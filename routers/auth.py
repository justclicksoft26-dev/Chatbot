"""Access-control helpers shared by the routers.

* caller_id            who is making the request (a verified JWT beats anything in the body)
* require_admin        FastAPI dependency guarding operational endpoints
* ensure_company_access  403 unless the caller may work with that company
"""
import hmac
import os

from fastapi import HTTPException, Request

from security import rbac
from security.company_manager import validate_company_access


def caller_id(request: Request, claimed_user_id: str = "") -> str:
    """Identity the request runs as. 401 in JWT mode without a valid token."""
    try:
        return rbac.resolve_user_id(dict(request.headers), claimed_user_id)
    except rbac.AuthenticationRequired:
        if rbac.auth_mode() == "keys":
            raise HTTPException(status_code=401, detail="المفتاح غير صالح — استخدم مفتاحك الشخصي في X-API-Key")
        raise HTTPException(
            status_code=401,
            detail="المصادقة مطلوبة — يرجى إرسال Authorization: Bearer <token> صالح",
        )


def is_admin(user_id: str) -> bool:
    """True when the user's role is ``admin``."""
    return bool(user_id) and rbac.get_user_permissions(user_id).role == "admin"


async def ensure_company_access(user_id: str, company_code: str) -> None:
    if not await validate_company_access(user_id, company_code):
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية على هذه الشركة.")


def has_admin_key(request: Request) -> bool:
    """True when the request carries the valid X-Admin-Key (used to show internals such as the SQL)."""
    admin_key = os.getenv("ADMIN_API_KEY", "").strip()
    supplied = request.headers.get("X-Admin-Key", "")
    return bool(admin_key and supplied and hmac.compare_digest(supplied.encode(), admin_key.encode()))


def require_admin(request: Request) -> None:
    """Allow the request only for an administrator.

    Accepted, in order:
      1. header ``X-Admin-Key`` equal to ADMIN_API_KEY
      2. a verified JWT whose role is ``admin`` (AUTH_MODE=jwt)
      3. ALLOW_INSECURE_ADMIN=1 — explicit opt-in for local development only

    With none of these configured the endpoint is closed (403), never open.
    """
    admin_key = os.getenv("ADMIN_API_KEY", "").strip()
    supplied = request.headers.get("X-Admin-Key", "")
    if admin_key and supplied and hmac.compare_digest(supplied.encode(), admin_key.encode()):
        return

    if rbac.auth_mode() == "jwt":
        verified = rbac.authenticate_request(dict(request.headers))
        if verified and is_admin(verified):
            return

    if rbac.auth_mode() == "keys":
        try:
            if is_admin(rbac.identity_from_key(request.headers.get("X-API-Key", ""))):
                return
        except rbac.AuthenticationRequired:
            pass

    if os.getenv("ALLOW_INSECURE_ADMIN", "").strip() == "1":
        return

    if not admin_key and rbac.auth_mode() != "jwt":
        raise HTTPException(
            status_code=403,
            detail="هذا المسار للإدارة فقط — اضبط ADMIN_API_KEY وأرسله في X-Admin-Key.",
        )
    raise HTTPException(status_code=403, detail="صلاحية الإدارة مطلوبة.")
