"""JustClick ERP profile — accounting, invoicing, inventory, customers/suppliers, HR."""
from pathlib import Path

NAME = "justclick"
TITLE = "JustClick ERP Chatbot"
BRAND = "JustClick ERP"
COMMENTS_FILE = Path(__file__).parent / "comments.sql"
# The ERP tables carry COMPANY_CODE / FISCAL_YEAR / BRANCH_ID: every query is scoped to the
# caller's company, year and branches before it runs (security/query_policy, security/rbac).
TENANT_FILTERING = True
