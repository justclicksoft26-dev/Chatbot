"""The sprint 4 security checks must fail when the system leaks and pass when it holds."""
import pytest
from fastapi.testclient import TestClient

import app as app_module
from uat import security_uat as su


def make(send, **kw):
    return su.Checks(send, kw.pop("api_key", "k"), kw.pop("admin_key", "a"), kw.pop("secrets", {}), **kw)


def by_id(checks):
    return {r[0]: r for r in checks.run()}


def locked_down(method, path, headers, body):
    """A server that behaves: 401 without a valid key, 403 on admin paths, refuses everything risky."""
    if headers.get("X-API-Key") != "k":
        return 401, {}
    if path != "/chat/" and headers.get("X-Admin-Key") != "a":
        return 403, {}
    return 200, {"answer": "لا يمكنني تنفيذ هذا", "sql_generated": "SELECT COUNT(*) FROM CUST"}


def test_a_locked_down_server_passes_every_check():
    results = by_id(make(locked_down))
    assert {k: v[2] for k, v in results.items()} == {
        "4.1": "PASS", "4.2": "PASS", "4.3": "PASS", "4.4": "PASS", "4.5": "PASS", "4.6": "PASS", "4.7": "PASS", "4.8": "WARN"}


def test_an_open_server_fails_the_key_checks():
    results = by_id(make(lambda m, p, h, b: (200, {"answer": "x", "sql_generated": ""})))
    assert results["4.1"][2] == results["4.2"][2] == results["4.3"][2] == results["4.4"][2] == "FAIL"


def test_a_generated_delete_fails_the_destructive_check():
    def sender(method, path, headers, body):
        if path == "/chat/" and headers.get("X-API-Key") == "k":
            return 200, {"answer": "تم", "sql_generated": "DELETE FROM CUST"}
        return locked_down(method, path, headers, body)
    assert by_id(make(sender))["4.5"][2] == "FAIL"


def test_changed_row_counts_fail_the_destructive_check_even_without_dml_in_the_reply():
    counts = iter([{"CUST": 38}, {"CUST": 0}])
    results = by_id(make(locked_down, row_counts=lambda: next(counts)))
    assert results["4.5"][2] == "FAIL" and "تغيّرت أعداد الصفوف" in results["4.5"][3]


def test_unchanged_row_counts_pass():
    results = by_id(make(locked_down, row_counts=lambda: {"CUST": 38, "MAIN_INV": 9}))
    assert results["4.5"][2] == "PASS"


def test_a_secret_in_an_answer_fails():
    def sender(method, path, headers, body):
        if path == "/chat/" and headers.get("X-API-Key") == "k":
            return 200, {"answer": "المفتاح super-secret-value", "sql_generated": ""}
        return locked_down(method, path, headers, body)
    results = by_id(make(sender, secrets={"API_KEY": "super-secret-value", "SHORT": "abc"}))
    assert results["4.6"][2] == "FAIL" and "API_KEY" in results["4.6"][3]


def test_a_dictionary_view_in_the_sql_fails():
    def sender(method, path, headers, body):
        if path == "/chat/" and headers.get("X-API-Key") == "k":
            return 200, {"answer": "x", "sql_generated": "SELECT USERNAME FROM DBA_USERS"}
        return locked_down(method, path, headers, body)
    assert by_id(make(sender))["4.7"][2] == "FAIL"


def test_a_configured_read_only_user_clears_the_warning():
    assert by_id(make(locked_down, db_user_set=True))["4.8"][2] == "PASS"


def test_the_report_is_accepted_only_without_a_failure(tmp_path):
    results = list(make(locked_down).run())
    path, accepted = su.write_report(results, str(tmp_path))
    assert accepted and "مقبول ✅" in open(path, encoding="utf-8").read()
    results[0] = ("4.1", "x", "FAIL", "d")
    assert su.write_report(results, str(tmp_path))[1] is False


def test_the_key_and_admin_checks_hold_on_the_real_app(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "k")
    monkeypatch.setenv("ADMIN_API_KEY", "a")
    client = TestClient(app_module.app)

    def send(method, path, headers, body):
        response = client.request(method, path, headers=headers, json=body)
        return response.status_code, (response.json() if response.content else {})

    results = {r[0]: r for r in su.Checks(send, "k", "a", {}).run() if r[0] in ("4.1", "4.2", "4.3", "4.4")}
    assert {k: v[2] for k, v in results.items()} == {"4.1": "PASS", "4.2": "PASS", "4.3": "PASS", "4.4": "PASS"}, results


# ── the role matrix ────────────────────────────────────────────────────
def matrix_sender(allowed_domains):
    """A server that answers permission_denied for every probe outside the given domains."""
    by_question = {q: d for d, q in su.DOMAIN_PROBES.items()}

    def send(method, path, headers, body):
        domain = by_question[body["question"]]
        return 200, {"method": "llm_controlled" if domain in allowed_domains else "permission_denied", "answer": "x"}
    return send


def test_the_role_matrix_passes_when_a_role_sees_exactly_its_domains():
    checks = su.Checks(matrix_sender({"inventory"}), "k", "a", {}, role_keys={"warehouse": "jc_x"})
    result = checks.role_matrix("warehouse", "jc_x")
    assert result[2] == "PASS", result


def test_the_role_matrix_fails_when_a_forbidden_domain_is_answered():
    checks = su.Checks(matrix_sender({"inventory", "hr"}), "k", "a", {})
    result = checks.role_matrix("warehouse", "jc_x")
    assert result[2] == "FAIL" and "hr" in result[3]


def test_the_role_matrix_fails_when_an_allowed_domain_is_refused():
    checks = su.Checks(matrix_sender(set()), "k", "a", {})
    result = checks.role_matrix("warehouse", "jc_x")
    assert result[2] == "FAIL" and "inventory" in result[3]
