"""Request field types shared by several routers."""
from typing import Annotated

from pydantic import StringConstraints

# company_code / fiscal_year / branch_id end up inside SQL filters, so the API
# only accepts short tokens made of letters, digits, '_' and '-'.
ScopeValue = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_\-]{1,32}$")]
