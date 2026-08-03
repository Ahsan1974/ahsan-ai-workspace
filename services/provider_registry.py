"""Registry of available LLM providers."""

from __future__ import annotations

from flask import current_app

from services.base_provider import BaseLLMProvider, MissingAPIKeyError
from services.cohere_provider import CohereProvider
from services.gemini_provider import GeminiProvider
from services.groq_provider import GroqProvider
from services.model_catalog import PROVIDER_DEFAULT_MODELS
from services.openai_compatible_provider import (
    create_mistral_provider,
    create_openrouter_provider,
    create_sambanova_provider,
)

PROVIDER_ORDER = ["groq", "sambanova", "gemini", "openrouter", "mistral", "cohere"]

PROVIDER_DISPLAY = {
    "groq": "Groq (GroqCloud)",
    "sambanova": "SambaNova",
    "gemini": "Gemini",
    "openrouter": "OpenRouter (xAI Grok)",
    "mistral": "Mistral",
    "cohere": "Cohere",
}


def get_provider(provider_id: str | None = None) -> BaseLLMProvider:
    """Return a provider instance by id."""
    selected = (provider_id or current_app.config.get("DEFAULT_PROVIDER") or "groq").lower().strip()

    if selected == "groq":
        return GroqProvider(
            api_key=current_app.config.get("GROQ_API_KEY", ""),
            default_model=current_app.config.get(
                "GROQ_DEFAULT_MODEL",
                PROVIDER_DEFAULT_MODELS["groq"],
            ),
        )
    if selected == "sambanova":
        return create_sambanova_provider(
            current_app.config.get("SAMBANOVA_API_KEY", ""),
            current_app.config.get("SAMBANOVA_DEFAULT_MODEL", PROVIDER_DEFAULT_MODELS["sambanova"]),
        )
    if selected == "gemini":
        return GeminiProvider(
            api_key=current_app.config.get("GEMINI_API_KEY", ""),
            default_model=current_app.config.get(
                "GEMINI_DEFAULT_MODEL",
                PROVIDER_DEFAULT_MODELS["gemini"],
            ),
        )
    if selected == "openrouter":
        return create_openrouter_provider(
            current_app.config.get("OPENROUTER_API_KEY", ""),
            current_app.config.get("OPENROUTER_DEFAULT_MODEL", PROVIDER_DEFAULT_MODELS["openrouter"]),
        )
    if selected == "mistral":
        return create_mistral_provider(
            current_app.config.get("MISTRAL_API_KEY", ""),
            current_app.config.get("MISTRAL_DEFAULT_MODEL", PROVIDER_DEFAULT_MODELS["mistral"]),
        )
    if selected == "cohere":
        return CohereProvider(
            api_key=current_app.config.get("COHERE_API_KEY", ""),
            default_model=current_app.config.get(
                "COHERE_DEFAULT_MODEL",
                PROVIDER_DEFAULT_MODELS["cohere"],
            ),
        )

    raise MissingAPIKeyError(selected)


def list_providers() -> list[dict]:
    """Return provider metadata for the UI."""
    providers: list[dict] = []
    for provider_id in PROVIDER_ORDER:
        try:
            provider = get_provider(provider_id)
            configured = provider.is_configured()
            providers.append(
                {
                    "id": provider_id,
                    "name": PROVIDER_DISPLAY.get(provider_id, provider_id.title()),
                    "configured": configured,
                    "enabled": configured,
                    "status": "Ready" if configured else "API key missing",
                    "default_model": PROVIDER_DEFAULT_MODELS.get(provider_id),
                }
            )
        except Exception:  # noqa: BLE001
            providers.append(
                {
                    "id": provider_id,
                    "name": PROVIDER_DISPLAY.get(provider_id, provider_id.title()),
                    "configured": False,
                    "enabled": False,
                    "status": "Unavailable",
                    "default_model": PROVIDER_DEFAULT_MODELS.get(provider_id),
                }
            )
    return providers


def get_provider_status(provider_id: str = "groq") -> dict:
    """Return a safe status payload that never includes secrets."""
    provider_id = (provider_id or "groq").lower()
    try:
        provider = get_provider(provider_id)
    except MissingAPIKeyError:
        return {"provider": provider_id, "configured": False, "available": False}
    configured = provider.is_configured()
    return {
        "provider": provider_id,
        "configured": configured,
        "available": configured,
    }
