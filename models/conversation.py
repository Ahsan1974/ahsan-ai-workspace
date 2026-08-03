"""Conversation database model."""

from __future__ import annotations

from datetime import datetime, timezone

from extensions import db


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class Conversation(db.Model):
    """A saved chat thread."""

    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False, default="New Chat")
    provider = db.Column(db.String(50), nullable=False, default="groq")
    model = db.Column(db.String(120), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    messages = db.relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
        lazy="joined",
    )

    def touch(self) -> None:
        """Bump the updated_at timestamp."""
        self.updated_at = utcnow()

    def to_dict(self, include_messages: bool = False, storage_bytes: int | None = None) -> dict:
        """Serialize the conversation for JSON responses."""
        message_count = len(self.messages) if self.messages is not None else 0
        if storage_bytes is None and self.messages is not None:
            storage_bytes = sum(
                len((message.content or "").encode("utf-8")) for message in self.messages
            )
        data = {
            "id": self.id,
            "title": self.title,
            "provider": self.provider,
            "model": self.model,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "message_count": message_count,
            "storage_bytes": int(storage_bytes or 0),
        }
        if include_messages:
            data["messages"] = [message.to_dict() for message in self.messages]
        return data
