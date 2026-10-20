"""LLM client logic that needs no network: provider fallback, history trimming, prompt assembly."""
import pytest

from llm import llm_client as llm


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setattr(llm, "_provider", None)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("GROQ_API_KEY", "q-key")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)           # retries must not slow the tests
    for key in llm._usage:
        llm._usage[key] = 0


def test_provider_defaults_to_groq_and_can_be_switched(monkeypatch):
    assert llm._get_provider() == "groq"
    llm.set_provider("Gemini")
    assert llm._get_provider() == "gemini"
    with pytest.raises(ValueError):
        llm.set_provider("openai")


def test_provider_comes_from_environment(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "GEMINI")
    assert llm._get_provider() == "gemini"


def test_usage_tracking_accumulates():
    llm._track_usage(10, 5)
    llm._track_usage(1, 2)
    usage = llm.get_usage()
    assert usage["total_tokens"] == 18 and usage["request_count"] == 2 and usage["last_prompt"] == 1
    usage["total_tokens"] = 0
    assert llm.get_usage()["total_tokens"] == 18          # a copy, not the live dict


def _providers(monkeypatch, groq, gemini):
    calls = []

    def make(name, outcome):
        def call(messages, temperature, max_tokens):
            calls.append(name)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return call
    monkeypatch.setattr(llm, "_call_groq", make("groq", groq))
    monkeypatch.setattr(llm, "_call_gemini", make("gemini", gemini))
    return calls


def test_rate_limited_primary_falls_back_to_the_other_provider(monkeypatch):
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    calls = _providers(monkeypatch, RuntimeError("Error 429 rate_limit"), "from gemini")
    assert llm._call_llm([], 0, 10) == "from gemini"
    assert calls == ["groq", "gemini"]


def test_gemini_primary_falls_back_to_groq(monkeypatch):
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    llm.set_provider("gemini")
    calls = _providers(monkeypatch, "from groq", RuntimeError("ResourceExhausted"))
    assert llm._call_llm([], 0, 10) == "from groq"
    assert calls == ["gemini", "groq"]


def test_other_errors_are_not_masked_by_fallback(monkeypatch):
    calls = _providers(monkeypatch, ValueError("bad request"), "never used")
    with pytest.raises(ValueError):
        llm._call_llm([], 0, 10)
    assert calls == ["groq"]


def test_all_providers_rate_limited_raises_last_error(monkeypatch):
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    _providers(monkeypatch, RuntimeError("429"), RuntimeError("429 again"))
    with pytest.raises(RuntimeError, match="again"):
        llm._call_llm([], 0, 10)


def test_trim_history_keeps_newest_within_budget_and_starts_with_user():
    history = [
        {"role": "user", "content": "a" * 50},
        {"role": "assistant", "content": "b" * 50},
        {"role": "user", "content": "c" * 50},
        {"role": "assistant", "content": "d" * 50},
    ]
    assert llm._trim_history(history, 120) == history[2:]
    # budget cuts so the oldest kept message is an assistant reply -> dropped, never start with one
    assert llm._trim_history(history, 160)[0]["role"] == "user"
    assert llm._trim_history(history, 0) == []
    assert llm._trim_history(None, 100) == []


def test_generate_sql_builds_prompt_and_strips_tenant_filters(monkeypatch):
    seen = {}

    def fake(messages, temperature, max_tokens):
        seen["messages"], seen["temperature"] = messages, temperature
        return "SELECT * FROM CUSTOMERS WHERE COMPANY_CODE = '1' AND CUST_TYPE = 0"

    monkeypatch.setattr(llm, "_call_llm", fake)
    history = [{"role": "user", "content": "سؤال سابق"}, {"role": "assistant", "content": "رد سابق"}]
    sql = llm.generate_sql("SCHEMA-CTX", "كم عميل؟", "1", "2024", history=history, extra_context="HINT")
    assert "COMPANY_CODE" not in sql and "CUST_TYPE = 0" in sql
    system = seen["messages"][0]["content"]
    assert "SCHEMA-CTX" in system and "{schema_context}" not in system and "HINT" in system
    assert [m["role"] for m in seen["messages"]] == ["system", "user", "assistant", "user"]
    assert seen["messages"][-1]["content"] == "كم عميل؟" and seen["temperature"] == 0


def test_format_answer_empty_result_matches_question_language(monkeypatch):
    monkeypatch.setattr(llm, "_call_llm", lambda *a, **k: pytest.fail("no LLM call for empty data"))
    assert "لم أجد" in llm.format_answer("كم عميل؟", [], "SELECT 1")
    assert "No matching data" in llm.format_answer("how many?", [], "SELECT 1")


@pytest.mark.parametrize("question,marker", [("كم عميل؟", "أجب بالعربية فقط"), ("how many?", "respond ONLY in English")])
def test_format_answer_forces_question_language(monkeypatch, question, marker):
    seen = {}
    monkeypatch.setattr(llm, "_call_llm", lambda messages, **k: seen.setdefault("m", messages) and "ok")
    assert llm.format_answer(question, [{"A": 1}], "SELECT 1", truncated=True, extra_context="COLS") == "ok"
    assert marker in seen["m"][0]["content"] and "COLS" in seen["m"][0]["content"]
    assert "500" in seen["m"][-1]["content"]


def test_format_answer_only_sends_the_first_50_rows(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "_call_llm", lambda messages, **k: seen.setdefault("m", messages) and "ok")
    llm.format_answer("q", [{"N": i} for i in range(200)], "SELECT 1")
    assert "'N': 49" in seen["m"][-1]["content"] and "'N': 50" not in seen["m"][-1]["content"]


async def test_async_wrappers_delegate(monkeypatch):
    monkeypatch.setattr(llm, "_call_llm", lambda *a, **k: "SELECT 1 FROM DUAL")
    assert await llm.generate_sql_async("ctx", "q", "1", "2024") == "SELECT 1 FROM DUAL"
    assert "No matching" in await llm.format_answer_async("q", [], "SELECT 1")


def test_gemini_call_builds_valid_requests_with_the_real_sdk(monkeypatch):
    """The request objects come from the google-genai package; building them must not fail on a clean install."""
    pytest.importorskip("google.genai")

    class Response:
        text = " answer "
        usage_metadata = None

    class Models:
        def generate_content(self, **kwargs):
            self.kwargs = kwargs
            return Response()

    class Client:
        models = Models()

    monkeypatch.setattr(llm, "_gemini_client", Client())
    monkeypatch.setenv("GEMINI_MODEL", "some-model")
    out = llm._call_gemini([{"role": "system", "content": "S"}, {"role": "user", "content": "q"},
                            {"role": "assistant", "content": "a"}, {"role": "user", "content": "q2"}], 0.1, 50)
    sent = Client.models.kwargs
    assert out == "answer" and sent["model"] == "some-model" and len(sent["contents"]) == 3


# ── Gemini setup: model name, timeout, thinking, timing ──────────────
@pytest.fixture
def gemini(monkeypatch):
    pytest.importorskip("google.genai")
    monkeypatch.setattr(llm, "_thinking_supported", True)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_THINKING_LEVEL", raising=False)

    class Models:
        def __init__(self):
            self.calls = []
            self.fail_on_thinking = False

        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            if self.fail_on_thinking and kwargs["config"].thinking_config is not None:
                raise RuntimeError("400 INVALID_ARGUMENT: thinking_level is not supported by this model")

            class Usage:
                prompt_token_count, candidates_token_count, thoughts_token_count = 10, 5, 0

            class Response:
                text, usage_metadata = " SELECT 1 FROM DUAL ", Usage()
            return Response()

    class Client:
        models = Models()

    monkeypatch.setattr(llm, "_gemini_client", Client())
    return Client.models


MESSAGES = [{"role": "system", "content": "S"}, {"role": "user", "content": "q"}]


def test_default_model_is_defined_once_and_overridable(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert llm.gemini_model() == llm.GEMINI_DEFAULT_MODEL
    monkeypatch.setenv("GEMINI_MODEL", " my-model ")
    assert llm.gemini_model() == "my-model"
    from llm import image_analyzer
    assert "gemini-2.0" not in open(image_analyzer.__file__, encoding="utf-8").read()


def test_thinking_is_kept_low_by_default(gemini):
    assert llm._call_gemini(MESSAGES, 0, 50) == "SELECT 1 FROM DUAL"
    assert gemini.calls[0]["config"].thinking_config.thinking_level.value.lower() == "low"


@pytest.mark.parametrize("value", ["off", "default", ""])
def test_thinking_can_be_left_to_the_model(gemini, monkeypatch, value):
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", value)
    llm._call_gemini(MESSAGES, 0, 50)
    assert gemini.calls[0]["config"].thinking_config is None


def test_a_model_that_rejects_thinking_is_retried_without_it_once(gemini):
    gemini.fail_on_thinking = True
    assert llm._call_gemini(MESSAGES, 0, 50) == "SELECT 1 FROM DUAL"
    assert len(gemini.calls) == 2 and gemini.calls[1]["config"].thinking_config is None
    llm._call_gemini(MESSAGES, 0, 50)
    assert len(gemini.calls) == 3 and gemini.calls[2]["config"].thinking_config is None      # remembered


def test_other_errors_are_not_retried(gemini):
    def boom(**kwargs):
        gemini.calls.append(kwargs)
        raise RuntimeError("404 NOT_FOUND model is not found")
    gemini.generate_content = boom
    with pytest.raises(RuntimeError, match="404"):
        llm._call_gemini(MESSAGES, 0, 50)
    assert len(gemini.calls) == 1


def test_each_call_logs_its_duration_and_token_use(gemini, caplog):
    with caplog.at_level("INFO", logger="llm"):
        llm._call_gemini(MESSAGES, 0, 50)
    assert any("gemini" in r.getMessage() and "thoughts=0" in r.getMessage() for r in caplog.records)


def test_an_empty_reply_is_an_error_not_a_crash(gemini):
    def empty(**kwargs):
        class R:
            text, usage_metadata, candidates = None, None, []
        return R()
    gemini.generate_content = empty
    with pytest.raises(RuntimeError, match="no text"):
        llm._call_gemini(MESSAGES, 0, 50)


def test_the_client_gets_a_request_timeout(monkeypatch):
    pytest.importorskip("google.genai")
    seen = {}

    class FakeClient:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    import google.genai as genai
    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setattr(llm, "_gemini_client", None)
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45")
    llm._get_gemini_client()
    assert seen["http_options"].timeout == 45000
    monkeypatch.setattr(llm, "_gemini_client", None)
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "junk")
    llm._get_gemini_client()
    assert seen["http_options"].timeout == 60000


# ── retries, and only providers that can work ────────────────────────
def test_a_busy_model_is_retried_before_giving_up_on_it(monkeypatch):
    outcomes = iter([RuntimeError("503 UNAVAILABLE: high demand"), RuntimeError("504 DEADLINE_EXCEEDED"), "recovered"])
    calls, waits = [], []

    def groq(messages, temperature, max_tokens):
        calls.append("groq")
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(llm, "_call_groq", groq)
    monkeypatch.setattr(llm.time, "sleep", waits.append)
    assert llm._call_llm([], 0, 10) == "recovered" and calls == ["groq"] * 3 and len(waits) == 2


def test_the_wait_follows_what_the_api_asks_for_but_never_exceeds_the_limit(monkeypatch):
    waits = []
    calls = _providers(monkeypatch, RuntimeError("429 RESOURCE_EXHAUSTED. Please retry in 7.2s."), "from gemini")
    monkeypatch.setattr(llm.time, "sleep", waits.append)
    llm._call_llm([], 0, 10)
    assert waits[:2] == [7.7, 7.7] and calls[-1] == "gemini"

    calls.clear()
    waits.clear()
    _providers(monkeypatch, RuntimeError("429 quota. Please retry in 300s"), "from gemini")       # far too long to wait
    monkeypatch.setattr(llm.time, "sleep", waits.append)
    assert llm._call_llm([], 0, 10) == "from gemini" and waits == []


def test_a_provider_without_a_key_is_never_the_fallback(monkeypatch):
    """Regression: a quota error from Gemini turned into 'groq model not found' because Groq was tried blindly."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    llm.set_provider("gemini")
    calls = _providers(monkeypatch, "never used", RuntimeError("429 RESOURCE_EXHAUSTED"))
    with pytest.raises(RuntimeError, match="429"):
        llm._call_llm([], 0, 10)
    assert calls == ["gemini"]


def test_usable_providers_order_and_filtering(monkeypatch):
    assert llm._usable_providers("gemini") == ["gemini", "groq"]
    assert llm._usable_providers("groq") == ["groq", "gemini"]
    monkeypatch.delenv("GEMINI_API_KEY")
    assert llm._usable_providers("gemini") == ["groq"]
    monkeypatch.delenv("GROQ_API_KEY")
    assert llm._usable_providers("gemini") == ["gemini"]            # nothing configured: keep the primary, its error is the useful one
