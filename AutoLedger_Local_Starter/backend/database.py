import logging
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from fastapi import HTTPException

PROJECT_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = PROJECT_DIR.parent
load_dotenv(PROJECT_DIR / ".env")
load_dotenv(WORKSPACE_DIR / ".env")

logger = logging.getLogger(__name__)


def get_connection():
    try:
        database_url = os.getenv("DATABASE_URL", "").strip()
        if database_url:
            connect_options = {"connect_timeout": 5}
            if os.getenv("APP_ENV", "development").casefold() == "production":
                connect_options["sslmode"] = "require"
            return psycopg2.connect(database_url, **connect_options)

        return psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "2005"),
            dbname=os.getenv("DB_NAME", "autoledger_db"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            connect_timeout=5,
        )
    except Exception as exc:
        logger.exception("Database connection failed")
        raise HTTPException(
            status_code=503,
            detail="Database connection failed. Check the server logs for the underlying error.",
        ) from exc