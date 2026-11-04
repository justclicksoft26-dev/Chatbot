"""The load-test arithmetic: percentiles, the acceptance rule and the report."""
import pytest

from uat import load_test as lt


def run(seconds, oks, p95=25.0, max_err=2.0):
    results = [{"seconds": s, "ok": ok, "why": "" if ok else "HTTP 429", "question": "q"} for s, ok in zip(seconds, oks)]
    return lt.summarize(results, wall_seconds=30.0, p95_limit=p95, max_error_pct=max_err)


def test_the_95th_percentile_is_the_value_below_which_95_percent_fall():
    assert lt.percentile(list(range(1, 101)), 95) == 95
    assert lt.percentile([7], 95) == 7 and lt.percentile([], 95) == 0.0


def test_fast_and_error_free_is_accepted():
    s = run([2.0] * 50, [True] * 50)
    assert s["accepted"] and s["median"] == 2.0 and s["p95"] == 2.0 and s["error_pct"] == 0.0


def test_one_slow_tail_beyond_the_limit_fails_the_run():
    s = run([2.0] * 45 + [40.0] * 5, [True] * 50)
    assert s["p95"] == 40.0 and not s["accepted"]


def test_errors_above_the_allowed_share_fail_the_run_and_are_explained():
    s = run([1.0] * 50, [True] * 47 + [False] * 3)
    assert s["error_pct"] == 6.0 and not s["accepted"] and s["reasons"] == {"HTTP 429": 3}


def test_one_error_in_fifty_is_within_two_percent():
    assert run([1.0] * 50, [True] * 49 + [False])["accepted"]


def test_no_answers_at_all_is_never_accepted():
    assert not lt.summarize([], 1.0, 25.0, 2.0)["accepted"]


def test_the_report_says_what_was_measured_and_the_cost_when_prices_are_set(tmp_path):
    s = run([2.0] * 50, [True] * 50)
    used = {"today": {"requests": 50, "prompt": 150000, "completion": 5000, "cost_estimate": {"amount": 0.35, "currency": "USD"}}}
    path = lt.write_report(s, used, str(tmp_path), users=50, rounds=1)
    text = open(path, encoding="utf-8").read()
    assert "مقبول ✅" in text and "50 مستخدماً" in text and "0.35 USD" in text and "p95" in text


def test_the_report_asks_for_prices_when_none_are_set(tmp_path):
    s = run([2.0] * 5, [True] * 5)
    text = open(lt.write_report(s, {"today": {"requests": 5, "prompt": 1, "completion": 1, "cost_estimate": None}},
                                str(tmp_path), 5, 1), encoding="utf-8").read()
    assert "LLM_PRICE_IN_PER_MILLION" in text
