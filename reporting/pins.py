"""Pinned SQL: the query behind a dashboard widget, written once from the schema comments and kept.

A widget is a business question ("sales today"). With DASHBOARD_SQL=comments its query is not hand-written in code: the
model writes it from the comments, the result is pinned here, and every later load runs the pinned text with no model
call (fast, free, and the same query every time). A pin is plain SQL in data/pinned_sql.json, so an administrator can
read it, approve it, or regenerate it (python -m tools.pins).

  auto      written by the model, not looked at yet; replaced when the comments change (the meaning may have moved)
  approved  an administrator accepted it; kept until it is regenerated on purpose
  failed    ran into an error; it is written again on the next load

The pin never carries data and never replaces the security checks: it is run through security.scope.prepare_sql by whoever
opens the dashboard, so company, branch, role and domain rules apply exactly as for any other query.
"""
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, asdict
from typing import Optional

_lock = threading.Lock()
_hash_cache: dict = {"key": None, "value": ""}


def pins_file() -> str:
    return os.getenv("PINNED_SQL_FILE", "").strip() or os.path.join("data", "pinned_sql.json")


def comments_hash() -> str:
    """Fingerprint of the active comments: when it changes, 'auto' pins are written again."""
    import profiles
    path = str(profiles.comments_file())
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        return ""
    if _hash_cache["key"] != (path, stamp):
        with open(path, "rb") as fh:
            _hash_cache.update(key=(path, stamp), value=hashlib.sha1(fh.read()).hexdigest()[:12])
    return _hash_cache["value"]


@dataclass
class Pin:
    key: str
    sql: str
    question: str
    status: str = "auto"                 # auto | approved | failed
    comments_hash: str = ""
    created: int = 0
    note: str = ""


def _load() -> dict:
    try:
        with open(pins_file(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    path = pins_file()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def get(key: str) -> Optional[Pin]:
    """The pin to run for this widget, or None when it must be (re)written."""
    with _lock:
        raw = _load().get(key)
    if not raw:
        return None
    pin = Pin(**raw)
    if pin.status == "failed":
        return None
    if pin.status == "auto" and pin.comments_hash != comments_hash():
        return None                                             # the comments changed since it was written
    return pin


def put(key: str, sql: str, question: str, status: str = "auto", note: str = "") -> Pin:
    pin = Pin(key=key, sql=sql.strip(), question=question, status=status, comments_hash=comments_hash(),
              created=int(time.time()), note=note)
    with _lock:
        data = _load()
        data[key] = asdict(pin)
        _save(data)
    return pin


def mark_failed(key: str, error: str) -> None:
    with _lock:
        data = _load()
        if key in data and data[key].get("status") != "approved":     # an approved pin is a human decision: keep it
            data[key].update(status="failed", note=error[:300])
            _save(data)


def approve(key: str) -> bool:
    with _lock:
        data = _load()
        if key not in data or data[key].get("status") == "failed":
            return False
        data[key]["status"] = "approved"
        _save(data)
        return True


def all_pins() -> list[Pin]:
    with _lock:
        return [Pin(**v) for _, v in sorted(_load().items())]


def forget(key: str) -> None:
    with _lock:
        data = _load()
        if data.pop(key, None) is not None:
            _save(data)
