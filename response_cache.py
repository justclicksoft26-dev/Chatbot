"""
response_cache.py — Smart Response Cache
Caches full pipeline responses for identical questions within a time window.
Reduces LLM calls for repeated questions (common in ERP usage patterns).

Cache key: question + company_code + fiscal_year (normalized)
TTL: configurable (default 5 minutes)
Invalidation: on schema refresh or learning feedback
"""
import time
import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("response_cache")

_cache: dict[str, "CacheEntry"] = {}
_MAX_ENTRIES = 200
_DEFAULT_TTL = 0    # disabled — every question hits DB fresh


@dataclass
class CacheEntry:
    key: str
    answer: str
    sql: str
    row_count: int
    method: str
    chart_data: Optional[dict]
    suggestions: list
    insights: list
    template_used: str
    created_at: float
    ttl: float
    hit_count: int = 0

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl


def _make_key(question: str, company_code: str = "1", fiscal_year: str = "2024",
              session_ctx: str = "", user_role: str = "") -> str:
    """Generate cache key from question + context + session state + permission fingerprint.

    user_role is the caller-supplied permission fingerprint string. The pipeline
    passes "role:domain1,domain2:branch1,branch2" so that two users who share
    the same role-string but have different domain or branch assignments never
    share a cache entry and cannot receive each other's data.

    session_ctx carries session-dependent values (e.g. txn_context INVTYPE) so
    that the same question with different session states gets different entries.
    """
    normalized = question.strip().lower()
    raw = f"{normalized}|{company_code}|{fiscal_year}|{session_ctx}|{user_role}"
    return hashlib.md5(raw.encode()).hexdigest()


def get(question: str, company_code: str = "1", fiscal_year: str = "2024",
        session_ctx: str = "", user_role: str = "") -> Optional[CacheEntry]:
    """Get cached response if valid."""
    key = _make_key(question, company_code, fiscal_year, session_ctx, user_role)
    entry = _cache.get(key)
    if entry and not entry.is_expired:
        entry.hit_count += 1
        log.debug(f"[CACHE] HIT: {question[:40]}... (hits={entry.hit_count})")
        return entry
    if entry and entry.is_expired:
        del _cache[key]
    return None


def put(question: str, company_code: str, fiscal_year: str,
        answer: str, sql: str = "", row_count: int = 0,
        method: str = "", chart_data: dict = None,
        suggestions: list = None, insights: list = None,
        template_used: str = "", ttl: float = _DEFAULT_TTL,
        session_ctx: str = "", user_role: str = ""):
    """Cache a pipeline response."""
    # Don't cache errors or empty results; ttl <= 0 means caching is switched off
    if method == "error" or not answer or ttl <= 0:
        return

    key = _make_key(question, company_code, fiscal_year, session_ctx, user_role)
    _cache[key] = CacheEntry(
        key=key,
        answer=answer,
        sql=sql,
        row_count=row_count,
        method=method,
        chart_data=chart_data,
        suggestions=suggestions or [],
        insights=insights or [],
        template_used=template_used,
        created_at=time.time(),
        ttl=ttl,
    )

    # Evict oldest if over limit
    if len(_cache) > _MAX_ENTRIES:
        oldest_key = min(_cache, key=lambda k: _cache[k].created_at)
        del _cache[oldest_key]

    log.debug(f"[CACHE] STORED: {question[:40]}... (ttl={ttl}s)")


def invalidate_all() -> int:
    """Clear entire cache. Called on schema refresh or bulk feedback."""
    count = len(_cache)
    _cache.clear()
    log.info(f"[CACHE] Invalidated all ({count} entries)")
    return count


def invalidate_by_intent(sub_intent: str) -> int:
    """Invalidate entries that used a specific template/intent."""
    keys_to_remove = [
        k for k, v in _cache.items()
        if v.template_used and sub_intent in v.template_used
    ]
    for k in keys_to_remove:
        del _cache[k]
    return len(keys_to_remove)


def get_stats() -> dict:
    """Cache statistics."""
    valid = sum(1 for v in _cache.values() if not v.is_expired)
    total_hits = sum(v.hit_count for v in _cache.values())
    return {
        "total_entries": len(_cache),
        "valid_entries": valid,
        "expired_entries": len(_cache) - valid,
        "total_hits": total_hits,
        "max_entries": _MAX_ENTRIES,
        "ttl_seconds": _DEFAULT_TTL,
    }
