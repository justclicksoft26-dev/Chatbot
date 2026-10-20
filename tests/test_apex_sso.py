"""APEX knows who is logged in: it signs a short-lived token, the chat trusts that identity and the role in it."""
import base64
import hashlib
import hmac
import json
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
from pipeline import PipelineResult
from security import rbac, users

pytest.importorskip("jwt")
SECRET = "apex-shared-secret-0123456789abcdef0123456789"
PAGE = (Path(__file__).resolve().parent.parent / "static" / "index.html").read_text(encoding="utf-8")


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def apex_token(user="AHMED", role="sales", branches=None, ttl=600, secret=SECRET, **extra):
    """The token exactly as the PL/SQL package builds it: base64url(header).base64url(payload).base64url(HMAC-SHA256)."""
    now = int(time.time())
    payload = {"sub": user, "role": role, "iat": now, "exp": now + ttl, **extra}
    payload["exp"] = max(payload["exp"], payload["iat"] + 0) if "iat" in extra and ttl > 0 else payload["exp"]
    if branches is not None:
        payload["branches"] = branches
    signing = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()) + "." + b64url(json.dumps(payload, ensure_ascii=False).encode())
    return signing + "." + b64url(hmac.new(secret.encode(), signing.encode(), hashlib.sha256).digest())


@pytest.fixture(autouse=True)
def mode(monkeypatch, tmp_path):
    rbac._user_roles.clear()
    monkeypatch.setattr(rbac, "_AUTH_MODE", "keys")
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setenv("API_KEY", "service-key-123456")
    monkeypatch.setattr(app_module, "_API_KEY", "service-key-123456")
    for var in ("JWT_AUDIENCE", "SSO_MAX_TOKEN_SECONDS", "FRAME_ANCESTORS", "ADMIN_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield
    rbac._user_roles.clear()


@pytest.fixture
def client(monkeypatch):
    seen = []

    async def fake(**kwargs):
        seen.append(kwargs)
        return PipelineResult(answer="ok", method="template")

    for module in ("routers.chat", "routers.stream", "routers.widget"):
        monkeypatch.setattr(f"{module}.process_question", fake)
    c = TestClient(app_module.app)
    c.seen = seen
    return c


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ── a token signed by APEX identifies the user and gives the role ─────
def test_a_signed_token_identifies_the_user_whatever_name_the_page_sends(client):
    r = client.post("/chat/", json={"question": "hi", "user_id": "boss"}, headers=bearer(apex_token("AHMED", "sales")))
    assert r.status_code == 200
    assert client.seen[-1]["user_id"] == "AHMED"
    assert rbac.get_user_permissions("AHMED").role == "sales"


def test_the_widget_endpoint_trusts_the_token_not_the_name_in_the_body(client):
    r = client.post("/api/chat", json={"question": "hi", "user": "boss"}, headers=bearer(apex_token("OMAR", "warehouse")))
    assert r.status_code == 200 and client.seen[-1]["user_id"] == "OMAR"


def test_branches_and_arabic_names_survive(client):
    token = apex_token("أحمد.علي", "sales", branches=["5", "6"])
    client.post("/chat/", json={"question": "hi"}, headers=bearer(token))
    assert rbac.get_user_permissions("أحمد.علي").allowed_branches == ["5", "6"]


def test_me_reports_the_role_and_domains_from_the_token(client):
    body = client.get("/chat/me", headers=bearer(apex_token("OMAR", "warehouse"))).json()
    assert body["user_id"] == "OMAR" and body["domains"] == ["inventory"] and body["restricted"] is True


def test_the_role_of_the_token_decides_the_domains_pipeline_side(client):
    from security import permissions
    client.post("/chat/", json={"question": "hi"}, headers=bearer(apex_token("OMAR", "warehouse")))
    assert permissions.user_domains("OMAR") == {"inventory"}


# ── what is refused ────────────────────────────────────────────────────
@pytest.mark.parametrize("make", [
    lambda: apex_token(ttl=-120),                                    # expired
    lambda: apex_token(secret="some-other-secret-0123456789abcdef0123"),   # signed with another secret
    lambda: apex_token(role="superuser"),                            # a role that does not exist
    lambda: apex_token(ttl=86400),                                   # lives a day: too long to be safe
    lambda: "not.a.token",
    lambda: b64url(b'{"alg":"none"}') + "." + b64url(b'{"sub":"x","exp":9999999999}') + ".",   # alg none
])
def test_bad_tokens_are_refused(client, make):
    assert client.post("/chat/", json={"question": "hi"}, headers=bearer(make())).status_code == 401
    assert client.seen == []


def test_a_token_without_an_expiry_is_refused(client):
    import jwt
    token = jwt.encode({"sub": "AHMED", "role": "sales"}, SECRET, algorithm="HS256")
    assert client.post("/chat/", json={"question": "hi"}, headers=bearer(token)).status_code == 401


def test_the_audience_is_checked_when_one_is_configured(client, monkeypatch):
    monkeypatch.setenv("JWT_AUDIENCE", "justclick-chat")
    assert client.post("/chat/", json={"question": "hi"}, headers=bearer(apex_token())).status_code == 401
    assert client.post("/chat/", json={"question": "hi"}, headers=bearer(apex_token(aud="justclick-chat"))).status_code == 200


def test_the_lifetime_limit_can_be_raised(client, monkeypatch):
    monkeypatch.setenv("SSO_MAX_TOKEN_SECONDS", "90000")
    assert client.post("/chat/", json={"question": "hi"}, headers=bearer(apex_token(ttl=86400))).status_code == 200


def test_without_the_shared_secret_bearer_tokens_are_ignored(client, monkeypatch):
    monkeypatch.delenv("JWT_SECRET")
    assert client.post("/chat/", json={"question": "hi"}, headers=bearer(apex_token())).status_code == 401


def test_no_credentials_at_all_is_refused(client):
    assert client.post("/chat/", json={"question": "hi"}).status_code == 401


def test_a_personal_key_still_works_next_to_the_token(client):
    key = users.add_user("ahmed", "sales")
    assert client.post("/chat/", json={"question": "hi"}, headers={"X-API-Key": key}).status_code == 200
    assert client.seen[-1]["user_id"] == "ahmed"


def test_an_administrator_token_opens_the_admin_paths_and_others_do_not(client):
    assert client.get("/chat/usage", headers=bearer(apex_token("BOSS", "admin"))).status_code == 200
    assert client.get("/chat/usage", headers=bearer(apex_token("AHMED", "sales"))).status_code == 403


def test_the_signature_is_the_standard_one_so_the_plsql_mirror_verifies():
    claims = rbac.verify_token(apex_token("AHMED", "sales", branches=["1"]))
    assert claims == {"user_id": "AHMED", "role": "sales", "company_code": "1", "branches": ["1"]}


# ── who may put the chat in a frame ────────────────────────────────────
def test_by_default_nobody_may_frame_the_chat():
    r = TestClient(app_module.app).get("/")
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_the_apex_origin_may_frame_it_when_configured(monkeypatch):
    monkeypatch.setenv("FRAME_ANCESTORS", "https://apex.example.com, https://apps.example.com:8443 *  http://evil")
    r = TestClient(app_module.app).get("/")
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'self' https://apex.example.com https://apps.example.com:8443 http://evil;" in csp
    assert "x-frame-options" not in r.headers
    assert "*" not in csp.split("frame-ancestors")[1]


# ── the page ───────────────────────────────────────────────────────────
def test_the_page_reads_the_token_from_the_fragment_and_removes_it_from_the_address():
    assert "window.location.hash" in PAGE and "'token'" in PAGE
    assert re.search(r"history\.replaceState\(null, '', window\.location\.pathname \+ window\.location\.search\)", PAGE)


def test_the_page_sends_the_token_and_only_accepts_a_new_one_from_its_parent_frame():
    assert "h['Authorization'] = 'Bearer ' + SSO_TOKEN" in PAGE
    assert "e.source !== window.parent" in PAGE and "chatbot-need-token" in PAGE and "chatbot-token" in PAGE


def test_the_page_renews_the_token_before_it_expires():
    assert "scheduleTokenRefresh" in PAGE and "- 60" in PAGE


def test_a_token_issued_a_few_seconds_ahead_of_the_chat_clock_is_accepted_but_not_one_far_ahead():
    now = int(time.time())
    assert rbac.verify_token(apex_token(iat=now + 20)) is not None
    import jwt
    far = jwt.encode({"sub": "A", "role": "sales", "iat": now + 600, "exp": now + 900}, SECRET, algorithm="HS256")
    assert rbac.verify_token(far) is None
