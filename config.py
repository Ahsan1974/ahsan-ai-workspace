"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent


def running_on_vercel() -> bool:
    """Vercel sets VERCEL=1 (and usually VERCEL_ENV) in serverless runtimes."""
    return os.getenv("VERCEL") == "1" or bool(os.getenv("VERCEL_ENV"))


# Vercel’s deployment filesystem is read-only except /tmp.
if running_on_vercel():
    INSTANCE_DIR = Path(tempfile.gettempdir()) / "ahsan-ai-workspace"
else:
    INSTANCE_DIR = BASE_DIR / "instance"

load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig")

APP_NAME = "Ahsan AI Workspace"

DEFAULT_SYSTEM_PROMPT = """You are Ahsan's personal AI assistant.

Provide accurate, clear, practical, and well-structured answers.

For programming questions:
- Prefer practical examples.
- Provide complete and runnable code when appropriate.
- Explain important parts in simple language.
- Focus especially on Python, Java, Spring Boot, software engineering, and software architecture.
- Use Markdown code blocks with the correct language identifier.
- Mention assumptions and limitations honestly.
- Do not invent APIs, packages, methods, facts, or citations.

For general questions:
- Give a direct answer first.
- Explain the reasoning clearly.
- Avoid unnecessary repetition."""


class Config:
    """Flask and application settings."""

    APP_NAME = APP_NAME
    SECRET_KEY = os.getenv("SECRET_KEY", "replace-with-a-random-local-secret")
    _raw_database_url = (os.getenv("DATABASE_URL") or "").strip()
    SQLALCHEMY_DATABASE_URI = _raw_database_url or f"sqlite:///{INSTANCE_DIR / 'personal_ai_workspace.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Neon / Heroku style URLs often use postgres:// — SQLAlchemy needs postgresql://
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = "postgresql://" + SQLALCHEMY_DATABASE_URI[len("postgres://") :]
    if SQLALCHEMY_DATABASE_URI.startswith("postgresql://"):
        SQLALCHEMY_DATABASE_URI = (
            "postgresql+psycopg://" + SQLALCHEMY_DATABASE_URI[len("postgresql://") :]
        )
    SQLALCHEMY_ENGINE_OPTIONS = (
        {"pool_pre_ping": True, "pool_recycle": 280}
        if SQLALCHEMY_DATABASE_URI.startswith(("postgresql+psycopg://", "mysql://"))
        else {}
    )

    FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1")
    FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes"}

    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
    GROQ_DEFAULT_MODEL = os.getenv("GROQ_DEFAULT_MODEL", "llama-3.3-70b-versatile")
    GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")

    SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY", "").strip()
    SAMBANOVA_DEFAULT_MODEL = os.getenv("SAMBANOVA_DEFAULT_MODEL", "Meta-Llama-3.3-70B-Instruct")

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_DEFAULT_MODEL = os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.0-flash")

    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
    OPENROUTER_DEFAULT_MODEL = os.getenv("OPENROUTER_DEFAULT_MODEL", "x-ai/grok-4.5")

    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "").strip()
    MISTRAL_DEFAULT_MODEL = os.getenv("MISTRAL_DEFAULT_MODEL", "mistral-small-latest")

    COHERE_API_KEY = os.getenv("COHERE_API_KEY", "").strip()
    COHERE_DEFAULT_MODEL = os.getenv("COHERE_DEFAULT_MODEL", "command-r-plus-08-2024")

    DEFAULT_TEMPERATURE = float(os.getenv("DEFAULT_TEMPERATURE", "0.7"))
    DEFAULT_MAX_TOKENS = int(os.getenv("DEFAULT_MAX_TOKENS", "4096"))
    MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", "80"))
    MAX_MESSAGE_CHARACTERS = int(os.getenv("MAX_MESSAGE_CHARACTERS", "20000"))
    MAX_IMPORT_SIZE_MB = int(os.getenv("MAX_IMPORT_SIZE_MB", "10"))
    # Vercel request body hard-limit is ~4.5MB — keep uploads under that.
    _upload_default = "3" if running_on_vercel() else "20"
    MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", _upload_default))
    if running_on_vercel():
        MAX_UPLOAD_SIZE_MB = min(MAX_UPLOAD_SIZE_MB, 3)

    DEFAULT_SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT
    DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "groq").strip().lower() or "groq"
    # Streaming SSE is unreliable on many Vercel setups; prefer JSON responses there.
    PREFER_STREAM = os.getenv(
        "PREFER_STREAM",
        "false" if running_on_vercel() else "true",
    ).lower() in {"1", "true", "yes", "on"}

    # On Vercel, use remote DATABASE_URL when set; otherwise fall back to ephemeral /tmp SQLite.
    if running_on_vercel():
        remote = (os.getenv("DATABASE_URL") or "").strip()
        if remote.startswith("postgres://"):
            remote = "postgresql://" + remote[len("postgres://") :]
        if remote.startswith("postgresql://"):
            remote = "postgresql+psycopg://" + remote[len("postgresql://") :]
        if remote.startswith(("postgresql+psycopg://", "mysql://")):
            SQLALCHEMY_DATABASE_URI = remote
            SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
        else:
            absolute = INSTANCE_DIR / "personal_ai_workspace.db"
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{absolute.as_posix()}"
            SQLALCHEMY_ENGINE_OPTIONS = {}
    elif SQLALCHEMY_DATABASE_URI.startswith("sqlite:///"):
        db_path = SQLALCHEMY_DATABASE_URI.replace("sqlite:///", "", 1)
        if not os.path.isabs(db_path):
            absolute = INSTANCE_DIR / Path(db_path).name
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{absolute.as_posix()}"

    DURABLE_DATABASE = not SQLALCHEMY_DATABASE_URI.startswith("sqlite:")
