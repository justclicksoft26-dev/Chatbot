"""
cache.py — Unified Caching Layer (LRU + TTL)
يدعم 3 مستويات:
  1. SQL Results    — hash(sql)           — TTL 5 دقايق
  2. Dashboard      — dash_id + company   — TTL 10 دقايق
  3. Schema Context — hash(question)      — TTL 5 دقايق

Thread-safe باستخدام threading.Lock.
بدون dependencies خارجية (Redis-ready interface لو محتاج ترقية).
"""
import time
import fnmatch
import hashlib
import threading
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("cache")

# ── Cache TTL defaults (seconds) ─────────────────────────────────
TTL_SQL = 300           # 5 minutes
TTL_DASHBOARD = 600     # 10 minutes
TTL_SCHEMA = 300        # 5 minutes — short TTL so justclick_comments.sql edits
                        # propagate within one cache window (hot-reload backs this up)

# ── Max entries per cache tier ───────────────────────────────────
MAX_SQL_ENTRIES = 500
MAX_DASH_ENTRIES = 50
MAX_SCHEMA_ENTRIES = 100


@dataclass
class CacheEntry:
    """Single cache entry with metadata."""
    key: str
    data: Any
    created_at: float
    ttl: int
    hit_count: int = 0
    last_hit: float = 0.0


class LRUTTLCache:
    """
    LRU cache with per-entry TTL.
    - get() returns None for expired entries (auto-evicts)
    - set() evicts oldest when max_size reached
    - Thread-safe via Lock
    """

    def __init__(self, name: str, max_size: int = 500, default_ttl: int = 300):
        self.name = name
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "sets": 0,
        }

    def get(self, key: str) -> Optional[Any]:
        """Get value by key. Returns None if missing or expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._stats["misses"] += 1
                return None

            # Check TTL
            if time.time() - entry.created_at > entry.ttl:
                # Expired — evict
                del self._store[key]
                self._stats["misses"] += 1
                self._stats["evictions"] += 1
                return None

            # Hit — move to end (most recently used)
            self._store.move_to_end(key)
            entry.hit_count += 1
            entry.last_hit = time.time()
            self._stats["hits"] += 1
            return entry.data

    def set(self, key: str, value: Any, ttl: int = None) -> None:
        """Set a value with optional TTL override."""
        with self._lock:
            # If key exists, update it
            if key in self._store:
                del self._store[key]

            # Evict oldest if at capacity
            while len(self._store) >= self.max_size:
                evicted_key, _ = self._store.popitem(last=False)
                self._stats["evictions"] += 1

            self._store[key] = CacheEntry(
                key=key,
                data=value,
                created_at=time.time(),
                ttl=ttl or self.default_ttl,
            )
            self._stats["sets"] += 1

    def invalidate(self, pattern: str = None) -> int:
        """
        Invalidate cache entries.
        - pattern=None → clear all
        - pattern="dash:*" → clear matching keys (glob-style)
        Returns count of removed entries.
        """
        with self._lock:
            if pattern is None:
                count = len(self._store)
                self._store.clear()
                return count

            regex = re.compile(fnmatch.translate(pattern))  # anchored, other chars literal
            to_remove = [k for k in self._store if regex.match(k)]
            for k in to_remove:
                del self._store[k]
            return len(to_remove)

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        with self._lock:
            now = time.time()
            expired = [
                k for k, v in self._store.items()
                if now - v.created_at > v.ttl
            ]
            for k in expired:
                del self._store[k]
                self._stats["evictions"] += 1
            return len(expired)

    def stats(self) -> dict:
        """Return cache statistics."""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            return {
                "name": self.name,
                "size": len(self._store),
                "max_size": self.max_size,
                "default_ttl": self.default_ttl,
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "hit_rate": round(self._stats["hits"] / total * 100, 1) if total else 0,
                "evictions": self._stats["evictions"],
                "sets": self._stats["sets"],
            }


# ══════════════════════════════════════════════════════════════════
# Global Cache Instances
# ══════════════════════════════════════════════════════════════════

sql_cache = LRUTTLCache("sql_results", max_size=MAX_SQL_ENTRIES, default_ttl=TTL_SQL)
dash_cache = LRUTTLCache("dashboards", max_size=MAX_DASH_ENTRIES, default_ttl=TTL_DASHBOARD)
schema_cache = LRUTTLCache("schema_ctx", max_size=MAX_SCHEMA_ENTRIES, default_ttl=TTL_SCHEMA)


# ══════════════════════════════════════════════════════════════════
# Helper Functions
# ══════════════════════════════════════════════════════════════════

def make_sql_key(sql: str) -> str:
    """Generate cache key from SQL string."""
    normalized = " ".join(sql.lower().split())
    return f"sql:{hashlib.md5(normalized.encode('utf-8')).hexdigest()}"


def make_dash_key(dashboard_id: str, company_code: str = "1") -> str:
    """Generate cache key for dashboard."""
    return f"dash:{dashboard_id}:{company_code}"


def make_schema_key(question: str) -> str:
    """Generate cache key for schema context."""
    normalized = " ".join(question.lower().split())
    return f"schema:{hashlib.md5(normalized.encode('utf-8')).hexdigest()}"


def get_all_stats() -> dict:
    """Return stats for all cache tiers."""
    return {
        "sql_results": sql_cache.stats(),
        "dashboards": dash_cache.stats(),
        "schema_context": schema_cache.stats(),
    }


def invalidate_all() -> dict:
    """Clear all caches. Returns counts per tier."""
    return {
        "sql_results": sql_cache.invalidate(),
        "dashboards": dash_cache.invalidate(),
        "schema_context": schema_cache.invalidate(),
    }


def cleanup_all_expired() -> dict:
    """Remove expired entries from all tiers."""
    return {
        "sql_results": sql_cache.cleanup_expired(),
        "dashboards": dash_cache.cleanup_expired(),
        "schema_context": schema_cache.cleanup_expired(),
    }
