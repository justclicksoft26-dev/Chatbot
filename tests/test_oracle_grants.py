"""The generated Oracle script must not stop on an object this database does not have, and must cover what the app uses."""
import importlib.util
import pathlib

SPEC = importlib.util.spec_from_file_location("gen_grants", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "gen_oracle_grants.py")
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)


def test_read_user_script_skips_missing_objects_and_may_run_the_stock_function():
    sql = gen._read_user_sql("justclick", "justclick_read", ["ITEMS", "MAIN_INV"])
    assert "grant_if_exists('ITEMS', 'SELECT', 'justclick_read', 'TABLE')" in sql
    assert "grant_if_exists('RASEED', 'EXECUTE', 'justclick_read', 'FUNCTION')" in sql
    assert "GRANT SELECT ON justclick.ITEMS" not in sql           # no bare GRANT that aborts the script when a table is absent
    assert "DB_SCHEMA=justclick" in sql


def test_dml_user_sequences_are_granted_only_if_they_exist():
    sql = gen._dml_user_sql("justclick", "justclick_dml")
    assert "grant_if_exists('CUST_SEQ', 'SELECT', 'justclick_dml', 'SEQUENCE')" in sql


def test_workflow_table_ddl_has_no_partial_index():
    assert "WHERE ASSIGNED_TO" not in gen._ai_action_requests_ddl("justclick")      # Oracle has no partial indexes (ORA-00933)


def test_tables_come_from_the_profiles_comments():
    path = pathlib.Path(__file__).resolve().parent.parent / "profiles" / "justclick" / "comments.sql"
    assert "MAIN_INV" in gen._get_comment_tables(path)
