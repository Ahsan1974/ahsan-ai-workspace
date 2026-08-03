"""Conversation and message domain logic."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models.conversation import Conversation
from models.message import Message

logger = logging.getLogger(__name__)

_ATTACHED_BLOCK_RE = re.compile(
    r"(--- Attached (?:PDF|file):[^\n]*---)\n([\s\S]*?)(?=\n\n--- Attached |\Z)",
)


class ServiceError(Exception):
    """Domain-level error with a stable code."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def make_title_from_message(content: str, max_length: int = 50) -> str:
    """Create a short conversation title from the first user message."""
    cleaned = re.sub(r"\s+", " ", (content or "").strip())
    if not cleaned:
        return "New Chat"
    if len(cleaned) <= max_length:
        return cleaned
    truncated = cleaned[: max_length - 1].rstrip()
    return f"{truncated}…"


class ConversationService:
    """CRUD helpers for conversations and messages."""

    @staticmethod
    def list_conversations(search: str | None = None) -> list[Conversation]:
        query = Conversation.query
        if search:
            term = f"%{search.strip()}%"
            query = query.filter(Conversation.title.ilike(term))
        return query.order_by(Conversation.updated_at.desc()).all()

    @staticmethod
    def get_conversation(conversation_id: int) -> Conversation:
        conversation = db.session.get(Conversation, conversation_id)
        if conversation is None:
            raise ServiceError("CONVERSATION_NOT_FOUND", "Conversation not found.", 404)
        return conversation

    @staticmethod
    def create_conversation(provider: str, model: str, title: str = "New Chat") -> Conversation:
        conversation = Conversation(
            title=(title or "New Chat").strip()[:120] or "New Chat",
            provider=provider or "groq",
            model=model or "",
        )
        try:
            db.session.add(conversation)
            db.session.commit()
            return conversation
        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.exception("Database error creating conversation")
            raise ServiceError("DATABASE_ERROR", "Unable to create conversation.", 500) from exc

    @staticmethod
    def update_conversation(conversation_id: int, **fields: Any) -> Conversation:
        conversation = ConversationService.get_conversation(conversation_id)
        if "title" in fields and fields["title"] is not None:
            title = str(fields["title"]).strip()
            if not title:
                raise ServiceError("INVALID_SETTINGS", "Conversation title cannot be empty.")
            conversation.title = title[:120]
        if "provider" in fields and fields["provider"]:
            conversation.provider = str(fields["provider"]).strip()[:50]
        if "model" in fields and fields["model"] is not None:
            conversation.model = str(fields["model"]).strip()[:120]
        conversation.touch()
        try:
            db.session.commit()
            return conversation
        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.exception("Database error updating conversation")
            raise ServiceError("DATABASE_ERROR", "Unable to update conversation.", 500) from exc

    @staticmethod
    def delete_conversation(conversation_id: int) -> None:
        from models.token_usage import TokenUsage

        conversation = ConversationService.get_conversation(conversation_id)
        try:
            TokenUsage.query.filter_by(conversation_id=conversation_id).delete()
            db.session.delete(conversation)
            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.exception("Database error deleting conversation")
            raise ServiceError("DATABASE_ERROR", "Unable to delete conversation.", 500) from exc

    @staticmethod
    def clear_all_conversations() -> int:
        try:
            count = Conversation.query.count()
            Message.query.delete()
            Conversation.query.delete()
            db.session.commit()
            return count
        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.exception("Database error clearing conversations")
            raise ServiceError("DATABASE_ERROR", "Unable to clear conversations.", 500) from exc

    @staticmethod
    def add_message(
        conversation_id: int,
        role: str,
        content: str,
        provider: str | None = None,
        model: str | None = None,
        auto_title: bool = False,
    ) -> Message:
        if role not in {"user", "assistant", "system"}:
            raise ServiceError("INVALID_SETTINGS", "Invalid message role.")
        text = (content or "").strip()
        if not text:
            raise ServiceError("INVALID_SETTINGS", "Message content cannot be empty.")

        conversation = ConversationService.get_conversation(conversation_id)
        message = Message(
            conversation_id=conversation.id,
            role=role,
            content=text,
            provider=provider,
            model=model,
        )
        conversation.touch()
        if provider:
            conversation.provider = provider
        if model:
            conversation.model = model
        if auto_title and role == "user" and conversation.title in {"New Chat", "New chat", ""}:
            conversation.title = make_title_from_message(text)

        try:
            db.session.add(message)
            db.session.commit()
            return message
        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.exception("Database error saving message")
            raise ServiceError("DATABASE_ERROR", "Unable to save message.", 500) from exc

    @staticmethod
    def get_message(message_id: int) -> Message:
        message = db.session.get(Message, message_id)
        if message is None:
            raise ServiceError("MESSAGE_NOT_FOUND", "Message not found.", 404)
        return message

    @staticmethod
    def delete_message(message_id: int) -> Conversation:
        message = ConversationService.get_message(message_id)
        conversation = message.conversation
        try:
            db.session.delete(message)
            conversation.touch()
            db.session.commit()
            return conversation
        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.exception("Database error deleting message")
            raise ServiceError("DATABASE_ERROR", "Unable to delete message.", 500) from exc

    @staticmethod
    def _compress_attachment_content(content: str) -> str:
        """Shrink old PDF/code attachments so earlier turns still fit in context."""
        text = content or ""
        if "--- Attached " not in text:
            return text

        def _stub(match: re.Match[str]) -> str:
            header = match.group(1)
            body = match.group(2) or ""
            preview = re.sub(r"\s+", " ", body.strip())[:240]
            return f"{header}\n[Earlier attachment summarized for context] {preview}…"

        compressed = _ATTACHED_BLOCK_RE.sub(_stub, text)
        if len(compressed) > 2500:
            compressed = compressed[:2500] + "…"
        return compressed

    @staticmethod
    def get_context_messages(
        conversation_id: int,
        limit: int,
        *,
        keep_full_tail: int = 4,
    ) -> list[dict[str, str]]:
        """Return messages for this conversation only (never other chats)."""
        conversation = ConversationService.get_conversation(conversation_id)
        messages = (
            Message.query.filter_by(conversation_id=conversation.id)
            .order_by(Message.created_at.asc())
            .all()
        )
        # Keep only user/assistant turns for the model context window.
        history = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in {"user", "assistant"}
        ]
        if limit > 0 and len(history) > limit:
            history = history[-limit:]

        # Compress bulky attachments in older turns so more of this chat fits.
        if keep_full_tail > 0 and len(history) > keep_full_tail:
            cutoff = len(history) - keep_full_tail
            for index in range(cutoff):
                if history[index]["role"] == "user":
                    history[index]["content"] = ConversationService._compress_attachment_content(
                        history[index]["content"]
                    )
        return history

    @staticmethod
    def get_storage_map() -> dict[int, int]:
        """Return approximate stored bytes per conversation (UTF-8 message bytes)."""
        # Prefer a simple Python sum — reliable across SQLite builds/drivers.
        sizes: dict[int, int] = {}
        rows = db.session.query(Message.conversation_id, Message.content).all()
        for conversation_id, content in rows:
            cid = int(conversation_id)
            sizes[cid] = sizes.get(cid, 0) + len((content or "").encode("utf-8"))
        return sizes

    @staticmethod
    def storage_bytes_for(conversation_id: int) -> int:
        total = 0
        rows = (
            Message.query.filter_by(conversation_id=conversation_id)
            .with_entities(Message.content)
            .all()
        )
        for (content,) in rows:
            total += len((content or "").encode("utf-8"))
        return total

    @staticmethod
    def get_database_size_bytes() -> int:
        uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if not uri.startswith("sqlite:///"):
            return 0
        path = uri.replace("sqlite:///", "", 1)
        # SQLAlchemy may use forward slashes on Windows paths.
        path = os.path.normpath(path)
        try:
            return int(os.path.getsize(path))
        except OSError:
            return 0

    @staticmethod
    def search_conversations(query: str) -> list[Conversation]:
        return ConversationService.list_conversations(search=query)