"""Export and import helpers for conversations."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from extensions import db
from models.conversation import Conversation
from models.message import Message
from services.conversation_service import ServiceError
from services.settings_service import SettingsService

logger = logging.getLogger(__name__)

EXPORT_VERSION = 1


class ExportService:
    """Create and restore portable conversation archives."""

    @staticmethod
    def conversation_to_markdown(conversation: Conversation) -> str:
        lines = [
            f"# {conversation.title}",
            "",
            f"- Provider: {conversation.provider}",
            f"- Model: {conversation.model}",
            f"- Created: {conversation.created_at.isoformat() if conversation.created_at else ''}",
            f"- Updated: {conversation.updated_at.isoformat() if conversation.updated_at else ''}",
            "",
            "---",
            "",
        ]
        for message in conversation.messages:
            role = message.role.capitalize()
            meta = ""
            if message.role == "assistant" and (message.provider or message.model):
                meta = f" ({message.provider or ''} / {message.model or ''})".replace(" / )", ")")
            lines.append(f"## {role}{meta}")
            lines.append("")
            lines.append(message.content)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def conversation_to_json(conversation: Conversation) -> dict[str, Any]:
        return {
            "export_version": EXPORT_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "conversation": conversation.to_dict(include_messages=True),
        }

    @staticmethod
    def export_all() -> dict[str, Any]:
        conversations = Conversation.query.order_by(Conversation.updated_at.desc()).all()
        return {
            "export_version": EXPORT_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "conversations": [c.to_dict(include_messages=True) for c in conversations],
            "settings": SettingsService.exportable_settings(),
        }

    @staticmethod
    def import_payload(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ServiceError("INVALID_JSON_IMPORT", "Import file must contain a JSON object.")

        version = payload.get("export_version", 1)
        try:
            version = int(version)
        except (TypeError, ValueError) as exc:
            raise ServiceError("INVALID_JSON_IMPORT", "Invalid export version.") from exc
        if version > EXPORT_VERSION:
            raise ServiceError(
                "INVALID_JSON_IMPORT",
                f"Unsupported export version {version}.",
            )

        conversations_data = payload.get("conversations")
        if conversations_data is None and "conversation" in payload:
            conversations_data = [payload["conversation"]]
        if conversations_data is None:
            raise ServiceError("INVALID_JSON_IMPORT", "No conversations found in import file.")
        if not isinstance(conversations_data, list):
            raise ServiceError("INVALID_JSON_IMPORT", "Conversations must be a list.")

        created = 0
        imported_messages = 0

        try:
            for item in conversations_data:
                if not isinstance(item, dict):
                    raise ServiceError("INVALID_JSON_IMPORT", "Each conversation must be an object.")
                title = str(item.get("title") or "Imported Chat").strip()[:120] or "Imported Chat"
                provider = str(item.get("provider") or "groq").strip()[:50] or "groq"
                model = str(item.get("model") or "").strip()[:120]
                conversation = Conversation(title=title, provider=provider, model=model)
                db.session.add(conversation)
                db.session.flush()

                messages = item.get("messages") or []
                if not isinstance(messages, list):
                    raise ServiceError("INVALID_JSON_IMPORT", "Messages must be a list.")
                for msg in messages:
                    if not isinstance(msg, dict):
                        raise ServiceError("INVALID_JSON_IMPORT", "Each message must be an object.")
                    role = str(msg.get("role") or "").strip()
                    content = str(msg.get("content") or "")
                    if role not in {"user", "assistant", "system"}:
                        raise ServiceError("INVALID_JSON_IMPORT", f"Invalid message role: {role}")
                    if not content.strip():
                        continue
                    message = Message(
                        conversation_id=conversation.id,
                        role=role,
                        content=content,
                        provider=msg.get("provider"),
                        model=msg.get("model"),
                    )
                    db.session.add(message)
                    imported_messages += 1
                created += 1

            # Optionally import non-sensitive settings without overwriting blindly:
            # only apply known exportable keys when present.
            settings_data = payload.get("settings")
            if isinstance(settings_data, dict) and settings_data:
                safe_updates = {
                    k: v
                    for k, v in settings_data.items()
                    if k in SettingsService.exportable_settings() or k in {
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
                }
                if safe_updates:
                    # Validate but do not fail the whole import if settings are odd;
                    # conversations are the primary payload.
                    try:
                        SettingsService.set_many(safe_updates)
                    except Exception:  # noqa: BLE001
                        logger.warning("Skipped settings import due to validation issues")

            db.session.commit()
        except ServiceError:
            db.session.rollback()
            raise
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            logger.exception("Import failed")
            raise ServiceError("INVALID_JSON_IMPORT", "Unable to import the provided file.") from exc

        return {
            "conversations_imported": created,
            "messages_imported": imported_messages,
        }
