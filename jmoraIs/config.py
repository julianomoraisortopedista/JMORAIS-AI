import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///./jmoraIs.db")


def get_app_env() -> str:
    return os.getenv("APP_ENV", "development")
