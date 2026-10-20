"""
llm_client.py — JustClick AI Chatbot
يدعم Gemini و Groq — يختار الـ provider من LLM_PROVIDER في .env
"""
import os
import re
import time
import asyncio
import logging

import profiles

log = logging.getLogger("llm")

MAX_PROMPT_CHARS = 28000
_provider = None

# ── Proactive rate-limit guard ─────────────────────────────────────
# Groq free tier: ~6000 TPM for openai/gpt-oss-120b. Each LLM call uses
# ~2000-4000 tokens. Space calls ≥25s apart to stay within the 60s window.
_last_groq_call_time = 0.0
_GROQ_MIN_INTERVAL = 25.0   # seconds between Groq calls


def _groq_cooldown():
    """Sleep if last Groq call was within _GROQ_MIN_INTERVAL seconds.
    Safe to call from a thread (via asyncio.to_thread) — never blocks the event loop directly.
    """
    global _last_groq_call_time
    elapsed = time.time() - _last_groq_call_time
    if _last_groq_call_time > 0 and elapsed < _GROQ_MIN_INTERVAL:
        sleep_t = _GROQ_MIN_INTERVAL - elapsed
        log.info(f"[GROQ] proactive cooldown: {sleep_t:.1f}s")
        time.sleep(sleep_t)


# ── Token usage tracking ───────────────────────────────────────────
_usage = {
    "total_prompt": 0,
    "total_completion": 0,
    "total_tokens": 0,
    "request_count": 0,
    "last_prompt": 0,
    "last_completion": 0,
}


def get_usage() -> dict:
    return dict(_usage)


def _track_usage(prompt_tokens: int, completion_tokens: int):
    _usage["last_prompt"] = prompt_tokens
    _usage["last_completion"] = completion_tokens
    _usage["total_prompt"] += prompt_tokens
    _usage["total_completion"] += completion_tokens
    _usage["total_tokens"] = _usage["total_prompt"] + _usage["total_completion"]
    _usage["request_count"] += 1


def _get_provider() -> str:
    global _provider
    if _provider is None:
        _provider = os.getenv("LLM_PROVIDER", "groq").lower()
        log.info(f"[LLM] provider={_provider}")
    return _provider


def set_provider(name: str):
    global _provider
    name = name.lower()
    if name not in ("groq", "gemini"):
        raise ValueError(f"Unknown provider: {name}")
    _provider = name
    log.info(f"[LLM] provider switched to {name}")


# ── Gemini ──────────────────────────────────────────────────────────

_gemini_client = None


GEMINI_DEFAULT_MODEL = "gemini-3.8-flash"      # Google retires models; set GEMINI_MODEL in .env to change
_thinking_supported = True                       # turned off for the process if the API rejects the setting


def gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", "").strip() or GEMINI_DEFAULT_MODEL


def _llm_timeout_seconds() -> int:
    try:
        return max(5, int(os.getenv("LLM_TIMEOUT_SECONDS", "60")))
    except ValueError:
        return 60


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        from google.genai import types
        # without a timeout one stuck request would keep a question "processing" forever
        _gemini_client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options=types.HttpOptions(timeout=_llm_timeout_seconds() * 1000),
        )
        log.info(f"[LLM] Gemini client ready, model={gemini_model()}, timeout={_llm_timeout_seconds()}s")
    return _gemini_client


def _thinking_config(types):
    """Writing SQL needs little reasoning, and hidden "thinking" is what makes answers take a minute.
    GEMINI_THINKING_LEVEL (default "low"; "off"/"default" = leave the model's own setting)."""
    level = os.getenv("GEMINI_THINKING_LEVEL", "low").strip().lower()
    if not _thinking_supported or level in ("", "off", "default", "none"):
        return None
    try:
        return types.ThinkingConfig(thinking_level=level)
    except Exception:                                      # an SDK without the field
        return None


def _call_gemini(messages: list, temperature: float, max_tokens: int) -> str:
    global _thinking_supported
    from google.genai import types

    system_text = ""
    contents = []
    for msg in messages:
        if msg["role"] == "system":
            system_text += msg["content"] + "\n"
        elif msg["role"] == "user":
            contents.append(types.Content(role="user",
                parts=[types.Part(text=msg["content"])]))
        elif msg["role"] == "assistant":
            contents.append(types.Content(role="model",
                parts=[types.Part(text=msg["content"])]))

    client = _get_gemini_client()
    model_name = gemini_model()

    def run(thinking):
        cfg = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_text.strip() if system_text else None,
            thinking_config=thinking,
        )
        return client.models.generate_content(model=model_name, contents=contents, config=cfg)

    started = time.time()
    thinking = _thinking_config(types)
    try:
        resp = run(thinking)
    except Exception as exc:
        # a model that does not know the thinking setting answers 400 mentioning it: retry once without
        if thinking is not None and "thinking" in str(exc).lower():
            log.warning(f"[LLM] {model_name} rejected the thinking setting; continuing without it")
            _thinking_supported = False
            resp = run(None)
        else:
            raise

    usage = resp.usage_metadata
    if usage:
        _track_usage(usage.prompt_token_count or 0, usage.candidates_token_count or 0)
    log.info("[LLM] gemini %s %.1fs prompt=%s out=%s thoughts=%s", model_name, time.time() - started,
             getattr(usage, "prompt_token_count", "-"), getattr(usage, "candidates_token_count", "-"),
             getattr(usage, "thoughts_token_count", "-"))
    if not resp.text:
        reason = getattr(resp.candidates[0], "finish_reason", "?") if getattr(resp, "candidates", None) else "?"
        raise RuntimeError(f"the model returned no text (finish_reason={reason})")
    return resp.text.strip()


# ── Groq ────────────────────────────────────────────────────────────

_groq_client = None


def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        # max_retries=0: disable SDK auto-retry so our _call_llm handles backoff
        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"), max_retries=0)
    return _groq_client


def _get_groq_model():
    # llama-3.1-8b-instant: 128k context + 20k TPM (vs 70b's 6k TPM).
    # Switch to "llama-3.3-70b-versatile" via GROQ_MODEL env var for higher quality.
    return os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")


def _call_groq(messages: list, temperature: float, max_tokens: int) -> str:
    global _last_groq_call_time
    _groq_cooldown()
    try:
        resp = _get_groq_client().chat.completions.create(
            model=_get_groq_model(),
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=25.0,
        )
        _last_groq_call_time = time.time()
        if resp.usage:
            _track_usage(resp.usage.prompt_tokens, resp.usage.completion_tokens)
        return resp.choices[0].message.content.strip()
    except Exception as e:
        err = str(e)
        # Groq returns 413 for both "payload too large" AND "context too long", and
        # both error bodies contain "rate_limit" — so we cannot exclude rate_limit here.
        # Detect by HTTP status 413 OR by "too large" / "context" keywords, then retry.
        is_size_413 = ("413" in err or "too large" in err.lower()
                       or "request too large" in err.lower()
                       or ("context" in err.lower() and "limit" in err.lower()))
        if is_size_413:
            if len(messages) > 2:
                # Conversation history is inflating the payload —
                # retry with system + last user message only.
                log.warning("[LLM] groq 413 payload too large — retrying without history")
                retry_msgs = [messages[0], messages[-1]]
                retry_max = max_tokens
            else:
                # Already minimal (system + user only).  The schema context itself
                # is pushing past Groq's 8 192-token limit.
                # Arabic tokenises at ≈1.5 chars/token, so a 10 000-char system prompt
                # ≈ 6 700 tokens.  With max_tokens=2000 that's 8 700 > 8 192 → 413.
                # Freeing the output budget to 1200 gives the 70B model enough room
                # for complex SQL while reducing total tokens if a 413 still occurs.
                log.warning("[LLM] groq 413 schema too large — retrying with max_tokens=1200")
                retry_msgs = messages
                retry_max = 1200
            resp = _get_groq_client().chat.completions.create(
                model=_get_groq_model(),
                messages=retry_msgs,
                temperature=temperature,
                max_tokens=retry_max,
                timeout=25.0,
            )
            if resp.usage:
                _track_usage(resp.usage.prompt_tokens, resp.usage.completion_tokens)
            return resp.choices[0].message.content.strip()
        raise


# ── Unified call ────────────────────────────────────────────────────

_RATE_LIMITED = re.compile(r"\b429\b|rate_limit|resource_?exhausted|quota", re.IGNORECASE)
_TRANSIENT = re.compile(r"\b50[0234]\b|UNAVAILABLE|overloaded|high demand|DEADLINE_EXCEEDED|timed out|timeout|"
                        r"connection (reset|error|aborted)|returned no text", re.IGNORECASE)
_RETRY_DELAY = re.compile(r"retry(?: in|Delay['\"]?:?)\s*['\"]?(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _usable_providers(primary: str) -> list[str]:
    """Primary first, then the other one, but only providers that have an API key: falling back to a
    provider that cannot work only replaces the real error (say, a quota) with a confusing one."""
    order = ["groq", "gemini"] if primary == "groq" else ["gemini", "groq"]
    keys = {"gemini": os.getenv("GEMINI_API_KEY", "").strip(), "groq": os.getenv("GROQ_API_KEY", "").strip()}
    return [p for p in order if keys[p]] or order[:1]


def _retry_wait(error_text: str, attempt: int) -> float:
    """Seconds to wait before trying again: what the API asks for, else a short growing pause."""
    found = _RETRY_DELAY.search(error_text)
    return float(found.group(1)) + 0.5 if found else 2.0 * (attempt + 1)


def _call_llm(messages: list, temperature: float, max_tokens: int) -> str:
    providers = _usable_providers(_get_provider())
    max_retries = _int_env("LLM_MAX_RETRIES", 2)
    max_wait = _int_env("LLM_RETRY_MAX_WAIT_SECONDS", 20)
    last_err = None
    for prov in providers:
        call = _call_gemini if prov == "gemini" else _call_groq
        for attempt in range(max_retries + 1):
            try:
                return call(messages, temperature, max_tokens)
            except Exception as e:
                err_s = str(e)
                limited, transient = bool(_RATE_LIMITED.search(err_s)), bool(_TRANSIENT.search(err_s))
                if not (limited or transient):
                    raise
                last_err = e
                wait = _retry_wait(err_s, attempt)
                if attempt < max_retries and wait <= max_wait:
                    log.warning(f"[LLM] {prov} {'rate-limited' if limited else 'unavailable'}; "
                                f"retry {attempt + 1}/{max_retries} in {wait:.1f}s")
                    time.sleep(wait)
                    continue
                log.warning(f"[LLM] {prov} {'rate-limited' if limited else 'unavailable'}; giving up on it")
                break
    raise last_err


def _trim_history(history: list, budget: int) -> list:
    if not history:
        return []
    trimmed, used = [], 0
    for msg in reversed(history):
        msg_len = len(msg.get("content", ""))
        if used + msg_len > budget:
            break
        trimmed.insert(0, msg)
        used += msg_len
    while trimmed and trimmed[0].get("role") == "assistant":
        trimmed.pop(0)
    return trimmed


# ══════════════════════════════════════════════════════════════════════
# generate_sql
# ══════════════════════════════════════════════════════════════════════

def generate_sql(schema_context: str, question: str, company_code: str,
                 fiscal_year: str, history: list = None,
                 extra_context: str = "") -> str:

    system_prompt = profiles.part("prompts").SQL_SYSTEM_PROMPT.replace("{schema_context}", schema_context)

    # SQL examples — loaded from justclick_comments.sql (@SQL_EXAMPLE_START blocks),
    # NOT hardcoded here.  Editing the file = change takes effect on next request.
    try:
        from nlu.schema_loader import get_sql_examples
        _examples = get_sql_examples()
    except Exception:
        _examples = ""
    if _examples:
        system_prompt += f"\n\n{_examples}"

    # Q3 fix: elevate ⚠ comment warnings from inline description to MANDATORY
    # constraints so the LLM cannot ignore them (e.g. INVID not unique across invoice
    # types → a lookup by INVID must be scoped by INVTYPE). Comment-sourced only.
    try:
        from nlu.schema_loader import get_comment_constraints
        _constraints = get_comment_constraints(question)
    except Exception:
        _constraints = ""
    if _constraints:
        system_prompt += (
            "\n\n══ قيود إلزامية من الكومنتات (⚠ — التزم بها حرفياً، لا تتجاهلها) ══\n"
            "تحذيرات من تعليقات الأعمدة يجب احترامها في الـ SQL. مثال: عمود غير فريد عبر "
            "الأنواع يجب تقييده بالنوع المناسب في WHERE:\n"
            f"{_constraints}"
        )

    # Phase 3/4/5: Inject learned context, JOIN hints, followup context
    if extra_context:
        system_prompt += f"\n{extra_context}"

    history_budget = MAX_PROMPT_CHARS - len(system_prompt) - len(question) - 500
    trimmed = _trim_history(history or [], max(0, history_budget))

    messages = [{"role": "system", "content": system_prompt}]
    for msg in trimmed:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    start_t = time.time()
    # max_tokens=2000: llama-3.3-70b-versatile has a 128k-token context window,
    # so the old 8B-era cap of 800 is no longer needed.  Complex Oracle SQL with
    # multiple JOINs can reach 600-800 tokens; 2000 gives a safe margin.
    result = _call_llm(messages, temperature=0, max_tokens=2000)

    return _strip_tenant_filters(result)


def _strip_tenant_filters(sql: str) -> str:
    """Remove COMPANY_CODE / FISCAL_YEAR conditions the LLM may generate."""
    from security.query_policy import strip_tenant_conditions
    return strip_tenant_conditions(sql)


# ══════════════════════════════════════════════════════════════════════
# format_answer
# ══════════════════════════════════════════════════════════════════════

def format_answer(question: str, data: list[dict], sql: str,
                  history: list = None, truncated: bool = False,
                  extra_context: str = "") -> str:

    # CHANGE 4: detect the question's language ONCE and apply it to EVERY response,
    # not just the empty-result message.
    is_arabic = any('؀' <= c <= 'ۿ' for c in question)

    if not data:
        if is_arabic:
            return "لم أجد بيانات مطابقة لسؤالك. جرّب إعادة صياغة السؤال أو توسيع نطاق البحث."
        return "No matching data found. Try rephrasing your question or broadening the search criteria."

    system_prompt = profiles.part("prompts").ANALYST_SYSTEM_PROMPT

    # RC5: inject column business meanings (from schema comments) so the narrative
    # is grounded in what each column actually represents — also for the template path.
    if extra_context:
        system_prompt += f"\n\n══ معاني الأعمدة (للفهم فقط — لا تعرضها كأسماء تقنية) ══\n{extra_context}"

    # CHANGE 4: force the answer language to match the question language.
    if is_arabic:
        system_prompt += ("\n\n══ لغة الإجابة ══\n"
                          "سؤال المستخدم بالعربية — أجب بالعربية فقط.")
    else:
        system_prompt += ("\n\n== Response Language ==\n"
                          "The user's question is in English — respond ONLY in English. "
                          "Translate any Arabic column labels or coded values to English.")

    data_str = str(data[:50])
    history_budget = MAX_PROMPT_CHARS - len(system_prompt) - len(data_str) - len(question) - 500
    trimmed = _trim_history(history or [], max(0, history_budget))

    messages = [{"role": "system", "content": system_prompt}]
    for msg in trimmed:
        messages.append({"role": msg["role"], "content": msg["content"]})
    trunc_note = "\n\n(ملاحظة: النتائج مقتصرة على أول 500 سجل — أشر لذلك باختصار)" if truncated else ""
    messages.append({
        "role": "user",
        "content": f"السؤال: {question}\n\nالبيانات:\n{data_str}{trunc_note}"
    })

    return _call_llm(messages, temperature=0.25, max_tokens=1500)


# ── Async wrappers — run blocking LLM calls in a thread ──────────────────────
# This keeps the asyncio event loop free during Groq cooldown + HTTP wait.

async def generate_sql_async(schema_context: str, question: str, company_code: str,
                              fiscal_year: str, history: list = None,
                              extra_context: str = "") -> str:
    return await asyncio.to_thread(
        generate_sql, schema_context, question, company_code,
        fiscal_year, history, extra_context,
    )


async def format_answer_async(question: str, data: list, sql: str,
                               history: list = None, truncated: bool = False,
                               extra_context: str = "") -> str:
    return await asyncio.to_thread(
        format_answer, question, data, sql, history, truncated, extra_context,
    )