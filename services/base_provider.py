"""Base LLM provider interface and shared error types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Generator, Iterable


class ProviderError(Exception):
    """Base error raised by LLM providers."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class MissingAPIKeyError(ProviderError):
    def __init__(self, provider: str = "groq") -> None:
        super().__init__(
            "MISSING_API_KEY",
            f"No API key is configured for {provider}. "
            "Add it to your local .env file, or in Vercel → Project → Settings → Environment Variables.",
        )


class InvalidAPIKeyError(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            "INVALID_API_KEY",
            "The configured API key appears to be invalid. Please check your .env file.",
        )


class NetworkUnavailableError(ProviderError):
    def __init__(self, detail: str | None = None) -> None:
        message = "Unable to reach the provider. Check your internet connection and try again."
        if detail:
            cleaned = " ".join(str(detail).split())
            if cleaned:
                message = f"Provider error: {cleaned[:280]}"
        super().__init__("NETWORK_UNAVAILABLE", message)


class APITimeoutError(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            "API_TIMEOUT",
            "The provider request timed out. Please try again.",
        )


class RateLimitError(ProviderError):
    def __init__(self, provider: str | None = None) -> None:
        label = provider or "provider"
        super().__init__(
            "RATE_LIMIT",
            f"The {label} rate or quota limit has been reached. Please wait, "
            "switch model, or try another provider.",
        )


class ModelUnavailableError(ProviderError):
    def __init__(self, model: str | None = None) -> None:
        detail = f" ({model})" if model else ""
        super().__init__(
            "MODEL_UNAVAILABLE",
            f"The selected model{detail} is currently unavailable. Choose another model.",
        )


class InvalidModelError(ProviderError):
    def __init__(self, model: str | None = None) -> None:
        detail = f" '{model}'" if model else ""
        super().__init__(
            "INVALID_MODEL",
            f"The selected model{detail} is not valid for chat. Choose another model.",
        )


class EmptyResponseError(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            "EMPTY_RESPONSE",
            "The provider returned an empty response. Please try again.",
        )


class MalformedResponseError(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            "MALFORMED_RESPONSE",
            "The provider returned an unexpected response format.",
        )


@dataclass
class ModelInfo:
    """Normalized model metadata for the UI."""

    id: str
    name: str
    owned_by: str | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_vision: bool = False


@dataclass
class UsageInfo:
    """Token usage reported by a provider for one request."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def normalized(self) -> dict[str, int]:
        total = self.total_tokens or (self.prompt_tokens + self.completion_tokens)
        return {
            "prompt_tokens": int(self.prompt_tokens or 0),
            "completion_tokens": int(self.completion_tokens or 0),
            "total_tokens": int(total or 0),
        }


class BaseLLMProvider(ABC):
    """Interface every LLM provider must implement."""

    name: str = "base"
    display_name: str = "Base Provider"

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True when an API key (or equivalent) is present."""

    @abstractmethod
    def list_models(self) -> list[ModelInfo]:
        """Return chat-capable models available from the provider."""

    @abstractmethod
    def generate_response(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: str,
    ) -> str:
        """Generate a complete assistant response."""

    def generate_stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: str,
    ) -> Generator[str, None, None]:
        """Stream response tokens. Default falls back to a single chunk."""
        yield self.generate_response(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )

    def test_connection(self) -> dict[str, Any]:
        """Lightweight connection check used by Settings."""
        if not self.is_configured():
            raise MissingAPIKeyError(self.name)
        models = self.list_models()
        return {
            "provider": self.name,
            "configured": True,
            "available": True,
            "model_count": len(models),
        }

    @staticmethod
    def build_chat_messages(
        history: Iterable[dict[str, Any]],
        system_prompt: str,
    ) -> list[dict[str, Any]]:
        """Combine a system prompt with conversation history.

        Message content may be a plain string or a multimodal content list
        (text + image_url parts) for vision models.
        """
        messages: list[dict[str, Any]] = []
        prompt = (system_prompt or "").strip()
        if prompt:
            messages.append({"role": "system", "content": prompt})
        for item in history:
            role = item.get("role")
            content = item.get("content", "")
            if role not in {"user", "assistant"}:
                continue
            if content is None or content == "":
                continue
            messages.append({"role": role, "content": content})
        return messages
