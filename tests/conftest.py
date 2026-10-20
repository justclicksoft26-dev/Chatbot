"""Shared pytest setup.

Every test runs offline: no Oracle, no LLM keys, and a throw-away SQLite file
instead of data/learning.db. Env vars are set before any project module is
imported because several modules read them at import time.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("LEARNING_FORCE_SQLITE", "1")
os.environ.pop("API_KEY", None)
os.environ.pop("JWT_SECRET", None)
os.environ["AUTH_MODE"] = "api_key"


@pytest.fixture(autouse=True)
def company_scope_on(monkeypatch):
    """The suite exercises company/year scoping; production defaults to TENANT_SCOPE=off."""
    monkeypatch.setenv("TENANT_SCOPE", "on")


@pytest.fixture(autouse=True)
def isolated_sqlite(tmp_path, monkeypatch):
    """Point every SQLite user (actions, sessions, rate limit, audit) at a temp file."""
    monkeypatch.setenv("LEARNING_DB_PATH", str(tmp_path / "learning.db"))
    # Tables are created at import time; re-create them in the temp database.
    from erp_actions import store
    store._actions.clear()
    store._audit_log.clear()
    store._ensure_tables()
    yield


@pytest.fixture(scope="session")
def comments_path():
    return ROOT / "justclick_comments.sql"


def _load_profile(name: str):
    """Switch the whole engine to profile `name` and reload what is cached from it."""
    import asyncio
    import importlib
    os.environ["APP_PROFILE"] = name
    os.environ.pop("SCHEMA_FILE", None)
    from nlu import schema_loader
    from nlu import query_templates
    from nlu import semantic_registry
    schema_loader._flag_concept_map = None
    asyncio.run(schema_loader.init_schema_context())
    importlib.reload(semantic_registry)
    query_templates.load_profile_templates()
    return schema_loader


@pytest.fixture
def justclick_profile():
    """Run a test against the JustClick ERP profile (the default)."""
    yield _load_profile("justclick")


@pytest.fixture
def ecosafe_profile():
    """Run a test against the ECO SAFE CRM profile; the ERP profile is restored afterwards."""
    yield _load_profile("ecosafe")
    _load_profile("justclick")


@pytest.fixture(scope="session")
def schema():
    """The comment-driven schema of the default (ERP) profile, loaded once."""
    return _load_profile("justclick")
