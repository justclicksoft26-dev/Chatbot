"""Sprint 5 acceptance rules 4 and 5: who may run write actions."""
from security import rbac


def _perms(role):
    return rbac.ROLES[role]


def test_off_by_default_for_everyone(monkeypatch):
    monkeypatch.delenv("ACTIONS_ENABLED", raising=False)
    assert not rbac.actions_allowed("u", _perms("admin"))
    monkeypatch.setenv("ACTIONS_ENABLED", "0")
    assert not rbac.actions_allowed("u", _perms("admin"))


def test_viewer_is_refused_even_when_enabled(monkeypatch):
    monkeypatch.setenv("ACTIONS_ENABLED", "1")
    assert not rbac.actions_allowed("u", _perms("viewer"))
    assert rbac.actions_allowed("u", _perms("admin"))


def test_pilot_limits_to_listed_users(monkeypatch):
    monkeypatch.setenv("ACTIONS_ENABLED", "pilot")
    monkeypatch.setenv("ACTIONS_PILOT_USERS", "ahmed")
    assert rbac.actions_allowed("ahmed", _perms("admin"))
    assert not rbac.actions_allowed("omar", _perms("admin"))
