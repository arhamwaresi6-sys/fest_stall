import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_flag(name, default=False):
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    DEBUG = _env_flag("FLASK_DEBUG")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-this-key")
    SQLALCHEMY_DATABASE_URI = (
        os.getenv("DATABASE_URL")
        or os.getenv("SQLALCHEMY_DATABASE_URI")
        or f"sqlite:///{(BASE_DIR / 'instance' / 'food_stall.db').as_posix()}"
    )
    if SQLALCHEMY_DATABASE_URI.startswith(("postgres://", "postgresql://")):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql+psycopg://", 1
        ).replace("postgresql://", "postgresql+psycopg://", 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1") == "1"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_SAMESITE = "Lax"
    WTF_CSRF_TIME_LIMIT = 3600
    TIMEZONE = "Asia/Dhaka"
    CURRENCY = "৳"
