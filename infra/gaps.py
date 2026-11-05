"""Questions the assistant could not answer: the backlog for improving the schema comments.

The assistant learns from the comments, so "training" it means writing the comment that was missing. This file keeps
the questions that ended without an answer (nothing found, a clarifying question, an error), and groups the similar
ones, so the administrator sees what people ask that the comments do not explain yet — the most asked first.

Nothing here is read by the model; it only feeds a person. Questions can contain names, so the file lives in data/
(GAPS_FILE), keeps only recent entries, stores a short hash instead of the user id, and is readable by administrators.
"""
import hashlib
import json
import os
import threading
import time

from nlu.name_match import normalize_ar

KINDS = {
    "no_answer": "لم يصل النظام لإجابة",
    "clarification": "طلب النظام توضيحاً",
    "empty": "لا توجد بيانات مطابقة",
    "error": "خطأ أثناء المعالجة",
}
_STOP = {"كم", "ما", "هو", "هي", "ماذا", "هل", "في", "من", "على", "الي", "عن", "مع", "هذا", "هذه", "ذلك", "لي", "لنا", "عدد",
         "اعرض", "اعرضلي", "اريد", "عايز", "عاوز", "طيب", "لو", "سمحت", "بتاع", "بتاعت", "ايه", "اي", "ان", "او", "ثم", "كل"}
_lock = threading.Lock()
MAX_KEEP = 2000


def _file() -> str:
    return os.getenv("GAPS_FILE", "").strip() or os.path.join("data", "gaps.jsonl")


def record(question: str, kind: str, user_id: str = "") -> None:
    """Keep one unanswered question. Never raises: logging must not break an answer."""
    if kind not in KINDS or not (question or "").strip():
        return
    _append(question, kind, user_id)


def dismiss(question: str) -> bool:
    """The administrator decided this is not a missing comment (a test probe, a question that is rightly refused, an
    out-of-scope one): that question and the ones that mean the same stop appearing in the list."""
    if not tokens(question):
        return False
    _append(question, "dismissed", "admin")
    return True


def _append(question: str, kind: str, user_id: str) -> None:
    entry = {"ts": int(time.time()), "kind": kind, "q": question.strip()[:300],
             "user": hashlib.sha1((user_id or "").encode("utf-8")).hexdigest()[:8]}
    try:
        path = _file()
        with _lock:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if os.path.getsize(path) > 1_000_000:                       # keep the file small: only the latest entries
                with open(path, encoding="utf-8") as fh:
                    lines = fh.readlines()[-MAX_KEEP:]
                with open(path, "w", encoding="utf-8") as fh:
                    fh.writelines(lines)
    except OSError:
        pass


def _entries() -> list[dict]:
    try:
        with open(_file(), encoding="utf-8") as fh:
            rows = []
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
            return rows
    except OSError:
        return []


def tokens(question: str) -> frozenset:
    """The words that carry the question's meaning: normalised, no digits, no filler words, no very short words."""
    out = set()
    for w in normalize_ar(question).replace("؟", " ").replace("?", " ").split():
        w = w[2:] if w.startswith("ال") and len(w) > 4 else w
        if len(w) >= 3 and not w.isdigit() and w not in _STOP:
            out.add(w)
    return frozenset(out)


def summary(limit: int = 30, since_days: int = 0) -> list[dict]:
    """Groups of similar unanswered questions, most asked first: {count, kinds, sample, users, last_seen, words}."""
    cutoff = time.time() - since_days * 86400 if since_days else 0
    groups: list[dict] = []
    entries = _entries()
    dismissed = [tokens(e.get("q", "")) for e in entries if e.get("kind") == "dismissed"]
    for e in entries:
        if e.get("ts", 0) < cutoff or e.get("kind") not in KINDS:
            continue
        words = tokens(e.get("q", ""))
        if not words:
            continue
        if any(d and len(d & words) / len(d | words) >= 0.5 for d in dismissed):
            continue
        for g in groups:
            union = g["words"] | words
            if union and len(g["words"] & words) / len(union) >= 0.5:
                break
        else:
            g = {"count": 0, "kinds": {}, "sample": e["q"], "users": set(), "last_seen": 0, "words": set(words)}
            groups.append(g)
        g["count"] += 1
        g["kinds"][e["kind"]] = g["kinds"].get(e["kind"], 0) + 1
        g["users"].add(e.get("user", ""))
        g["last_seen"] = max(g["last_seen"], e.get("ts", 0))
        g["words"] |= words
    groups.sort(key=lambda g: (-g["count"], -g["last_seen"]))
    return [{"count": g["count"], "kinds": g["kinds"], "sample": g["sample"], "users": len(g["users"]),
             "last_seen": g["last_seen"], "words": sorted(g["words"])[:8]} for g in groups[:limit]]
