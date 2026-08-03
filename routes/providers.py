"""Provider listing, models, and connection test routes."""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, request

from routes.helpers import error_response, success_response
from services.base_provider import ProviderError
from services.model_catalog import (
    PROVIDER_DEFAULT_MODELS,
    get_context_window,
    get_max_output_tokens,
    max_message_characters_for_model,
)
from services.provider_registry import get_provider, get_provider_status, list_providers
from services.settings_service import SettingsService

logger = logging.getLogger(__name__)

providers_bp = Blueprint("providers", __name__, url_prefix="/api")


@providers_bp.get("/providers")
def providers():
    return success_response(list_providers())


@providers_bp.get("/providers/status")
def provider_status():
    provider_id = request.args.get("provider", "groq")
    return success_response(get_provider_status(provider_id))


def _serialize_models(provider_id: str, models) -> list[dict]:
    payload = []
    for model in models:
        context_window = getattr(model, "context_window", None) or get_context_window(
            provider_id, model.id
        )
        max_out = getattr(model, "max_output_tokens", None) or get_max_output_tokens(
            provider_id, model.id
        )
        payload.append(
            {
                "id": model.id,
                "name": model.name,
                "owned_by": getattr(model, "owned_by", None),
                "context_window": context_window,
                "max_output_tokens": max_out,
                "supports_vision": bool(getattr(model, "supports_vision", False)),
                "max_message_characters": max_message_characters_for_model(provider_id, model.id),
            }
        )
    return payload


@providers_bp.get("/providers/<provider_id>/models")
def provider_models(provider_id: str):
    provider_id = (provider_id or "").lower()
    try:
        provider = get_provider(provider_id)
        fallback = current_app.config.get(
            f"{provider_id.upper()}_DEFAULT_MODEL",
            PROVIDER_DEFAULT_MODELS.get(provider_id, ""),
        )
        if not provider.is_configured():
            return success_response(
                {
                    "provider": provider_id,
                    "models": _serialize_models(
                        provider_id,
                        [
                            type("M", (), {"id": fallback, "name": fallback, "owned_by": None, "context_window": None, "max_output_tokens": None, "supports_vision": False})()
                        ],
                    )
                    if fallback
                    else [],
                    "fallback": True,
                    "configured": False,
                    "fallback_model": fallback,
                }
            )

        models = provider.list_models()
        settings = SettingsService.get_all()
        saved_model = settings.get("default_model")
        model_ids = {m.id for m in models}
        model_fallback_used = bool(
            settings.get("default_provider") == provider_id
            and saved_model
            and saved_model not in model_ids
        )
        return success_response(
            {
                "provider": provider_id,
                "models": _serialize_models(provider_id, models),
                "fallback": False,
                "configured": True,
                "saved_model_unavailable": model_fallback_used,
                "fallback_model": fallback,
            }
        )
    except ProviderError as exc:
        return error_response(exc.code, exc.message, 502)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to list %s models", provider_id)
        fallback = PROVIDER_DEFAULT_MODELS.get(provider_id)
        return success_response(
            {
                "provider": provider_id,
                "models": [{"id": fallback, "name": fallback}] if fallback else [],
                "fallback": True,
                "configured": False,
                "fallback_model": fallback,
            }
        )


# Backward-compatible alias used by older frontend code.
@providers_bp.get("/providers/groq/models")
def groq_models_alias():
    return provider_models("groq")


@providers_bp.post("/providers/<provider_id>/test")
def test_provider(provider_id: str):
    provider_id = (provider_id or "").lower()
    try:
        provider = get_provider(provider_id)
        result = provider.test_connection()
        return success_response(
            {
                **result,
                "message": f"Connected to {result.get('provider', provider_id)} successfully.",
            }
        )
    except ProviderError as exc:
        return error_response(exc.code, exc.message, 502)
    except Exception:  # noqa: BLE001
        logger.exception("%s connection test failed", provider_id)
        return error_response(
            "NETWORK_UNAVAILABLE",
            f"Unable to verify the {provider_id} connection.",
            502,
        )


@providers_bp.post("/providers/groq/test")
def test_groq_alias():
    return test_provider("groq")
