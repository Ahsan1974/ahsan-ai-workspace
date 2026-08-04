"""Shared API-key validation helpers for all providers."""

from __future__ import annotations

PLACEHOLDER_KEYS = {
    "",
    "changeme",
    "your_api_key_here",
    "put_your_key_here",
    "put_your_new_groq_api_key_here",
    "put_your_sambanova_api_key_here",
    "put_your_gemini_api_key_here",
    "put_your_openrouter_api_key_here",
    "put_your_mistral_api_key_here",
    "put_your_cohere_api_key_here",
    "replace-with-a-random-local-secret",
}


def key_looks_real(api_key: str | None) -> bool:
    """Return True when the key is present and not an example placeholder."""
    cleaned = (api_key or "").strip()
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if lowered in PLACEHOLDER_KEYS:
        return False
    if lowered.startswith("put_your_"):
        return False
    if "your_" in lowered and "key" in lowered and len(cleaned) < 40:
        return False
    return True
