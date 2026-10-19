"""Repository layout rules, so the root does not fill up with loose files again."""
import importlib
import pkgutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ["security", "nlu", "infra", "llm", "reporting", "routers",
            "erp_actions", "learning", "proactive", "profiles"]


def tracked(pattern: str = "") -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f and pattern in f]


def test_only_the_entry_points_live_at_the_root():
    root_py = sorted(f for f in tracked() if f.endswith(".py") and "/" not in f)
    assert root_py == ["app.py", "pipeline.py"]


def test_no_generated_files_are_tracked():
    bad = [f for f in tracked() if f.endswith((".log", ".pyc")) or "__pycache__" in f
           or f.split("/")[-1].startswith(".coverage") or "htmlcov/" in f
           or ("/" not in f and f.endswith(".json"))]
    assert bad == []


def test_no_secrets_are_tracked():
    assert [f for f in tracked() if Path(f).name == ".env"] == []
    assert ".env.example" in [Path(f).name for f in tracked()]


@pytest.mark.parametrize("package", PACKAGES)
def test_every_module_in_every_package_imports(package):
    pkg = importlib.import_module(package)
    failures = []
    for module in pkgutil.walk_packages(pkg.__path__, package + "."):
        try:
            importlib.import_module(module.name)
        except Exception as exc:                               # noqa: BLE001 - report all
            failures.append(f"{module.name}: {exc!r}")
    assert failures == []


def test_each_profile_directory_is_a_package():
    for directory in (ROOT / "profiles").iterdir():
        if directory.is_dir() and not directory.name.startswith("__"):
            assert (directory / "__init__.py").exists(), directory.name


def test_security_layer_does_not_depend_on_http_routers():
    """The safety modules must stay usable without FastAPI."""
    for path in (ROOT / "security").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "from routers" not in text and "import routers" not in text, path.name
        assert "fastapi" not in text.lower(), path.name


def test_requirements_list_what_the_code_imports():
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for needed in ("fastapi", "oracledb", "openpyxl", "pyjwt", "groq", "python-multipart"):
        assert needed in reqs, needed


def test_db_check_script_collects_every_shipped_query(justclick_profile):
    """The live checker must see all templates, widgets and report queries, scoped and safe."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_sql_against_db", ROOT / "scripts" / "check_sql_against_db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    queries = module.collect_queries(company_code="9", fiscal_year="2025")
    assert len(queries) >= 21 + 43 + 30
    assert all(sql is not None for _, sql, _ in queries), [q[0] for q in queries if q[1] is None]


def test_test_data_is_not_gitignored():
    """tests/data holds the golden questions; a blanket `data/` ignore rule once dropped it from the repo."""
    import subprocess
    out = subprocess.run(["git", "check-ignore", "tests/data/golden_justclick.py"], cwd=ROOT, capture_output=True)
    assert out.returncode == 1
