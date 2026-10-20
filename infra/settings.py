"""Settings read from the environment that more than one part of the application needs."""
import datetime
import os


def default_company() -> str:
    """Company a question is asked for when the caller does not say (the web page asks /chat/config)."""
    return os.getenv("DEFAULT_COMPANY_CODE", "").strip() or "1"


def default_fiscal_year() -> str:
    return os.getenv("DEFAULT_FISCAL_YEAR", "").strip() or str(datetime.date.today().year)


def tenant_scope_enabled() -> bool:
    """TENANT_SCOPE=on filters every query to one COMPANY_CODE / FISCAL_YEAR (several companies in one
    database). Off by default: a single-company database needs no filter, and rows that carry no
    company or year (legacy data) would otherwise vanish from the answers."""
    return os.getenv("TENANT_SCOPE", "off").strip().lower() in ("1", "on", "true", "yes")


def answer_mode() -> str:
    """comments (default): every data question is answered from the schema comments via the LLM;
    templates: the profile's ready-made SQL templates may answer first (legacy hybrid)."""
    return "templates" if os.getenv("ANSWER_MODE", "comments").strip().lower() == "templates" else "comments"
