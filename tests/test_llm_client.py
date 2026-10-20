"""LLM client logic that needs no network: provider fallback, history trimming, prompt assembly."""
import pytest

from llm import llm_client as llm


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setattr(llm, "_provider", None)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
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
    calls = _providers(monkeypatch, RuntimeError("Error 429 rate_limit"), "from gemini")
    assert llm._call_llm([], 0, 10) == "from gemini"
    assert calls == ["groq", "gemini"]


def test_gemini_primary_falls_back_to_groq(monkeypatch):
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
