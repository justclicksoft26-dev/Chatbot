"""
scripts/gen_oracle_grants.py
============================
Generate Oracle SQL to create the two least-privilege DB users needed by
the JustClick AI Chatbot, then write the result to:

    scripts/oracle_users_setup.sql   (ready to run via SQL*Plus / SQLcl / DBeaver)

Usage
-----
    py scripts/gen_oracle_grants.py [options]

Options
-------
    --schema    OWNER      Oracle schema that owns the ERP tables (default: justclick)
    --read-user NAME       Read-only user to create            (default: justclick_read)
    --dml-user  NAME       DML-only user to create             (default: justclick_dml)
    --out       PATH       Output SQL file                     (default: scripts/oracle_users_setup.sql)

What is generated
-----------------
1.  AI_ACTION_REQUESTS DDL  — workflow tracking table (not part of the ERP schema)
2.  justclick_read           — CREATE USER + SELECT on all 38 comment-defined tables
                               + SELECT on AI_ACTION_REQUESTS (workflow queries)
3.  justclick_dml            — CREATE USER + minimal INSERT/UPDATE on action tables
                               + SELECT on CUST / ITEMS / PAYED (sequence fallback)
                               + SELECT on CUST_SEQ / ITEMS_SEQ / PAYED_SEQ (NEXTVAL)
                               + INSERT, UPDATE on AI_ACTION_REQUESTS

After generating
----------------
1.  Edit the generated file and replace every CHANGE_ME_* placeholder with
    the real passwords you want to use.
2.  Run the file as a DBA / SYSDBA user:
        sqlplus sys/syspass@DEVPDB as sysdba @scripts/oracle_users_setup.sql
3.  Add to .env:
        DB_READ_USER=justclick_read
        DB_READ_PASS=<your_read_password>
        DB_DML_USER=justclick_dml
        DB_DML_PASS=<your_dml_password>
4.  Restart the application — the pools are lazy-initialised at first request.
"""

import re
import sys
import argparse
from pathlib import Path

# ── Locate project root ───────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent

# ── Tables from justclick_comments.sql ───────────────────────────────────────

def _get_comment_tables(sql_path: Path) -> list[str]:
    """Extract table names from every COMMENT ON TABLE statement."""
    src = sql_path.read_text(encoding="utf-8", errors="replace")
    names = re.findall(r"COMMENT\s+ON\s+TABLE\s+(\w+)", src, re.IGNORECASE)
    return sorted(set(n.upper() for n in names))


# ── DML tables derived from erp_actions/registry.py ─────────────────────────
# These are the ONLY tables the action executor writes to.
# Extracted once from registry.py; update here if new actions are added.

_DML_GRANTS: dict[str, list[str]] = {
    # table               : [privileges]
    "CUST":               ["INSERT", "UPDATE", "SELECT"],   # customers / suppliers
    "ITEMS":              ["INSERT", "UPDATE", "SELECT"],   # items / products
    "PAYED":              ["INSERT", "SELECT"],             # payments / collections
    "AI_ACTION_REQUESTS": ["INSERT", "UPDATE"],             # workflow approve/reject
}

_SEQUENCES: list[str] = [
    "CUST_SEQ",    # new customer / supplier ID
    "ITEMS_SEQ",   # new item ID
    "PAYED_SEQ",   # new payment ID
]


# ── AI_ACTION_REQUESTS DDL ───────────────────────────────────────────────────

def _ai_action_requests_ddl(schema: str) -> str:
    return f"""\
-- ============================================================
-- AI_ACTION_REQUESTS — workflow tracking table
-- Run as schema owner ({schema}) or DBA
-- ============================================================

-- Drop if re-running (comment out if table already has data)
-- DROP TABLE {schema}.AI_ACTION_REQUESTS CASCADE CONSTRAINTS;

CREATE TABLE {schema}.AI_ACTION_REQUESTS (
    REQUEST_ID      NUMBER         GENERATED ALWAYS AS IDENTITY
                                   START WITH 1 INCREMENT BY 1
                                   NOCACHE CONSTRAINT pk_air PRIMARY KEY,
    ACTION_TYPE     VARCHAR2(100)  NOT NULL,
    REQUEST_TYPE    VARCHAR2(100),
    STATUS          VARCHAR2(20)   DEFAULT 'pending'
                                   CONSTRAINT chk_air_status
                                   CHECK (STATUS IN ('pending','approved','rejected','completed','cancelled')),
    DESCRIPTION     VARCHAR2(500),
    AMOUNT          NUMBER(18, 3),
    REQUESTED_BY    VARCHAR2(100),
    ASSIGNED_TO     VARCHAR2(100),
    REQUESTED_AT    TIMESTAMP      DEFAULT SYSTIMESTAMP NOT NULL,
    APPROVED_BY     VARCHAR2(100),
    APPROVED_AT     TIMESTAMP,
    NOTES           VARCHAR2(1000),
    COMPANY_CODE    VARCHAR2(10)   DEFAULT '1'          NOT NULL,
    FISCAL_YEAR     VARCHAR2(10)
);

CREATE INDEX idx_air_status_co ON {schema}.AI_ACTION_REQUESTS (STATUS, COMPANY_CODE);
CREATE INDEX idx_air_requested ON {schema}.AI_ACTION_REQUESTS (REQUESTED_BY, REQUESTED_AT);
CREATE INDEX idx_air_assigned  ON {schema}.AI_ACTION_REQUESTS (ASSIGNED_TO)
    WHERE ASSIGNED_TO IS NOT NULL;

COMMENT ON TABLE  {schema}.AI_ACTION_REQUESTS IS 'JustClick AI Chatbot — pending / completed workflow actions';
COMMENT ON COLUMN {schema}.AI_ACTION_REQUESTS.STATUS IS 'pending | approved | rejected | completed | cancelled';
"""


# ── Read-only user SQL ────────────────────────────────────────────────────────

def _read_user_sql(schema: str, read_user: str, tables: list[str]) -> str:
    lines = [
        "-- ============================================================",
        f"-- READ-ONLY USER: {read_user}",
        "-- Run as DBA / SYSDBA",
        "-- ============================================================",
        "",
        f"CREATE USER {read_user}",
        f"    IDENTIFIED BY \"CHANGE_ME_READ_PASS\"",
        f"    DEFAULT TABLESPACE USERS",
        f"    TEMPORARY TABLESPACE TEMP",
        f"    QUOTA 0 ON USERS;      -- no storage: read-only, no temp tables",
        "",
        f"GRANT CREATE SESSION TO {read_user};",
        "",
        "-- SELECT on all ERP tables (comment-driven — matches justclick_comments.sql)",
    ]

    for tbl in tables:
        lines.append(f"GRANT SELECT ON {schema}.{tbl} TO {read_user};")

    lines += [
        "",
        "-- SELECT on workflow tracking table (queries via execute_read_query)",
        f"GRANT SELECT ON {schema}.AI_ACTION_REQUESTS TO {read_user};",
        "",
        "-- No sequence grants needed for the read user (CURRVAL requires prior NEXTVAL",
        "-- on the same session, which read queries never issue).",
        "",
        "-- Verify (run as DBA):",
        f"-- SELECT COUNT(*) FROM {schema}.MAIN_INV FETCH FIRST 1 ROWS ONLY;  -- should succeed",
        f"-- UPDATE {schema}.CUST SET ACTIVE='0' WHERE ROWNUM = 1;            -- should fail ORA-01031",
    ]

    return "\n".join(lines)


# ── DML user SQL ─────────────────────────────────────────────────────────────

def _dml_user_sql(schema: str, dml_user: str) -> str:
    lines = [
        "",
        "-- ============================================================",
        f"-- DML USER: {dml_user}",
        "-- Run as DBA / SYSDBA",
        "-- ============================================================",
        "",
        f"CREATE USER {dml_user}",
        f"    IDENTIFIED BY \"CHANGE_ME_DML_PASS\"",
        f"    DEFAULT TABLESPACE USERS",
        f"    TEMPORARY TABLESPACE TEMP",
        f"    QUOTA 0 ON USERS;",
        "",
        f"GRANT CREATE SESSION TO {dml_user};",
        "",
        "-- Table-level DML grants (minimum required by erp_actions/registry.py)",
    ]

    for tbl, privs in _DML_GRANTS.items():
        qualified = f"{schema}.{tbl}" if tbl != "AI_ACTION_REQUESTS" else f"{schema}.{tbl}"
        privs_str = ", ".join(privs)
        comment = {
            "CUST":               "customers + suppliers: create, update, deactivate",
            "ITEMS":              "items: create, update, price change",
            "PAYED":              "payments + collections: create (no UPDATE — immutable records)",
            "AI_ACTION_REQUESTS": "workflow: approve, reject, new request",
        }.get(tbl, "")
        lines.append(f"-- {comment}")
        lines.append(f"GRANT {privs_str} ON {qualified} TO {dml_user};")
        lines.append("")

    lines += [
        "-- Sequence NEXTVAL for INSERT ID generation",
        "-- (SELECT on sequence = permission to call .NEXTVAL and .CURRVAL)",
    ]
    for seq in _SEQUENCES:
        lines.append(f"GRANT SELECT ON {schema}.{seq} TO {dml_user};")

    lines += [
        "",
        "-- No access to chat/reporting tables — DML user cannot read MAIN_INV,",
        "-- TRANSACTION_TOT, VOUCHERS, etc. Full privilege separation.",
        "",
        "-- Verify (run as DBA):",
        f"-- UPDATE {schema}.CUST SET ACTIVE='0' WHERE ROWNUM = 0;  -- should succeed (0 rows)",
        f"-- SELECT COUNT(*) FROM {schema}.MAIN_INV;                 -- should fail  ORA-01031",
    ]

    return "\n".join(lines)


# ── Password profile (optional hardening) ────────────────────────────────────

_PROFILE_SQL = """\

-- ============================================================
-- OPTIONAL: Security profile for both chatbot users
-- Prevents brute-force and limits runaway session resources.
-- Run as DBA / SYSDBA before creating the users, or alter
-- users after creation: ALTER USER <name> PROFILE chatbot_profile;
-- ============================================================

-- DROP PROFILE chatbot_profile CASCADE;   -- uncomment to re-create

CREATE PROFILE chatbot_profile LIMIT
    FAILED_LOGIN_ATTEMPTS    5
    PASSWORD_LOCK_TIME       1/24           -- 1 hour
    PASSWORD_LIFE_TIME       180            -- 6 months
    PASSWORD_REUSE_TIME      365
    PASSWORD_REUSE_MAX       5
    SESSIONS_PER_USER        20             -- max concurrent connections
    CPU_PER_SESSION          UNLIMITED
    IDLE_TIME                30             -- disconnect idle after 30 min
    CONNECT_TIME             UNLIMITED;

-- Apply profile (uncomment after creating users):
-- ALTER USER {read_user}  PROFILE chatbot_profile;
-- ALTER USER {dml_user}   PROFILE chatbot_profile;
"""


# ── Post-setup verification queries ──────────────────────────────────────────

def _verify_sql(schema: str, read_user: str, dml_user: str) -> str:
    return f"""
-- ============================================================
-- VERIFICATION QUERIES
-- Run each block connected as the indicated user.
-- ============================================================

-- [ As {read_user} ] --
-- SELECT COUNT(*) FROM {schema}.MAIN_INV FETCH FIRST 1 ROWS ONLY;
-- Expected: 1 row with a count value
-- SELECT COUNT(*) FROM {schema}.AI_ACTION_REQUESTS FETCH FIRST 1 ROWS ONLY;
-- Expected: 1 row (0 if no data yet)
-- UPDATE {schema}.CUST SET ACTIVE='0' WHERE ROWNUM = 1;
-- Expected: ORA-01031: insufficient privileges  <-- GOOD

-- [ As {dml_user} ] --
-- UPDATE {schema}.CUST SET ACTIVE='0' WHERE ROWNUM = 0;
-- Expected: 0 rows updated (no error)
-- SELECT {schema}.CUST_SEQ.NEXTVAL FROM DUAL;
-- Expected: a sequence number
-- SELECT COUNT(*) FROM {schema}.MAIN_INV;
-- Expected: ORA-01031: insufficient privileges  <-- GOOD
-- SELECT COUNT(*) FROM {schema}.VOUCHERS;
-- Expected: ORA-01031: insufficient privileges  <-- GOOD

-- [ As DBA ] --
-- SELECT GRANTED_ROLE, ADMIN_OPTION
-- FROM DBA_ROLE_PRIVS
-- WHERE GRANTEE IN ('{read_user}', '{dml_user}');
-- Expected: only CREATE SESSION, no DBA / RESOURCE / CONNECT roles
"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--schema",    default="justclick",      help="Oracle schema owner")
    parser.add_argument("--read-user", default="justclick_read", help="Read-only user name")
    parser.add_argument("--dml-user",  default="justclick_dml",  help="DML-only user name")
    parser.add_argument("--out", default=str(_ROOT / "scripts" / "oracle_users_setup.sql"),
                        help="Output SQL file path")
    args = parser.parse_args()

    schema    = args.schema.lower()
    read_user = args.read_user.lower()
    dml_user  = args.dml_user.lower()
    out_path  = Path(args.out)

    # Read tables from justclick_comments.sql
    comments_path = _ROOT / "justclick_comments.sql"
    if not comments_path.exists():
        print(f"ERROR: {comments_path} not found", file=sys.stderr)
        sys.exit(1)

    tables = _get_comment_tables(comments_path)
    print(f"[GEN] Found {len(tables)} tables in {comments_path.name}")

    # Build SQL
    header = f"""\
-- ============================================================
-- JustClick AI Chatbot — Oracle User Separation Setup
-- Generated by scripts/gen_oracle_grants.py
-- Schema owner : {schema}
-- Read-only user: {read_user}
-- DML-only user : {dml_user}
--
-- HOW TO RUN:
--   1. Replace CHANGE_ME_READ_PASS and CHANGE_ME_DML_PASS with
--      strong passwords of your choice.
--   2. Connect as DBA / SYSDBA and run this file:
--        sqlplus sys/<syspass>@{'{DB_HOST}:{DB_PORT}/{DB_SID}'} as sysdba
--        @scripts/oracle_users_setup.sql
--   3. Add to .env:
--        DB_READ_USER={read_user}
--        DB_READ_PASS=<your_read_password>
--        DB_DML_USER={dml_user}
--        DB_DML_PASS=<your_dml_password>
--   4. Restart the application.
-- ============================================================

SET ECHO ON
SET FEEDBACK ON
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK;

"""

    parts = [
        header,
        _ai_action_requests_ddl(schema),
        _PROFILE_SQL.replace("{read_user}", read_user).replace("{dml_user}", dml_user),
        _read_user_sql(schema, read_user, tables),
        _dml_user_sql(schema, dml_user),
        _verify_sql(schema, read_user, dml_user),
        "\nCOMMIT;\n",
    ]

    sql_out = "\n".join(parts)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(sql_out, encoding="utf-8")
    print(f"[GEN] Written: {out_path}")
    print(f"[GEN] Read-user grants: {len(tables) + 1} tables")
    print(f"[GEN] DML-user grants : {len(_DML_GRANTS)} tables + {len(_SEQUENCES)} sequences")
    print()
    print("Next steps:")
    print(f"  1. Edit {out_path.name} — replace CHANGE_ME_* passwords")
    print("  2. sqlplus sys/<pass>@<SID> as sysdba @scripts/oracle_users_setup.sql")
    print(f"  3. Add to .env: DB_READ_USER={read_user}  DB_DML_USER={dml_user}")
    print("  4. Restart the application")


if __name__ == "__main__":
    main()
