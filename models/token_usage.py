"""Token usage database model."""

from __future__ import annotations

from datetime import datetime, timezone

from extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TokenUsage(db.Model):
    """One generation request's token accounting."""

    __tablename__ = "token_usage"

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50), nullable=False, index=True)
    model = db.Column(db.String(160), nullable=False, index=True)
    prompt_tokens = db.Column(db.Integer, nullable=False, default=0)
    completion_tokens = db.Column(db.Integer, nullable=False, default=0)
    total_tokens = db.Column(db.Integer, nullable=False, default=0)
    conversation_id = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "provider": self.provider,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "conversation_id": self.conversation_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
