"""Business-domain profiles.

Everything that describes *which* system the assistant talks about lives in a
profile package, never in the generic engine:

    profiles/<name>/
        __init__.py   NAME, TITLE, BRAND, COMMENTS_FILE, DASHBOARDS_ENABLED
        comments.sql  COMMENT ON TABLE/COLUMN  (the single source of meaning)
        intents.py    DOMAIN_SIGNALS, SUB_INTENT_PATTERNS, ENTITY_PATTERNS, ...
        templates.py  register(register, QueryTemplate): ready-made SQL
        prompts.py    LLM prompts and user-facing texts (greeting, help, ...)
        suggestions.py  follow-up chips and column labels

The active profile comes from the APP_PROFILE environment variable
(default: ``justclick``). Engine modules call ``profiles.part("intents")``
at use time, so switching profiles needs no code change.
"""
import importlib
import os
from types import ModuleType

DEFAULT_PROFILE = "justclick"
PARTS = ("intents", "templates", "prompts", "suggestions")


def active_name() -> str:
    return os.getenv("APP_PROFILE", DEFAULT_PROFILE).strip().lower() or DEFAULT_PROFILE


def available() -> list[str]:
    from pathlib import Path
    root = Path(__file__).parent
    return sorted(p.name for p in root.iterdir() if (p / "__init__.py").exists())


def active() -> ModuleType:
    """The active profile package."""
    name = active_name()
    try:
        return importlib.import_module(f"profiles.{name}")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"Unknown APP_PROFILE={name!r}. Available: {', '.join(available())}"
        ) from exc


def part(name: str) -> ModuleType:
    """One module of the active profile, e.g. part("intents")."""
    if name not in PARTS:
        raise ValueError(f"Unknown profile part {name!r}; expected one of {PARTS}")
    return importlib.import_module(f"profiles.{active_name()}.{name}")


def comments_file():
    """Path of the active profile's COMMENT ON file."""
    return active().COMMENTS_FILE
