"""ECO SAFE CRM profile — sales activities, contacts, training courses."""
from pathlib import Path

NAME = "ecosafe"
TITLE = "ECO SAFE CRM Chatbot"
BRAND = "ECO SAFE CRM"
COMMENTS_FILE = Path(__file__).parent / "comments.sql"
# The CRM tables have no company / fiscal-year / branch columns, so nothing is injected.
TENANT_FILTERING = False
from .seeds import SEED_KNOWLEDGE  # noqa: E402,F401
