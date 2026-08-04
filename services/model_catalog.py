"""Static model catalogs, context windows, and soft token limits."""

from __future__ import annotations

from typing import Any

# Soft daily token budgets for the dashboard (personal free-tier style estimates).
# These are display limits, not hard API enforcement.
DEFAULT_DAILY_TOKEN_LIMITS: dict[str, int] = {
    "groq": 200_000,
    "sambanova": 200_000,
    "gemini": 1_000_000,
    "openrouter": 100_000,
    "mistral": 200_000,
    "cohere": 100_000,
}

# Fallback catalogs when live model listing fails.
PROVIDER_MODEL_CATALOG: dict[str, list[dict[str, Any]]] = {
    "groq": [
        {"id": "llama-3.3-70b-versatile", "name": "llama-3.3-70b-versatile", "context_window": 131072, "max_output_tokens": 32768},
        {"id": "llama-3.1-8b-instant", "name": "llama-3.1-8b-instant", "context_window": 131072, "max_output_tokens": 131072},
        {"id": "qwen/qwen3.6-27b", "name": "qwen/qwen3.6-27b", "context_window": 131072, "max_output_tokens": 40960, "supports_vision": True},
        {"id": "openai/gpt-oss-120b", "name": "openai/gpt-oss-120b", "context_window": 131072, "max_output_tokens": 65536},
        {"id": "openai/gpt-oss-20b", "name": "openai/gpt-oss-20b", "context_window": 131072, "max_output_tokens": 65536},
    ],
    "sambanova": [
        {"id": "Meta-Llama-3.3-70B-Instruct", "name": "Meta-Llama-3.3-70B-Instruct", "context_window": 131072, "max_output_tokens": 8192},
        {"id": "Meta-Llama-3.1-8B-Instruct", "name": "Meta-Llama-3.1-8B-Instruct", "context_window": 131072, "max_output_tokens": 8192},
        {"id": "DeepSeek-R1-Distill-Llama-70B", "name": "DeepSeek-R1-Distill-Llama-70B", "context_window": 131072, "max_output_tokens": 8192},
        {"id": "Qwen3-32B", "name": "Qwen3-32B", "context_window": 8192, "max_output_tokens": 8192},
    ],
    "gemini": [
        {"id": "gemini-2.0-flash", "name": "gemini-2.0-flash", "context_window": 1048576, "max_output_tokens": 8192, "supports_vision": True},
        {"id": "gemini-2.0-flash-lite", "name": "gemini-2.0-flash-lite", "context_window": 1048576, "max_output_tokens": 8192, "supports_vision": True},
        {"id": "gemini-2.5-flash", "name": "gemini-2.5-flash", "context_window": 1048576, "max_output_tokens": 8192, "supports_vision": True},
        {"id": "gemini-2.5-pro", "name": "gemini-2.5-pro", "context_window": 1048576, "max_output_tokens": 8192, "supports_vision": True},
        {"id": "gemini-1.5-flash", "name": "gemini-1.5-flash", "context_window": 1048576, "max_output_tokens": 8192, "supports_vision": True},
        {"id": "gemini-1.5-pro", "name": "gemini-1.5-pro", "context_window": 2097152, "max_output_tokens": 8192, "supports_vision": True},
    ],
    "openrouter": [
        {"id": "x-ai/grok-4.5", "name": "x-ai/grok-4.5 (xAI Grok)", "context_window": 256000, "max_output_tokens": 16384, "supports_vision": True},
        {"id": "x-ai/grok-4.3", "name": "x-ai/grok-4.3 (xAI Grok)", "context_window": 256000, "max_output_tokens": 16384, "supports_vision": True},
        {"id": "x-ai/grok-4.20", "name": "x-ai/grok-4.20 (xAI Grok)", "context_window": 256000, "max_output_tokens": 16384, "supports_vision": True},
        {"id": "openai/gpt-4o-mini", "name": "openai/gpt-4o-mini (vision)", "context_window": 128000, "max_output_tokens": 16384, "supports_vision": True},
        {"id": "google/gemini-2.0-flash-001", "name": "google/gemini-2.0-flash-001 (PDF/vision)", "context_window": 1048576, "max_output_tokens": 8192, "supports_vision": True},
        {"id": "qwen/qwen-2.5-72b-instruct", "name": "qwen/qwen-2.5-72b-instruct (code)", "context_window": 131072, "max_output_tokens": 16384},
        {"id": "meta-llama/llama-3.3-70b-instruct", "name": "meta-llama/llama-3.3-70b-instruct", "context_window": 131072, "max_output_tokens": 16384},
        {"id": "mistralai/mistral-small-3.1-24b-instruct", "name": "mistralai/mistral-small-3.1-24b-instruct", "context_window": 128000, "max_output_tokens": 16384},
    ],
    "mistral": [
        {"id": "codestral-latest", "name": "codestral-latest (Java/code)", "context_window": 256000, "max_output_tokens": 16384},
        {"id": "mistral-small-latest", "name": "mistral-small-latest", "context_window": 128000, "max_output_tokens": 16384, "supports_vision": True},
        {"id": "mistral-large-latest", "name": "mistral-large-latest", "context_window": 128000, "max_output_tokens": 16384},
        {"id": "open-mistral-nemo", "name": "open-mistral-nemo", "context_window": 128000, "max_output_tokens": 16384},
    ],
    "cohere": [
        {"id": "command-r-plus-08-2024", "name": "command-r-plus-08-2024", "context_window": 128000, "max_output_tokens": 4096},
        {"id": "command-r-08-2024", "name": "command-r-08-2024", "context_window": 128000, "max_output_tokens": 4096},
        {"id": "command-a-03-2025", "name": "command-a-03-2025", "context_window": 256000, "max_output_tokens": 8192},
    ],
}

PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "groq": "llama-3.3-70b-versatile",
    "sambanova": "Meta-Llama-3.3-70B-Instruct",
    "gemini": "gemini-2.0-flash",
    "openrouter": "x-ai/grok-4.5",
    "mistral": "mistral-small-latest",
    "cohere": "command-r-plus-08-2024",
}


def get_catalog_entry(provider: str, model_id: str) -> dict[str, Any] | None:
    provider = (provider or "").lower()
    for item in PROVIDER_MODEL_CATALOG.get(provider, []):
        if item["id"] == model_id:
            return item
    return None


def get_context_window(provider: str, model_id: str, fallback: int = 32000) -> int:
    entry = get_catalog_entry(provider, model_id)
    if entry and entry.get("context_window"):
        return int(entry["context_window"])
    return fallback


def get_max_output_tokens(provider: str, model_id: str, fallback: int = 4096) -> int:
    entry = get_catalog_entry(provider, model_id)
    if entry and entry.get("max_output_tokens"):
        return int(entry["max_output_tokens"])
    return fallback


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) for local context trimming."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def trim_history_to_context(
    history: list[dict],
    *,
    provider: str,
    model: str,
    system_prompt: str,
    max_output_tokens: int,
) -> list[dict]:
    """Keep the newest turns that fit inside the model context window."""
    window = get_context_window(provider, model)
    reserve = max(max_output_tokens, 1024) + estimate_tokens(system_prompt) + 512
    budget = max(1024, window - reserve)

    kept: list[dict] = []
    used = 0
    # Always try to keep at least the latest few turns for chat continuity.
    min_keep = min(len(history), 6)
    for message in reversed(history):
        content = message.get("content", "")
        if isinstance(content, list):
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            # Images consume a chunk of budget; count conservatively.
            image_parts = sum(
                1
                for part in content
                if isinstance(part, dict) and part.get("type") == "image_url"
            )
            cost = estimate_tokens("\n".join(text_parts)) + image_parts * 800
        else:
            cost = estimate_tokens(str(content or ""))
        if kept and used + cost > budget and len(kept) >= min_keep:
            break
        kept.append(message)
        used += cost
    kept.reverse()
    return kept


def max_message_characters_for_model(provider: str, model: str) -> int:
    """Dynamic input character budget derived from model context size."""
    window = get_context_window(provider, model)
    # Leave room for history + completion; expose a practical single-message cap.
    return max(4000, min(200_000, (window * 3)))
