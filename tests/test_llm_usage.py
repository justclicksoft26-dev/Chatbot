"""The model budget: what was used today, what it cost, and the daily cap that stops the spending."""
import json

import pytest

import pipeline
from llm import llm_client as llm


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for key in llm._usage:
        llm._usage[key] = 0


def test_calls_are_counted_per_day_with_their_tokens():
    llm._track_usage(1000, 50)
    llm._track_usage(2000, 30)
    today = llm.get_usage()["today"]
    assert (today["requests"], today["prompt"], today["completion"]) == (2, 3000, 80)


def test_the_days_count_survives_a_restart(tmp_path):
    llm._track_usage(1000, 50)
    llm._daily.clear()                                  # a new process: nothing in memory
    llm._daily_loaded_from = None
    assert llm.get_usage()["today"]["requests"] == 1
    assert json.loads(open(llm._usage_file(), encoding="utf-8").read())[llm._today()]["requests"] == 1


def test_a_missing_or_damaged_file_starts_the_day_at_zero(tmp_path, monkeypatch):
    open(tmp_path / "llm_usage.json", "w").write("{not json")
    llm._daily_loaded_from = None
    assert llm.get_usage()["today"]["requests"] == 0


def test_only_a_month_of_history_is_kept():
    llm._daily_loaded_from = llm._usage_file()                         # history already loaded: do not re-read the file
    for day in range(40):
        llm._daily[f"2026-01-{day + 1:02d}"] = {"requests": 1, "prompt": 1, "completion": 1}
    llm._track_usage(1, 1)
    assert len(llm._daily) == 31


def test_no_cost_is_shown_until_the_prices_are_set(monkeypatch):
    llm._track_usage(1_000_000, 100_000)
    assert llm.get_usage()["today"]["cost_estimate"] is None
    monkeypatch.setenv("LLM_PRICE_IN_PER_MILLION", "2")
    assert llm.get_usage()["today"]["cost_estimate"] is None          # both prices are needed


def test_the_cost_follows_the_prices_the_operator_set(monkeypatch):
    monkeypatch.setenv("LLM_PRICE_IN_PER_MILLION", "2")
    monkeypatch.setenv("LLM_PRICE_OUT_PER_MILLION", "10")
    monkeypatch.setenv("LLM_PRICE_CURRENCY", "EUR")
    llm._track_usage(1_000_000, 100_000)
    assert llm.get_usage()["today"]["cost_estimate"] == {"amount": 3.0, "currency": "EUR"}
    assert llm.estimate_cost(500_000, 0) == {"amount": 1.0, "currency": "EUR"}


def test_no_limit_by_default_and_the_cap_stops_the_next_call(monkeypatch):
    for _ in range(5):
        llm._track_usage(1, 1)
    llm.check_daily_limit()                                           # unset: fine
    monkeypatch.setenv("LLM_DAILY_REQUEST_LIMIT", "5")
    with pytest.raises(llm.DailyLimitReached, match="LLM_DAILY_LIMIT"):
        llm.check_daily_limit()
    monkeypatch.setenv("LLM_DAILY_REQUEST_LIMIT", "6")
    llm.check_daily_limit()


def test_a_call_past_the_cap_never_reaches_the_provider(monkeypatch):
    monkeypatch.setenv("LLM_DAILY_REQUEST_LIMIT", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setattr(llm, "_provider", "gemini")
    reached = []
    monkeypatch.setattr(llm, "_call_gemini", lambda *a, **k: reached.append(1) or "SELECT 1 FROM DUAL")
    llm._track_usage(1, 1)
    with pytest.raises(llm.DailyLimitReached):
        llm._call_llm([{"role": "user", "content": "x"}], 0, 10)
    assert reached == []


@pytest.mark.usefixtures("justclick_profile")
async def test_the_user_is_told_the_daily_budget_is_used_up(monkeypatch):
    async def blocked(**kwargs):
        raise llm.DailyLimitReached("LLM_DAILY_LIMIT: 5/5 model calls made today")
    monkeypatch.setattr(pipeline, "generate_sql_async", blocked)
    r = await pipeline.process_question("كم عدد العملاء؟", user_id="u1", company_code="1", fiscal_year="2024")
    assert r.method == "error" and "الأقصى" in r.answer and "غد" in r.answer
