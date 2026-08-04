"""Conversation CRUD API routes."""

from __future__ import annotations

from flask import Blueprint, request

from routes.helpers import error_response, success_response
from services.conversation_service import ConversationService, ServiceError
from services.settings_service import SettingsService

conversations_bp = Blueprint("conversations", __name__, url_prefix="/api")


@conversations_bp.get("/conversations")
def list_conversations():
    search = request.args.get("search") or request.args.get("q")
    items = ConversationService.list_conversations(search=search)
    storage_map = ConversationService.get_storage_map()
    payload = []
    for conversation in items:
        data = conversation.to_dict()
        data["storage_bytes"] = storage_map.get(conversation.id, 0)
        payload.append(data)
    return success_response(payload)


@conversations_bp.get("/storage")
def storage_info():
    storage_map = ConversationService.get_storage_map()
    return success_response(
        {
            "database_bytes": ConversationService.get_database_size_bytes(),
            "total_chat_bytes": int(sum(storage_map.values())),
            "conversation_count": len(storage_map),
        }
    )


@conversations_bp.post("/conversations")
def create_conversation():
    payload = request.get_json(silent=True) or {}
    settings = SettingsService.get_all()
    provider = payload.get("provider") or settings.get("default_provider") or "groq"
    model = payload.get("model") or settings.get("default_model") or ""
    title = payload.get("title") or "New Chat"
    history = payload.get("messages")
    try:
        if isinstance(history, list) and history:
            conversation = ConversationService.create_conversation_with_history(
                provider=provider,
                model=model,
                title=title,
                messages=history,
            )
        else:
            conversation = ConversationService.create_conversation(
                provider=provider,
                model=model,
                title=title,
            )
        return success_response(conversation.to_dict(include_messages=True), 201)
    except ServiceError as exc:
        return error_response(exc.code, exc.message, exc.status_code)


@conversations_bp.get("/conversations/<int:conversation_id>")
def get_conversation(conversation_id: int):
    try:
        conversation = ConversationService.get_conversation(conversation_id)
        return success_response(conversation.to_dict(include_messages=True))
    except ServiceError as exc:
        return error_response(exc.code, exc.message, exc.status_code)


@conversations_bp.patch("/conversations/<int:conversation_id>")
def update_conversation(conversation_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        conversation = ConversationService.update_conversation(conversation_id, **payload)
        return success_response(conversation.to_dict())
    except ServiceError as exc:
        return error_response(exc.code, exc.message, exc.status_code)


@conversations_bp.delete("/conversations/<int:conversation_id>")
def delete_conversation(conversation_id: int):
    try:
        ConversationService.delete_conversation(conversation_id)
        return success_response({"deleted": True})
    except ServiceError as exc:
        return error_response(exc.code, exc.message, exc.status_code)
