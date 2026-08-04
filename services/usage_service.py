"""Aggregate and record token usage for the dashboard."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func

from extensions import db
from models.token_usage import TokenUsage
from services.model_catalog import DEFAULT_DAILY_TOKEN_LIMITS
from services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class UsageService:
    @staticmethod
    def record(
        *,
        provider: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        conversation_id: int | None = None,
    ) -> TokenUsage | None:
        prompt_tokens = int(prompt_tokens or 0)
        completion_tokens = int(completion_tokens or 0)
        total_tokens = int(total_tokens or (prompt_tokens + completion_tokens))
        if total_tokens <= 0 and prompt_tokens <= 0 and completion_tokens <= 0:
            return None
        row = TokenUsage(
            provider=(provider or "unknown").lower(),
            model=model or "unknown",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            conversation_id=conversation_id,
        )
        try:
            db.session.add(row)
            db.session.commit()
            return row
        except Exception:  # noqa: BLE001
            db.session.rollback()
            logger.exception("Failed to record token usage")
            return None

    @staticmethod
    def estimate_tokens_from_text(text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    @staticmethod
    def estimate_from_exchange(messages: list | None, completion_text: str) -> dict[str, int]:
        prompt_chars = 0
        for item in messages or []:
            content = (item or {}).get("content", "")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        prompt_chars += len(str(part.get("text") or ""))
                    elif isinstance(part, dict) and part.get("type") == "image_url":
                        prompt_chars += 3200  # rough vision cost
            else:
                prompt_chars += len(str(content or ""))
        prompt_tokens = max(1, prompt_chars // 4) if prompt_chars else 0
        completion_tokens = UsageService.estimate_tokens_from_text(completion_text or "")
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

    @staticmethod
    def record_from_provider(
        provider_obj,
        *,
        provider_id: str,
        model: str,
        conversation_id: int | None,
        messages: list | None = None,
        completion_text: str = "",
    ) -> dict[str, int]:
        usage = getattr(provider_obj, "last_usage", None)
    if (usage is not None):
            if hasattr(usage, "normalized"):
                data = usage.normalized()
            elif isinstance(usage, dict):
                data = usage
            else:
                data = {
                    "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                    "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
                }
        else:
            data = UsageService.estimate_from_exchange(messages, completion_text)
        recorded = UsageService.record(
            provider=provider_id,
            model=model,
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            conversation_id=conversation_id,
        )
        payload = {
            "prompt_tokens": int(data.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(data.get("completion_tokens", 0) or 0),
            "total_tokens": int(data.get("total_tokens", 0) or 0),
            "estimated": usage is None,
            "recorded": recorded is not None,
        }
        return payload

    @staticmethod
    def _today_start() -> datetime:
        now = datetime.now(timezone.utc)
        return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    @staticmethod
    def dashboard() -> dict:
        limits = dict(DEFAULT_DAILY_TOKEN_LIMITS)
        custom = SettingsService.get("token_limits")
        if isinstance(custom, dict):
            for key, value in custom.items():
                try:
                    limits[str(key).lower()] = int(value)
                except (TypeError, ValueError):
                    continue

        today_start = UsageService._today_start()
        today_rows = (
            db.session.query(
                TokenUsage.provider,
                TokenUsage.model,
                func.coalesce(func.sum(TokenUsage.prompt_tokens), 0),
                func.coalesce(func.sum(TokenUsage.completion_tokens), 0),
                func.coalesce(func.sum(TokenUsage.total_tokens), 0),
            )
            .filter(TokenUsage.created_at >= today_start)
            .group_by(TokenUsage.provider, TokenUsage.model)
            .all()
        )

        all_rows = (
            db.session.query(
                TokenUsage.provider,
                TokenUsage.model,
                func.coalesce(func.sum(TokenUsage.prompt_tokens), 0),
                func.coalesce(func.sum(TokenUsage.completion_tokens), 0),
                func.coalesce(func.sum(TokenUsage.total_tokens), 0),
            )
            .group_by(TokenUsage.provider, TokenUsage.model)
            .all()
        )

        def pack(rows):
            items = []
            for provider, model, prompt, completion, total in rows:
                limit = int(limits.get(provider, 0) or 0)
                used = int(total or 0)
                remaining = max(0, limit - used) if limit > 0 else None
                items.append(
                    {
                        "provider": provider,
                        "model": model,
                        "prompt_tokens": int(prompt or 0),
                        "completion_tokens": int(completion or 0),
                        "total_tokens": used,
                        "limit": limit or None,
                        "remaining": remaining,
                    }
                )
            items.sort(key=lambda i: i["total_tokens"], reverse=True)
            return items

        by_provider_today = (
            db.session.query(
                TokenUsage.provider,
                func.coalesce(func.sum(TokenUsage.total_tokens), 0),
            )
            .filter(TokenUsage.created_at >= today_start)
            .group_by(TokenUsage.provider)
            .all()
        )
        provider_summary = []
        for provider, used in by_provider_today:
            limit = int(limits.get(provider, 0) or 0)
            used_i = int(used or 0)
            provider_summary.append(
                {
                    "provider": provider,
                    "total_tokens": used_i,
                    "limit": limit or None,
                    "remaining": max(0, limit - used_i) if limit else None,
                }
            )
        provider_summary.sort(key=lambda i: i["total_tokens"], reverse=True)

        return {
            "today": {
                "by_model": pack(today_rows),
                "by_provider": provider_summary,
            },
            "all_time": {
                "by_model": pack(all_rows),
            },
            "limits": limits,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
