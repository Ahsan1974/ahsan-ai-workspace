"""Message send / regenerate / delete API routes."""

from __future__ import annotations

import json
import logging
from typing import Any, Generator

from flask import Blueprint, Response, current_app, request, stream_with_context

from routes.helpers import error_response, success_response
from services.attachment_service import (
    AttachmentError,
    AttachmentBundle,
    VISION_FALLBACKS,
    attachment_system_hint,
    build_provider_user_content,
    build_stored_content,
    process_uploads,
    resolve_model_for_attachments,
)
from services.base_provider import ProviderError
from services.conversation_service import ConversationService, ServiceError
from services.model_catalog import (
    get_max_output_tokens,
    max_message_characters_for_model,
    trim_history_to_context,
)
from services.provider_registry import get_provider
from services.settings_service import SettingsService
from services.usage_service import UsageService

logger = logging.getLogger(__name__)

messages_bp = Blueprint("messages", __name__, url_prefix="/api")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _parse_send_request() -> tuple[str, str, str, bool, list]:
    """Parse JSON or multipart message requests."""
    files = []
    if request.files:
        files = request.files.getlist("files") or request.files.getlist("files[]")

    if files or request.form:
        content = request.form.get("content", "")
        provider = request.form.get("provider", "")
        model = request.form.get("model", "")
        stream_raw = request.form.get("stream", "true")
        stream = str(stream_raw).lower() in {"1", "true", "yes", "on"}
        return content, provider, model, stream, files

    payload = request.get_json(silent=True) or {}
    return (
        payload.get("content", ""),
        payload.get("provider", ""),
        payload.get("model", ""),
        bool(payload.get("stream", True)),
        [],
    )


def _prepare_user_payload(raw_content: str, files: list, provider_id: str, model: str) -> tuple[str, Any, AttachmentBundle, str | None]:
    """Return stored_text, provider_content, bundle, error_response_or_none."""
    user_text = (raw_content or "").strip()
    max_chars = max_message_characters_for_model(provider_id, model)
    configured_cap = int(current_app.config.get("MAX_MESSAGE_CHARACTERS", 20000))
    max_chars = max(max_chars, configured_cap)
    if len(user_text) > max_chars:
        return "", "", AttachmentBundle(), error_response(
            "INPUT_TOO_LONG",
            f"Message exceeds the maximum length for this model ({max_chars} characters).",
        )

    try:
        bundle = process_uploads(files) if files else AttachmentBundle()
    except AttachmentError as exc:
        return "", "", AttachmentBundle(), error_response(exc.code, exc.message, 400)

    if not user_text and not bundle.attachments:
        return "", "", bundle, error_response(
            "INVALID_SETTINGS",
            "Type a message or attach a file before sending.",
        )

    try:
        stored = build_stored_content(user_text, bundle)
        provider_content = build_provider_user_content(user_text, bundle)
    except AttachmentError as exc:
        return "", "", bundle, error_response(exc.code, exc.message, 400)

    return stored, provider_content, bundle, None


def _history_with_provider_content(
    history: list[dict[str, str]],
    provider_content: Any,
) -> list[dict[str, Any]]:
    """Replace the latest user turn with provider-ready content (may be multimodal)."""
    prepared: list[dict[str, Any]] = [dict(item) for item in history]
    if not prepared:
        return [{"role": "user", "content": provider_content}]
    # Find last user message and override content for this request only.
    for index in range(len(prepared) - 1, -1, -1):
        if prepared[index].get("role") == "user":
            prepared[index]["content"] = provider_content
            break
    return prepared


@messages_bp.post("/conversations/<int:conversation_id>/messages")
def send_message(conversation_id: int):
    raw_content, provider_in, model_in, stream, files = _parse_send_request()
    # Hosted serverless often breaks SSE; prefer reliable JSON completions there.
    if not current_app.config.get("PREFER_STREAM", True):
        stream = False

    settings = SettingsService.get_all()
    try:
        conversation = ConversationService.get_conversation(conversation_id)
    except ServiceError as exc:
        return error_response(exc.code, exc.message, exc.status_code)

    # Prefer this chat's provider/model so other chats never bleed in.
    provider_id = (
        provider_in
        or conversation.provider
        or settings.get("default_provider")
        or "groq"
    )
    requested_model = (
        model_in
        or conversation.model
        or settings.get("default_model")
        or ""
    )

    stored, provider_content, bundle, early_error = _prepare_user_payload(
        raw_content, files, provider_id, requested_model
    )
    if early_error is not None:
        return early_error

    vision_fallback = VISION_FALLBACKS.get(provider_id)
    if provider_id == "groq":
        vision_fallback = current_app.config.get("GROQ_VISION_MODEL", vision_fallback)
    try:
        model, switched_vision = resolve_model_for_attachments(
            requested_model,
            bundle,
            provider_id,
            vision_fallback=vision_fallback,
        )
    except AttachmentError as exc:
        return error_response(exc.code, exc.message, 400)

    if bundle.has_images and provider_id == "gemini":
        model = model or current_app.config.get("GEMINI_DEFAULT_MODEL", "gemini-2.0-flash")

    try:
        user_message = ConversationService.add_message(
            conversation_id=conversation.id,
            role="user",
            content=stored,
            provider=provider_id,
            model=model,
            auto_title=True,
        )
        conversation = ConversationService.get_conversation(conversation.id)

        provider = get_provider(provider_id)
        context_limit = int(settings.get("context_messages") or current_app.config["MAX_CONTEXT_MESSAGES"])
        # Only messages from this conversation_id are included.
        history = ConversationService.get_context_messages(conversation.id, context_limit)
        provider_history = _history_with_provider_content(history, provider_content)
        temperature = float(settings.get("temperature", 0.7))
        max_tokens = int(settings.get("max_tokens", 4096))
        model_max_out = get_max_output_tokens(provider_id, model, max_tokens)
        max_tokens = min(max_tokens, model_max_out)
        system_prompt = str(settings.get("system_prompt") or "")
        attach_hint = attachment_system_hint(bundle)
        if attach_hint:
            system_prompt = f"{system_prompt}\n\n{attach_hint}".strip()
        provider_history = trim_history_to_context(
            provider_history,
            provider=provider_id,
            model=model,
            system_prompt=system_prompt,
            max_output_tokens=max_tokens,
        )

        attachment_meta = [
            {
                "filename": item.filename,
                "kind": item.kind,
                "extension": item.extension,
            }
            for item in bundle.attachments
        ]

        if not stream:
            assistant_text = provider.generate_response(
                messages=provider_history,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
            UsageService.record_from_provider(
                provider,
                provider_id=provider_id,
                model=model,
                conversation_id=conversation.id,
            )
            assistant_message = ConversationService.add_message(
                conversation_id=conversation.id,
                role="assistant",
                content=assistant_text,
                provider=provider_id,
                model=model,
            )
            return success_response(
                {
                    "user_message": user_message.to_dict(),
                    "assistant_message": assistant_message.to_dict(),
                    "conversation": conversation.to_dict(),
                    "model_switched_for_vision": switched_vision,
                    "model": model,
                    "attachments": attachment_meta,
                }
            )

        @stream_with_context
        def event_stream() -> Generator[str, None, None]:
            yield _sse(
                "meta",
                {
                    "user_message": user_message.to_dict(),
                    "conversation": conversation.to_dict(),
                    "provider": provider_id,
                    "model": model,
                    "model_switched_for_vision": switched_vision,
                    "attachments": attachment_meta,
                    "context_window": None,
                },
            )
            collected: list[str] = []
            try:
                for chunk in provider.generate_stream(
                    messages=provider_history,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                ):
                    collected.append(chunk)
                    yield _sse("token", {"content": chunk})

                full_text = "".join(collected).strip()
                if not full_text:
                    yield _sse(
                        "error",
                        {
                            "code": "EMPTY_RESPONSE",
                            "message": "The provider returned an empty response. Please try again.",
                        },
                    )
                    return

                UsageService.record_from_provider(
                    provider,
                    provider_id=provider_id,
                    model=model,
                    conversation_id=conversation.id,
                )
                assistant_message = ConversationService.add_message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=full_text,
                    provider=provider_id,
                    model=model,
                )
                refreshed = ConversationService.get_conversation(conversation.id)
                yield _sse(
                    "done",
                    {
                        "assistant_message": assistant_message.to_dict(),
                        "conversation": refreshed.to_dict(),
                    },
                )
            except ProviderError as exc:
                logger.warning("Provider error during stream: %s", exc.code)
                yield _sse("error", {"code": exc.code, "message": exc.message})
            except Exception:  # noqa: BLE001
                logger.exception("Unexpected streaming failure")
                yield _sse(
                    "error",
                    {
                        "code": "INTERNAL_ERROR",
                        "message": "An unexpected error occurred while generating a response.",
                    },
                )

        return Response(
            event_stream(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except ServiceError as exc:
        return error_response(exc.code, exc.message, exc.status_code)
    except ProviderError as exc:
        return error_response(exc.code, exc.message, 502)


@messages_bp.delete("/messages/<int:message_id>")
def delete_message(message_id: int):
    try:
        conversation = ConversationService.delete_message(message_id)
        return success_response({"deleted": True, "conversation": conversation.to_dict()})
    except ServiceError as exc:
        return error_response(exc.code, exc.message, exc.status_code)


@messages_bp.post("/messages/<int:message_id>/regenerate")
def regenerate_message(message_id: int):
    """Regenerate the latest assistant message (or a selected assistant message)."""
    payload = request.get_json(silent=True) or {}
    stream = bool(payload.get("stream", True))

    try:
        message = ConversationService.get_message(message_id)
        if message.role != "assistant":
            return error_response("INVALID_SETTINGS", "Only assistant messages can be regenerated.")

        conversation = message.conversation
        settings = SettingsService.get_all()
        provider_id = payload.get("provider") or conversation.provider or settings.get("default_provider")
        model = payload.get("model") or conversation.model or settings.get("default_model")

        ConversationService.delete_message(message.id)

        provider = get_provider(provider_id)
        context_limit = int(settings.get("context_messages") or current_app.config["MAX_CONTEXT_MESSAGES"])
        history = ConversationService.get_context_messages(conversation.id, context_limit)
        temperature = float(settings.get("temperature", 0.7))
        max_tokens = int(settings.get("max_tokens", 4096))
        system_prompt = str(settings.get("system_prompt") or "")

        if not history or history[-1]["role"] != "user":
            return error_response(
                "INVALID_SETTINGS",
                "Cannot regenerate without a preceding user message.",
            )

        if not stream:
            assistant_text = provider.generate_response(
                messages=history,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
            assistant_message = ConversationService.add_message(
                conversation_id=conversation.id,
                role="assistant",
                content=assistant_text,
                provider=provider_id,
                model=model,
            )
            refreshed = ConversationService.get_conversation(conversation.id)
            return success_response(
                {
                    "assistant_message": assistant_message.to_dict(),
                    "conversation": refreshed.to_dict(),
                }
            )

        @stream_with_context
        def event_stream() -> Generator[str, None, None]:
            yield _sse(
                "meta",
                {
                    "conversation": conversation.to_dict(),
                    "provider": provider_id,
                    "model": model,
                    "regenerated": True,
                },
            )
            collected: list[str] = []
            try:
                for chunk in provider.generate_stream(
                    messages=history,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                ):
                    collected.append(chunk)
                    yield _sse("token", {"content": chunk})

                full_text = "".join(collected).strip()
                if not full_text:
                    yield _sse(
                        "error",
                        {
                            "code": "EMPTY_RESPONSE",
                            "message": "The provider returned an empty response. Please try again.",
                        },
                    )
                    return

                assistant_message = ConversationService.add_message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=full_text,
                    provider=provider_id,
                    model=model,
                )
                refreshed = ConversationService.get_conversation(conversation.id)
                yield _sse(
                    "done",
                    {
                        "assistant_message": assistant_message.to_dict(),
                        "conversation": refreshed.to_dict(),
                    },
                )
            except ProviderError as exc:
                logger.warning("Provider error during regenerate: %s", exc.code)
                yield _sse("error", {"code": exc.code, "message": exc.message})
            except Exception:  # noqa: BLE001
                logger.exception("Unexpected regenerate failure")
                yield _sse(
                    "error",
                    {
                        "code": "INTERNAL_ERROR",
                        "message": "An unexpected error occurred while regenerating.",
                    },
                )

        return Response(
            event_stream(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except ServiceError as exc:
        return error_response(exc.code, exc.message, exc.status_code)
    except ProviderError as exc:
        return error_response(exc.code, exc.message, 502)
