"""Colleagues behind one office address must not make each other wait; invented credentials must not escape the limit."""
import time

import pytest
from fastapi.testclient import TestClient

import app as app_module
from pipeline import PipelineResult
from security import rbac, users

pytest.importorskip("jwt")
SECRET = "apex-shared-secret-0123456789abcdef0123456789"


@pytest.fixture(autouse=True)
def keys_mode(monkeypatch, tmp_path):
    rbac._user_roles.clear()
    monkeypatch.setattr(rbac, "_AUTH_MODE", "keys")
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setenv("API_KEY", "service-key-123456")
    monkeypatch.setattr(app_module, "_API_KEY", "service-key-123456")
    monkeypatch.setattr(app_module, "_RATE_LIMIT_CHAT", 2)
    monkeypatch.setattr(app_module, "RATE_DB_PATH", str(tmp_path / "rate.db"), raising=False)

    async def fake(**kwargs):
        return PipelineResult(answer="ok", method="template")

    for module in ("routers.chat", "routers.stream", "routers.widget"):
        monkeypatch.setattr(f"{module}.process_question", fake)
    yield
    rbac._user_roles.clear()


def post(client, headers):
    return client.post("/api/chat", json={"question": "hi"}, headers=headers).status_code


def test_each_user_has_their_own_allowance_from_the_same_address(tmp_path):
    ahmed, omar = users.add_user("ahmed", "sales"), users.add_user("omar", "warehouse")
    client = TestClient(app_module.app)
    assert [post(client, {"X-API-Key": ahmed}) for _ in range(3)] == [200, 200, 429]
    assert [post(client, {"X-API-Key": omar}) for _ in range(2)] == [200, 200]      # not slowed by ahmed


def test_a_signed_token_counts_for_its_user():
    import jwt
    now = int(time.time())
    token = jwt.encode({"sub": "KHALED", "role": "sales", "iat": now, "exp": now + 300}, SECRET, algorithm="HS256")
    client = TestClient(app_module.app)
    assert [post(client, {"Authorization": f"Bearer {token}"}) for _ in range(3)] == [200, 200, 429]


def test_invented_credentials_are_refused_and_never_open_a_bucket_of_their_own():
    client = TestClient(app_module.app)
    assert {post(client, {"X-API-Key": f"invented-{i}"}) for i in range(5)} == {401}
    key = users.add_user("ahmed", "sales")
    assert post(client, {"X-API-Key": key}) == 200                    # a real user is not affected by the noise
