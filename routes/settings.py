"""Application settings API routes."""

from __future__ import annotations

from flask import Blueprint, request

from config import DEFAULT_SYSTEM_PROMPT
from routes.helpers import error_response, success_response
from services.conversation_service import ConversationService, ServiceError
from services.settings_service import SettingsService, SettingsValidationError

settings_bp = Blueprint("settings", __name__, url_prefix="/api")


@settings_bp.get("/settings")
def get_settings():
    data = SettingsService.get_all()
    data["database_path"] = SettingsService.database_path()
    data["default_system_prompt"] = DEFAULT_SYSTEM_PROMPT
    return success_response(data)


@settings_bp.put("/settings")
def update_settings():
    payload = request.get_json(silent=True) or {}
    try:
        updated = SettingsService.set_many(payload)
        updated["database_path"] = SettingsService.database_path()
        updated["default_system_prompt"] = DEFAULT_SYSTEM_PROMPT
        return success_response(updated)
    except SettingsValidationError as exc:
        return error_response(exc.code, exc.message, 400)


@settings_bp.post("/settings/reset-system-prompt")
def reset_system_prompt():
    try:
        updated = SettingsService.reset_system_prompt()
        updated["database_path"] = SettingsService.database_path()
        updated["default_system_prompt"] = DEFAULT_SYSTEM_PROMPT
        return success_response(updated)
    except SettingsValidationError as exc:
        return error_response(exc.code, exc.message, 400)


@settings_bp.delete("/settings/conversations")
def clear_conversations():
    try:
        count = ConversationService.clear_all_conversations()
        return success_response({"cleared": count})
    except ServiceError as exc:
        return error_response(exc.code, exc.message, exc.status_code)
