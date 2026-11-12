import os
import sys
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(WORKSPACE_ROOT / ".env")

live_database = dotenv_values(WORKSPACE_ROOT / ".env").get("DB_NAME")
test_database = os.getenv("AUTOLEDGER_TEST_DB_NAME", "").strip()
allow_dev_clone = os.getenv("AUTOLEDGER_ALLOW_DEV_CLONE") == "1"
if not test_database:
    raise RuntimeError(
        "Set AUTOLEDGER_TEST_DB_NAME to a dedicated isolated test database before running pytest."
    )
explicit_dev_clone = test_database == "autoledger_dev_clone" and allow_dev_clone
if test_database.casefold() == "autoledger_db":
    raise RuntimeError("The live autoledger_db database is never an allowed pytest target.")
if test_database.casefold() == (live_database or "").casefold() and not explicit_dev_clone:
    raise RuntimeError("The test database must not be the configured live database.")
if explicit_dev_clone:
    if os.getenv("DB_HOST", "").casefold() not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("The explicitly allowed development clone must use a local PostgreSQL host.")
    if os.getenv("DB_PORT") != "2005":
        raise RuntimeError("The explicitly allowed development clone must use PostgreSQL port 2005.")
else:
    if test_database == "autoledger_dev_clone":
        raise RuntimeError(
            "Set AUTOLEDGER_ALLOW_DEV_CLONE=1 to explicitly allow tests on autoledger_dev_clone."
        )
    if not test_database.startswith("autoledger_test_"):
        raise RuntimeError("AUTOLEDGER_TEST_DB_NAME must begin with 'autoledger_test_'.")
os.environ.pop("DATABASE_URL", None)
os.environ["DB_HOST"] = os.getenv("DB_HOST", "localhost")
os.environ["DB_PORT"] = os.getenv("DB_PORT", "2005")
os.environ["DB_NAME"] = test_database