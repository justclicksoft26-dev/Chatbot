"""
learning/embeddings.py — Vector Embeddings for Semantic Search
Gemini text-embedding-004 for Arabic-aware embeddings.
Cache stored in-memory (no DB persistence).
"""
import os
import json
import hashlib
import logging
import math
import threading
from typing import Optional

log = logging.getLogger("learning.embeddings")

_EMBED_MODEL = "text-embedding-004"
_EMBED_DIM = 768

# In-memory embedding cache: hash → {"text", "embedding", "category", "metadata"}
_CACHE: dict[str, dict] = {}
_cache_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════
# Embedding Generation
# ═══════════════════════════════════════════════════════════════════

def _get_embedding_gemini(text: str) -> list[float] | None:
    """Generate embedding using Gemini API."""
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=FutureWarning)
            import google.generativeai as genai
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None
        genai.configure(api_key=api_key)
        result = genai.embed_content(
            model=f"models/{_EMBED_MODEL}",
            content=text,
            task_type="SEMANTIC_SIMILARITY",
        )
        return result["embedding"]
    except Exception as e:
        log.debug(f"[EMBEDDING] Gemini embedding failed: {e}")
        return None


def get_embedding(text: str, category: str = "question") -> list[float] | None:
    """Get embedding — checks in-memory cache first, then generates via API."""
    text_hash = hashlib.md5(text.encode()).hexdigest()

    with _cache_lock:
        cached = _CACHE.get(text_hash)
        if cached:
            return cached["embedding"]

    embedding = _get_embedding_gemini(text)
    if embedding is None:
        return None

    with _cache_lock:
        _CACHE[text_hash] = {
            "text": text,
            "embedding": embedding,
            "category": category,
            "metadata": {},
        }
    return embedding


# ═══════════════════════════════════════════════════════════════════
# Similarity Search
# ═══════════════════════════════════════════════════════════════════

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_similar(
    query: str,
    category: str = "",
    top_k: int = 5,
    min_score: float = 0.7,
) -> list[dict]:
    """Find semantically similar texts in the in-memory cache."""
    query_emb = get_embedding(query, "query")
    if query_emb is None:
        return []

    with _cache_lock:
        entries = list(_CACHE.values())

    results = []
    for entry in entries:
        if category and entry.get("category") != category:
            continue
        stored_emb = entry.get("embedding")
        if not stored_emb:
            continue
        score = cosine_similarity(query_emb, stored_emb)
        if score >= min_score:
            results.append({
                "text": entry.get("text", ""),
                "category": entry.get("category", ""),
                "score": round(score, 4),
                "metadata": entry.get("metadata", {}),
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def find_similar_intent(question: str, top_k: int = 3) -> list[dict]:
    """Find similar past questions and their intents."""
    return find_similar(question, category="question", top_k=top_k, min_score=0.75)


# ═══════════════════════════════════════════════════════════════════
# Index Building
# ═══════════════════════════════════════════════════════════════════

def _store_in_cache(text: str, embedding: list[float], category: str,
                   metadata: dict) -> None:
    """Store an embedding in the in-memory cache."""
    text_hash = hashlib.md5(text.encode()).hexdigest()
    with _cache_lock:
        _CACHE[text_hash] = {
            "text": text,
            "embedding": embedding,
            "category": category,
            "metadata": metadata,
        }


def index_question(question: str, sub_intent: str, domain: str = "",
                   template: str = "") -> bool:
    """Add a question to the in-memory embedding index."""
    metadata = {"sub_intent": sub_intent, "domain": domain, "template": template}
    embedding = get_embedding(question, "question")
    if embedding is None:
        return False
    _store_in_cache(question, embedding, "question", metadata)
    return True


def index_erp_term(term_ar: str, term_en: str, domain: str = "",
                   sub_intent: str = "") -> bool:
    """Add an ERP term to the in-memory embedding index."""
    text = f"{term_ar} — {term_en}"
    metadata = {"term_ar": term_ar, "term_en": term_en,
                "domain": domain, "sub_intent": sub_intent}
    embedding = get_embedding(text, "term")
    if embedding is None:
        return False
    _store_in_cache(text, embedding, "term", metadata)
    return True


# ═══════════════════════════════════════════════════════════════════
# Stats
# ═══════════════════════════════════════════════════════════════════

def get_embedding_stats() -> dict:
    """Get in-memory embedding cache statistics."""
    with _cache_lock:
        total = len(_CACHE)
        by_cat: dict[str, int] = {}
        for entry in _CACHE.values():
            cat = entry.get("category", "unknown")
            by_cat[cat] = by_cat.get(cat, 0) + 1
    return {"total": total, "by_category": by_cat, "db_persistence": False}
