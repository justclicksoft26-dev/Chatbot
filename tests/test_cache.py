"""cache.py (LRU + TTL) and response_cache.py."""
import time

import pytest

import cache
import response_cache


@pytest.fixture
def c():
    return cache.LRUTTLCache("t", max_size=3, default_ttl=60)


def test_set_get_roundtrip(c):
    c.set("a", 1)
    assert c.get("a") == 1


def test_miss_returns_none_and_counts(c):
    assert c.get("nope") is None
    assert c.stats()["misses"] == 1


def test_expired_entry_is_evicted(c, monkeypatch):
    c.set("a", 1, ttl=10)
    now = time.time()
    monkeypatch.setattr(cache.time, "time", lambda: now + 11)
    assert c.get("a") is None
    assert c.stats()["size"] == 0


def test_lru_eviction_drops_oldest(c):
    for k in "abc":
        c.set(k, k)
    c.get("a")            # a becomes most recent
    c.set("d", "d")       # evicts b
    assert c.get("b") is None
    assert c.get("a") == "a"
    assert c.stats()["evictions"] == 1


def test_overwrite_does_not_evict(c):
    for k in "abc":
        c.set(k, k)
    c.set("a", "new")
    assert c.stats()["evictions"] == 0
    assert c.get("a") == "new"


def test_invalidate_all(c):
    c.set("a", 1); c.set("b", 2)
    assert c.invalidate() == 2
    assert c.stats()["size"] == 0


def test_invalidate_glob_matches_exact_prefix_only():
    big = cache.LRUTTLCache("t", max_size=10)
    big.set("dash:sales:1", 1)
    big.set("dash:sales:10", 2)
    big.set("dash:hr:1", 3)
    assert big.invalidate("dash:sales:1") == 1       # not the "…:10" entry
    assert big.get("dash:sales:10") == 2


def test_invalidate_glob_wildcard():
    big = cache.LRUTTLCache("t", max_size=10)
    big.set("dash:sales:1", 1); big.set("dash:hr:1", 2); big.set("sql:x", 3)
    assert big.invalidate("dash:*") == 2
    assert big.get("sql:x") == 3


def test_invalidate_glob_treats_dot_literally():
    big = cache.LRUTTLCache("t", max_size=10)
    big.set("k1.5", 1); big.set("k1x5", 2)
    assert big.invalidate("k1.5") == 1
    assert big.get("k1x5") == 2


def test_cleanup_expired(c, monkeypatch):
    c.set("old", 1, ttl=5); c.set("new", 2, ttl=500)
    now = time.time()
    monkeypatch.setattr(cache.time, "time", lambda: now + 10)
    assert c.cleanup_expired() == 1
    assert c.get("new") == 2


def test_hit_rate(c):
    c.set("a", 1); c.get("a"); c.get("a"); c.get("zzz")
    assert c.stats()["hit_rate"] == pytest.approx(66.7, abs=0.1)


def test_keys_are_whitespace_and_case_insensitive():
    assert cache.make_sql_key("SELECT  1\nFROM dual") == cache.make_sql_key("select 1 from DUAL")
    assert cache.make_schema_key("كام  عميل") == cache.make_schema_key("كام عميل")
    assert cache.make_dash_key("sales", "2") != cache.make_dash_key("sales", "3")


def test_global_helpers():
    cache.sql_cache.set("x", 1)
    assert cache.get_all_stats()["sql_results"]["size"] >= 1
    assert cache.invalidate_all()["sql_results"] >= 1
    assert cache.sql_cache.get("x") is None


# ── response_cache ──────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _clean_response_cache():
    response_cache.invalidate_all()
    yield
    response_cache.invalidate_all()


def test_response_cache_is_disabled_by_default():
    """Default TTL is 0: a stored answer must never be served back."""
    response_cache.put("q", "1", "2024", answer="a")
    assert response_cache.get("q", "1", "2024") is None
    assert response_cache.get_stats()["total_entries"] == 0


def test_response_cache_hit_with_ttl():
    response_cache.put("Q ", "1", "2024", answer="a", ttl=60)
    hit = response_cache.get("q", "1", "2024")
    assert hit and hit.answer == "a" and hit.hit_count == 1


def test_response_cache_key_includes_permissions_and_context():
    response_cache.put("q", "1", "2024", answer="admin data", ttl=60, user_role="admin:*:*")
    assert response_cache.get("q", "1", "2024", user_role="viewer::") is None
    assert response_cache.get("q", "1", "2024", user_role="admin:*:*", session_ctx="x") is None
    assert response_cache.get("q", "2", "2024", user_role="admin:*:*") is None
    assert response_cache.get("q", "1", "2024", user_role="admin:*:*") is not None


def test_response_cache_skips_errors_and_empty_answers():
    response_cache.put("q", "1", "2024", answer="x", method="error", ttl=60)
    response_cache.put("q2", "1", "2024", answer="", ttl=60)
    assert response_cache.get_stats()["total_entries"] == 0


def test_response_cache_expiry(monkeypatch):
    response_cache.put("q", "1", "2024", answer="a", ttl=30)
    now = time.time()
    monkeypatch.setattr(response_cache.time, "time", lambda: now + 31)
    assert response_cache.get("q", "1", "2024") is None


def test_response_cache_bounded(monkeypatch):
    monkeypatch.setattr(response_cache, "_MAX_ENTRIES", 5)
    for i in range(12):
        response_cache.put(f"q{i}", "1", "2024", answer="a", ttl=60)
    assert response_cache.get_stats()["total_entries"] <= 5


def test_invalidate_by_intent():
    response_cache.put("q1", "1", "2024", answer="a", template_used="customer_list", ttl=60)
    response_cache.put("q2", "1", "2024", answer="a", template_used="item_list", ttl=60)
    assert response_cache.invalidate_by_intent("customer") == 1
    assert response_cache.get("q2", "1", "2024") is not None
