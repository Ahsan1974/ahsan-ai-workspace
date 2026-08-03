"""Application settings service."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from config import Config, DEFAULT_SYSTEM_PROMPT
from extensions import db
from models.app_setting import AppSetting

logger = logging.getLogger(__name__)

# Keys that may be exported (never secrets).
EXPORTABLE_SETTING_KEYS = {
    "theme",
    "default_provider",
    "default_model",
    "confirm_delete",
    "enter_to_send",
    "temperature",
    "max_tokens",
    "system_prompt",
    "context_messages",
}

SENSITIVE_KEYS = {"api_key", "secret", "password", "token", "authorization", "secret_key"}
SENSITIVE_SUFFIXES = ("_api_key", "_secret", "_password", "_token")


class SettingsValidationError(Exception):
    def __init__(self, message: str) -> None:
        self.code = "INVALID_SETTINGS"
        self.message = message
        super().__init__(message)


def _default_settings() -> dict[str, Any]:
    return {
        "theme": "dark",
        "default_provider": Config.DEFAULT_PROVIDER,
        "default_model": Config.GROQ_DEFAULT_MODEL,
        "confirm_delete": True,
        "enter_to_send": True,
        "temperature": Config.DEFAULT_TEMPERATURE,
        "max_tokens": Config.DEFAULT_MAX_TOKENS,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "context_messages": Config.MAX_CONTEXT_MESSAGES,
    }


def _serialize_value(value: Any) -> str:
    if isinstance(value, (dict, list, bool, int, float)) or value is None:
        return json.dumps(value)
    return str(value)


def _deserialize_value(raw: str, key: str) -> Any:
    defaults = _default_settings()
    default = defaults.get(key)
    if isinstance(default, bool):
        try:
            return bool(json.loads(raw))
        except (TypeError, json.JSONDecodeError):
            return str(raw).lower() in {"1", "true", "yes", "on"}
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            parsed = json.loads(raw)
            return int(parsed)
        except (TypeError, ValueError, json.JSONDecodeError):
            try:
                return int(raw)
            except ValueError:
                return default
    if isinstance(default, float):
        try:
            parsed = json.loads(raw)
            return float(parsed)
        except (TypeError, ValueError, json.JSONDecodeError):
            try:
                return float(raw)
            except ValueError:
                return default
    if raw.startswith("{") or raw.startswith("["):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in SENSITIVE_KEYS or any(lowered.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)


class SettingsService:
    """Read and validate persisted application settings."""

    @classmethod
    def ensure_defaults(cls) -> None:
        """Create missing default settings on startup."""
        for key, value in _default_settings().items():
            existing = AppSetting.query.filter_by(key=key).first()
            if existing is None:
                db.session.add(AppSetting(key=key, value=_serialize_value(value)))
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Failed to seed default settings")
            raise

    @classmethod
    def get_all(cls) -> dict[str, Any]:
        settings = _default_settings()
        rows = AppSetting.query.all()
        for row in rows:
            if _is_sensitive_key(row.key):
                continue
            settings[row.key] = _deserialize_value(row.value, row.key)
        return settings

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        row = AppSetting.query.filter_by(key=key).first()
        if row is None:
            return _default_settings().get(key, default)
        return _deserialize_value(row.value, key)

    @classmethod
    def set_many(cls, updates: dict[str, Any]) -> dict[str, Any]:
        validated = cls.validate(updates)
        for key, value in validated.items():
            if _is_sensitive_key(key):
                raise SettingsValidationError("Sensitive settings cannot be stored this way.")
            row = AppSetting.query.filter_by(key=key).first()
            serialized = _serialize_value(value)
            if row is None:
                db.session.add(AppSetting(key=key, value=serialized))
            else:
                row.value = serialized
        try:
            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.exception("Failed to update settings")
            raise SettingsValidationError("Unable to save settings.") from exc
        return cls.get_all()

    @classmethod
    def validate(cls, updates: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(updates, dict):
            raise SettingsValidationError("Settings payload must be an object.")

        allowed = set(_default_settings().keys())
        unknown = set(updates.keys()) - allowed
        if unknown:
            raise SettingsValidationError(f"Unknown settings: {', '.join(sorted(unknown))}")

        current = cls.get_all()
        merged = {**current, **updates}
        result: dict[str, Any] = {}

        theme = str(merged.get("theme", "dark")).lower()
        if theme not in {"dark", "light"}:
            raise SettingsValidationError("Theme must be 'dark' or 'light'.")
        result["theme"] = theme

        provider = str(merged.get("default_provider", "groq")).lower().strip()
        allowed_providers = {"groq", "sambanova", "gemini", "openrouter", "mistral", "cohere"}
        if provider not in allowed_providers:
            raise SettingsValidationError("Unsupported default provider.")
        result["default_provider"] = provider

        model = str(merged.get("default_model", Config.GROQ_DEFAULT_MODEL)).strip()
        if not model:
            raise SettingsValidationError("Default model cannot be empty.")
        if len(model) > 120:
            raise SettingsValidationError("Default model name is too long.")
        result["default_model"] = model

        result["confirm_delete"] = bool(merged.get("confirm_delete", True))
        result["enter_to_send"] = bool(merged.get("enter_to_send", True))

        try:
            temperature = float(merged.get("temperature", Config.DEFAULT_TEMPERATURE))
        except (TypeError, ValueError) as exc:
            raise SettingsValidationError("Temperature must be a number.") from exc
        if temperature < 0 or temperature > 2:
            raise SettingsValidationError("Temperature must be between 0 and 2.")
        result["temperature"] = temperature

        try:
            max_tokens = int(merged.get("max_tokens", Config.DEFAULT_MAX_TOKENS))
        except (TypeError, ValueError) as exc:
            raise SettingsValidationError("Maximum tokens must be an integer.") from exc
        if max_tokens < 1 or max_tokens > 128000:
            raise SettingsValidationError("Maximum tokens must be between 1 and 128000.")
        result["max_tokens"] = max_tokens

        system_prompt = str(merged.get("system_prompt", DEFAULT_SYSTEM_PROMPT))
        if len(system_prompt) > 20000:
            raise SettingsValidationError("System prompt is too long.")
        result["system_prompt"] = system_prompt

        try:
            context_messages = int(merged.get("context_messages", Config.MAX_CONTEXT_MESSAGES))
        except (TypeError, ValueError) as exc:
            raise SettingsValidationError("Context messages must be an integer.") from exc
        if context_messages < 1 or context_messages > 200:
            raise SettingsValidationError("Context messages must be between 1 and 200.")
        result["context_messages"] = context_messages

        # Only return keys that were requested for update, but validate the full merge.
        return {key: result[key] for key in updates.keys()}

    @classmethod
    def reset_system_prompt(cls) -> dict[str, Any]:
        return cls.set_many({"system_prompt": DEFAULT_SYSTEM_PROMPT})

    @classmethod
    def exportable_settings(cls) -> dict[str, Any]:
        all_settings = cls.get_all()
        return {k: v for k, v in all_settings.items() if k in EXPORTABLE_SETTING_KEYS}

    @classmethod
    def database_path(cls) -> str:
        uri = Config.SQLALCHEMY_DATABASE_URI
        if uri.startswith("sqlite:///"):
            return uri.replace("sqlite:///", "", 1)
        return uri
