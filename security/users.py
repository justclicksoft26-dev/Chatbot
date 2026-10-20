"""One key per person: who is asking, and what role they hold.

    AUTH_MODE=keys

Every user gets their own key (shown once when it is created, stored only as a SHA-256 hash). The key
identifies the user on every request, so a user cannot become someone else by typing a different name, and
the role of that user (security/rbac.py) decides which business domains they may read.

    python -m security.users add --user ahmed --role sales --branches 5,6 --name "Ahmed Ali"
    python -m security.users list
    python -m security.users set-role --user ahmed --role accountant
    python -m security.users rotate --user ahmed          # prints the new key, the old one stops working
    python -m security.users disable --user ahmed
    python -m security.users enable  --user ahmed
    python -m security.users remove  --user ahmed

Users live in USERS_FILE (default data/users.json, a persistent volume in Docker). Changes made by this command
are seen by the running server without a restart.
"""
import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
import threading
from datetime import datetime, timezone
from typing import Optional

_lock = threading.Lock()
_cache: dict = {"mtime": None, "path": None, "users": []}


def users_file() -> str:
    return os.getenv("USERS_FILE", "").strip() or os.path.join("data", "users.json")


def hash_key(key: str) -> str:
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()


def new_key() -> str:
    return "jc_" + secrets.token_urlsafe(32)


def _read() -> list[dict]:
    path = users_file()
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return []
    with _lock:
        if _cache["path"] == path and _cache["mtime"] == mtime:
            return _cache["users"]
        try:
            with open(path, encoding="utf-8") as fh:
                users = json.load(fh).get("users", [])
        except (OSError, ValueError):
            return _cache["users"] if _cache["path"] == path else []     # a half-written file: keep what we had
        _cache.update(path=path, mtime=mtime, users=users)
        return users


def _write(users: list[dict]) -> None:
    path = users_file()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"users": users}, fh, ensure_ascii=False, indent=2)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)                                                 # atomic: a reader never sees half a file
    with _lock:
        _cache["mtime"] = None


def _find(users: list[dict], user_id: str) -> Optional[dict]:
    return next((u for u in users if u["user_id"] == user_id), None)


def _valid_role(role: str) -> None:
    from security import rbac
    if role not in rbac.ROLES:
        raise ValueError(f"unknown role {role!r}; valid: {', '.join(sorted(rbac.ROLES))}")


def add_user(user_id: str, role: str, branches: Optional[list[str]] = None, name: str = "") -> str:
    """Create a user and return their key (the only time it is visible)."""
    user_id = (user_id or "").strip()
    if not user_id or not user_id.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise ValueError("user id: letters, digits, - _ . only")
    _valid_role(role)
    users = list(_read())
    if _find(users, user_id):
        raise ValueError(f"user {user_id!r} already exists (use rotate / set-role)")
    key = new_key()
    users.append({"user_id": user_id, "name": name, "role": role, "branches": [str(b) for b in (branches or [])],
                  "key_hash": hash_key(key), "active": True,
                  "created": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    _write(users)
    return key


def _update(user_id: str, **changes) -> dict:
    users = [dict(u) for u in _read()]
    user = _find(users, user_id)
    if not user:
        raise ValueError(f"no such user {user_id!r}")
    user.update(changes)
    _write(users)
    return user


def set_role(user_id: str, role: str, branches: Optional[list[str]] = None) -> dict:
    _valid_role(role)
    changes = {"role": role}
    if branches is not None:
        changes["branches"] = [str(b) for b in branches]
    return _update(user_id, **changes)


def set_active(user_id: str, active: bool) -> dict:
    return _update(user_id, active=active)


def rotate(user_id: str) -> str:
    key = new_key()
    _update(user_id, key_hash=hash_key(key))
    return key


def remove(user_id: str) -> None:
    users = [u for u in _read() if u["user_id"] != user_id]
    if len(users) == len(_read()):
        raise ValueError(f"no such user {user_id!r}")
    _write(users)


def list_users() -> list[dict]:
    return [{k: v for k, v in u.items() if k != "key_hash"} for u in _read()]


def authenticate(key: str) -> Optional[dict]:
    """The active user holding this key, or None. Every record is compared, so timing does not reveal a match."""
    if not key:
        return None
    digest = hash_key(key)
    found = None
    for user in _read():
        if hmac.compare_digest(user.get("key_hash", ""), digest) and user.get("active", True):
            found = user
    return dict(found) if found else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("add", "set-role", "rotate", "disable", "enable", "remove"):
        p = sub.add_parser(name)
        p.add_argument("--user", required=True)
        if name in ("add", "set-role"):
            p.add_argument("--role", required=True)
            p.add_argument("--branches", default=None, help="comma separated branch ids (roles restricted by branch)")
        if name == "add":
            p.add_argument("--name", default="")
    sub.add_parser("list")
    args = parser.parse_args(argv)
    try:
        branches = None if getattr(args, "branches", None) is None else [b.strip() for b in args.branches.split(",") if b.strip()]
        if args.cmd == "add":
            key = add_user(args.user, args.role, branches, args.name)
            print(f"user {args.user} created, role {args.role}.\nKEY (shown once, give it to them): {key}")
        elif args.cmd == "set-role":
            set_role(args.user, args.role, branches); print(f"{args.user} is now {args.role}")
        elif args.cmd == "rotate":
            print(f"new KEY for {args.user} (the old one stopped working): {rotate(args.user)}")
        elif args.cmd == "disable":
            set_active(args.user, False); print(f"{args.user} disabled")
        elif args.cmd == "enable":
            set_active(args.user, True); print(f"{args.user} enabled")
        elif args.cmd == "remove":
            remove(args.user); print(f"{args.user} removed")
        elif args.cmd == "list":
            for u in list_users():
                print(f"{u['user_id']:20} {u['role']:12} {'active' if u.get('active', True) else 'DISABLED':8} "
                      f"branches={','.join(u.get('branches', [])) or '-':10} {u.get('name', '')}")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
