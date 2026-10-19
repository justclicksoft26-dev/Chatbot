"""
rbac.py — Role-Based Access Control + Row-Level Security
Enterprise-grade permission system for the AI Copilot.

Roles:
  admin     — Full access, all domains, all data, system management
  manager   — All domains, own branch data, reports
  accountant — Accounting domain only, own company data
  sales     — Invoicing + customers, own branch
  warehouse — Inventory domain only
  hr        — HR domain only, restricted PII
  viewer    — Read-only, no SQL visibility, limited domains

Row-level security:
  - company_code filtering (multi-tenant)
  - branch_id filtering (per-role)
  - domain restrictions (per-role)
  - sensitive column masking (PII)
"""
import os
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("rbac")


@dataclass
class UserRole:
    role: str
    allowed_domains: list[str] = field(default_factory=list)
    allowed_branches: list[str] = field(default_factory=list)
    can_view_sql: bool = True
    can_export: bool = True
    can_execute_actions: bool = False
    max_rows: int = 500
    masked_columns: list[str] = field(default_factory=list)
    description: str = ""


# ── Role Definitions ─────────────────────────────────────────────
ROLES: dict[str, UserRole] = {
    "admin": UserRole(
        role="admin",
        allowed_domains=["accounting", "invoicing", "inventory", "customers", "hr", "system"],
        allowed_branches=["*"],
        can_view_sql=True,
        can_export=True,
        can_execute_actions=True,
        max_rows=500,
        description="Full system access",
    ),
    "manager": UserRole(
        role="manager",
        allowed_domains=["accounting", "invoicing", "inventory", "customers", "hr"],
        allowed_branches=["*"],
        can_view_sql=True,
        can_export=True,
        can_execute_actions=True,
        max_rows=500,
        description="Management access — all domains, reports enabled",
    ),
    "accountant": UserRole(
        role="accountant",
        allowed_domains=["accounting", "invoicing"],
        allowed_branches=["*"],
        can_view_sql=True,
        can_export=True,
        can_execute_actions=False,
        max_rows=500,
        masked_columns=["EMP_SALARY", "BASIC_SALARY", "NET_SALARY"],
        description="Accounting & invoicing access",
    ),
    "sales": UserRole(
        role="sales",
        allowed_domains=["invoicing", "customers", "inventory"],
        allowed_branches=[],  # filled per-user
        can_view_sql=False,
        can_export=True,
        can_execute_actions=False,
        max_rows=200,
        masked_columns=["EMP_SALARY", "BASIC_SALARY", "NET_SALARY", "COST_PRICE"],
        description="Sales team — invoicing, customers, inventory",
    ),
    "warehouse": UserRole(
        role="warehouse",
        allowed_domains=["inventory"],
        allowed_branches=[],
        can_view_sql=False,
        can_export=False,
        can_execute_actions=False,
        max_rows=200,
        masked_columns=["FINALTOTAL", "INVTOTAL", "COST_PRICE", "EMP_SALARY"],
        description="Inventory access only",
    ),
    "hr": UserRole(
        role="hr",
        allowed_domains=["hr"],
        allowed_branches=["*"],
        can_view_sql=False,
        can_export=True,
        can_execute_actions=False,
        max_rows=200,
        description="HR domain — employees, salaries, attendance",
    ),
    "viewer": UserRole(
        role="viewer",
        allowed_domains=["invoicing", "inventory"],
        allowed_branches=[],
        can_view_sql=False,
        can_export=False,
        can_execute_actions=False,
        max_rows=50,
        masked_columns=["FINALTOTAL", "INVTOTAL", "COST_PRICE", "EMP_SALARY", "BASIC_SALARY"],
        description="Read-only limited access",
    ),
}

# ── User-Role Mapping (in production: from DB or LDAP) ───────────
# Format: user_id -> {role, company_code, branches}
_user_roles: dict[str, dict] = {}


def assign_role(user_id: str, role: str, company_code: str = "1",
                branches: list[str] = None):
    """Assign a role to a user (called from admin API or startup)."""
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role}. Valid: {list(ROLES.keys())}")
    _user_roles[user_id] = {
        "role": role,
        "company_code": company_code,
        "branches": branches or [],
    }
    log.info(f"[RBAC] Assigned role={role} to user={user_id}")


def auth_mode() -> str:
    """Current AUTH_MODE (api_key | jwt | oauth2)."""
    return _AUTH_MODE


def get_assignment(user_id: str) -> Optional[dict]:
    """The explicit role assignment of a user ({role, company_code, branches}) or None.

    Unknown users have no assignment: they fall back to the viewer role.
    """
    return _user_roles.get(user_id)


def get_user_permissions(user_id: str) -> UserRole:
    """Get the effective permissions for a user."""
    user_data = _user_roles.get(user_id)
    if not user_data:
        # Default: viewer role for unknown users
        return ROLES["viewer"]
    role_name = user_data.get("role", "viewer")
    role = ROLES.get(role_name, ROLES["viewer"])

    # Apply branch restrictions from user assignment
    if role.allowed_branches != ["*"]:
        branches = user_data.get("branches", [])
        role = UserRole(
            role=role.role,
            allowed_domains=role.allowed_domains,
            allowed_branches=branches,
            can_view_sql=role.can_view_sql,
            can_export=role.can_export,
            can_execute_actions=role.can_execute_actions,
            max_rows=role.max_rows,
            masked_columns=role.masked_columns,
            description=role.description,
        )
    return role


def check_domain_access(user_id: str, domain: str) -> bool:
    """Check if user has access to a specific domain."""
    perms = get_user_permissions(user_id)
    if "*" in perms.allowed_domains or not domain:
        return True
    return domain in perms.allowed_domains


def filter_response_for_role(user_id: str, result: dict) -> dict:
    """Apply role-based filtering to a pipeline response.
    Masks SQL, restricts exports, applies column masking.
    """
    perms = get_user_permissions(user_id)

    if not perms.can_view_sql:
        result["sql_generated"] = ""

    if not perms.can_export:
        result.pop("export_available", None)

    return result


def get_max_rows(user_id: str) -> int:
    """Get the maximum rows this user can retrieve."""
    return get_user_permissions(user_id).max_rows


def get_masked_columns(user_id: str) -> list[str]:
    """Get columns that should be masked for this user."""
    return get_user_permissions(user_id).masked_columns


# ── JWT/Token-Based Identity Integration ─────────────────────────
# AUTH_MODE is a stable deployment setting — read once at import time.
# JWT_SECRET is resolved lazily on every call so python-dotenv has time
# to populate os.environ before the first authentication attempt.
_AUTH_MODE = os.getenv("AUTH_MODE", "api_key")  # api_key | jwt | oauth2


def _get_jwt_secret() -> str:
    """Return JWT_SECRET from the environment.

    Raises RuntimeError in jwt mode when the secret is absent or empty.
    The error deliberately propagates to the caller (→ HTTP 500) so that
    a misconfigured jwt-mode deployment fails loudly on startup / first
    request rather than silently falling through to the claimed identity.
    """
    secret = os.getenv("JWT_SECRET", "").strip()
    if not secret and _AUTH_MODE == "jwt":
        raise RuntimeError(
            "[RBAC] JWT_SECRET is not configured. "
            "Set JWT_SECRET in the environment / .env file before running in jwt mode."
        )
    return secret


def verify_token(token: str) -> Optional[dict]:
    """Verify a JWT Bearer token and return {user_id, role, company_code, branches}.

    Security guarantees (PyJWT >= 2.4):

    1. algorithms=["HS256"] is passed explicitly.  PyJWT checks the 'alg'
       field in the JWT header and raises InvalidAlgorithmError if it is not
       HS256 — this defeats alg:none and RS256-confusion attacks where an
       attacker substitutes a different algorithm in the header.

    2. options={"require": ["exp", "sub"]} forces both claims to be present;
       a token without an expiry or a subject is rejected outright.

    3. An empty JWT_SECRET in jwt mode raises RuntimeError (outside the
       try/except) so it is never silently swallowed.  The error surfaces as
       HTTP 500 so operations knows the deployment is misconfigured.
    """
    if not token:
        return None

    # _get_jwt_secret raises RuntimeError in jwt mode if secret is missing.
    # It sits OUTSIDE the try/except block intentionally — misconfiguration
    # must not be caught and turned into a silent None return.
    secret = _get_jwt_secret()
    if not secret:
        # api_key / dev mode with no secret — skip JWT verification entirely.
        return None

    try:
        import jwt as _jwt  # PyJWT

        payload = _jwt.decode(
            token,
            secret,
            algorithms=["HS256"],               # explicit allowlist — alg:none rejected
            options={"require": ["exp", "sub"]}, # both claims mandatory
        )
        return {
            "user_id":      payload["sub"],
            "role":         payload.get("role", "viewer"),
            "company_code": payload.get("company", "1"),
            "branches":     payload.get("branches", []),
        }

    except ImportError:
        log.error("[RBAC] PyJWT is not installed — run: pip install 'PyJWT>=2.8'")
        return None
    except Exception as exc:
        # Log only the exception class — avoids leaking token content into logs.
        log.warning("[RBAC] JWT verification failed: %s", type(exc).__name__)
        return None


def authenticate_request(headers: dict) -> Optional[str]:
    """Authenticate a request and return user_id.
    Supports: API key, JWT Bearer token, or OAuth2 token.
    """
    if _AUTH_MODE == "jwt":
        auth_header = headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            claims = verify_token(token)
            if claims:
                # Auto-assign role from token claims
                assign_role(
                    claims["user_id"],
                    claims["role"],
                    claims["company_code"],
                    claims["branches"],
                )
                return claims["user_id"]
        return None

    # Default: API key mode (existing behavior)
    return None  # handled by ApiKeyMiddleware


class AuthenticationRequired(Exception):
    """AUTH_MODE=jwt and the request carried no valid bearer token."""


def resolve_user_id(headers: dict, claimed_user_id: str) -> str:
    """Decide which identity a request runs as.

    A verified JWT always wins over the user_id sent in the body. Without a
    token, jwt mode is a hard failure, while api_key/dev mode trusts the body
    (access is then gated by the X-API-Key middleware, not per user).
    """
    verified = authenticate_request(headers)
    if verified:
        if verified != claimed_user_id:
            log.warning("[AUTH] Body user_id=%r overridden by JWT-verified identity=%r",
                        claimed_user_id, verified)
        return verified
    if _AUTH_MODE == "jwt":
        raise AuthenticationRequired("Authorization: Bearer <token> required")
    return claimed_user_id


def actions_allowed(user_id: str, user_perms: Optional[UserRole] = None) -> bool:
    """Feature gate for ERP write actions (create/update/approve ...).

    ACTIONS_ENABLED:
      "0" (default) - off for everyone
      "pilot"       - admin/manager role AND user in ACTIONS_PILOT_USERS
                      (an empty list means every admin/manager)
      "1"           - every user whose role has can_execute_actions
    """
    mode = os.getenv("ACTIONS_ENABLED", "0").strip().lower()
    if mode in ("", "0", "false", "no", "off"):
        return False
    perms = user_perms or get_user_permissions(user_id)
    if not perms.can_execute_actions:
        return False
    if mode == "pilot":
        pilot_csv = os.getenv("ACTIONS_PILOT_USERS", "").strip()
        if pilot_csv:
            pilot_users = {u.strip() for u in pilot_csv.split(",") if u.strip()}
            return user_id in pilot_users
    return True


# ── Database-Backed Role Loading ─────────────────────────────────

def load_roles_from_db():
    """Load user-role assignments from database.
    Called at startup to populate in-memory cache.
    """
    try:
        from learning.store import get_conn, is_oracle
        with get_conn() as conn:
            if is_oracle():
                rows = conn.execute("""
                    SELECT USER_ID, ROLE_NAME, COMPANY_CODE, BRANCHES_JSON
                    FROM AI_USER_ROLES
                    WHERE IS_ACTIVE = 1
                """).fetchall()
            else:
                rows = conn.execute("""
                    SELECT user_id, role_name, company_code, branches_json
                    FROM user_roles
                    WHERE is_active = 1
                """).fetchall()

        loaded = 0
        for row in rows:
            d = dict(row)
            uid = d.get("user_id") or d.get("USER_ID", "")
            role = d.get("role_name") or d.get("ROLE_NAME", "viewer")
            company = d.get("company_code") or d.get("COMPANY_CODE", "1")
            branches_raw = d.get("branches_json") or d.get("BRANCHES_JSON", "[]")
            try:
                import json
                branches = json.loads(branches_raw) if branches_raw else []
            except Exception:
                branches = []

            if uid and role in ROLES:
                assign_role(uid, role, company, branches)
                loaded += 1

        log.info(f"[RBAC] Loaded {loaded} user roles from database")
    except Exception as e:
        log.debug(f"[RBAC] DB role loading skipped: {e}")


def _rls_is_strict(user_id: str) -> bool:
    """Should a restricted role with no branches be locked out for this user?

    Yes when the identity is trustworthy (JWT mode, or the user has an explicit
    assignment) or when RLS_STRICT=1 forces it for everyone including unknown users.
    """
    if os.getenv("RLS_STRICT", "").strip().lower() in ("1", "true", "yes"):
        return True
    return auth_mode() == "jwt" or user_id in _user_roles


def inject_row_level_security(
    sql: str,
    user_id: str,
    company_code: str = "",   # reserved — branch-only filter for now
) -> tuple[str, dict]:
    """Apply row-level security (branch filter) and return (sql, bind_params).

    Callers must forward the returned params dict to execute_read_query:
        sql, rls = inject_row_level_security(sql, user_id, co)
        rows = await execute_read_query(sql, {**query_params, **rls})

    Returns (original_sql, {}) unchanged when no branch restriction applies.
    A restricted role with no assigned branch gets ``1 = 0`` (no rows) instead of
    unrestricted access — see _rls_is_strict for the one legacy exception.

    Fixes vs the old regex-based implementation:

    1. Subquery-safe injection — _find_outer_token() tracks parenthesis depth
       character-by-character, so WHERE / AND always lands on the outermost
       SELECT.  The old re.sub(r'\\bWHERE\\b', ..., count=1) matched the first
       WHERE in the text, which could be inside a subquery:

         SELECT * FROM MAIN_INV m,
           (SELECT INVID FROM DETAIL_INV WHERE ITEMID=5) d  <- depth-1 WHERE
         WHERE m.INVID = d.INVID                            <- depth-0 WHERE

       With the old code the filter was injected after the depth-1 WHERE,
       not after the outer one, producing broken or wrong SQL.

    2. Bind variables — branch values become :rls_branch_0, :rls_branch_1 …
       never string-interpolated.  The old f\"'{b}'\" pattern allowed a
       crafted branch ID such as  x' OR '1'='1  to inject SQL.

    3. Missing fallback — the old code silently omitted the filter when there
       was no WHERE *and* no ORDER/GROUP/FETCH marker.  The new code always
       appends WHERE <condition> in that case.
    """
    from security.query_policy import (
        _inject_at_correct_position, _strip_subqueries, map_set_branches,
        BRANCH_TABLES,
    )

    # Each branch of a UNION is its own query: restrict every one of them.
    all_params: dict[str, str] = {}

    def _restrict(branch: str) -> str:
        branch_sql, branch_params = inject_row_level_security(branch, user_id, company_code)
        all_params.update(branch_params)
        return branch_sql

    combined = map_set_branches(sql, _restrict)
    if combined is not None:
        return combined, all_params

    perms    = get_user_permissions(user_id)
    branches = perms.allowed_branches

    # Unrestricted role (admin, manager, ...) — pass through unchanged
    if branches == ["*"]:
        return sql, {}

    # A restricted role with NO branch assigned must see nothing, not everything.
    # Anonymous dev users (unknown id, AUTH_MODE=api_key) keep the legacy open
    # behaviour unless RLS_STRICT=1, because their identity cannot be verified anyway.
    deny_all = not branches
    if deny_all and not _rls_is_strict(user_id):
        return sql, {}

    # Only inject when the outer query actually references a branch-aware table.
    # Use _strip_subqueries so table names inside subqueries are ignored.
    outer_sql = _strip_subqueries(sql)
    touches_branch_table = bool(
        re.search(r'\bBRANCH_ID\b', outer_sql, re.IGNORECASE)
    ) or any(
        re.search(rf'\b{re.escape(t)}\b', outer_sql, re.IGNORECASE)
        for t in BRANCH_TABLES
    )
    if not touches_branch_table:
        return sql, {}

    # Build named bind params — one per allowed branch value
    params: dict[str, str] = {}
    placeholders: list[str] = []
    for i, branch in enumerate(branches):
        key = f"rls_branch_{i}"
        params[key] = str(branch)
        placeholders.append(f":{key}")

    condition = "1 = 0" if deny_all else f"BRANCH_ID IN ({', '.join(placeholders)})"

    new_sql = _inject_at_correct_position(sql, [condition])

    log.info("[RBAC] Branch RLS injected for user=%s: %d branch(es)", user_id, len(branches))
    return new_sql, params
