"""Settings read from the environment that more than one part of the application needs."""
import datetime
import os


def default_company() -> str:
    """Company a question is asked for when the caller does not say (the web page asks /chat/config)."""
    return os.getenv("DEFAULT_COMPANY_CODE", "").strip() or "1"


def default_fiscal_year() -> str:
    return os.getenv("DEFAULT_FISCAL_YEAR", "").strip() or str(datetime.date.today().year)
