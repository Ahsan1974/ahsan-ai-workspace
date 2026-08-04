"""GroqCloud LLM provider implementation."""

from __future__ import annotations

import logging
import time
from typing import Any, Generator

from groq import APIConnectionError, APIStatusError, APITimeoutError as GroqTimeoutError, Groq, RateLimitError as GroqRateLimitError

from services.base_provider import (
    APITimeoutError,
    BaseLLMProvider,
    EmptyResponseError,
    InvalidAPIKeyError,
    InvalidModelError,
    MalformedResponseError,
    MissingAPIKeyError,
    ModelInfo,
    ModelUnavailableError,
    NetworkUnavailableError,
    RateLimitError,
)

from services.provider_keys import key_looks_real

logger = logging.getLogger(__name__)

# Models with these tokens in the id are usually not useful for text chat.
NON_CHAT_KEYWORDS = (
    "whisper",
    "tts",
    "speech",
    "audio",
    "transcribe",
    "guard",
    "prompt-guard",
    "distil-whisper",
    "orpheus",  # speech/TTS style models
    "compound",  # agent/tooling systems, not plain chat
)


class GroqProvider(BaseLLMProvider):
    """Official Groq Python SDK integration."""

    name = "groq"
    display_name = "Groq"

    def __init__(self, api_key: str, default_model: str) -> None:
        self._api_key = (api_key or "").strip()
        self.default_model = default_model
        self._client: Groq | None = None
        self._models_cache: list[ModelInfo] | None = None
        self._models_cache_at: float = 0.0
        self._cache_ttl_seconds = 300.0
        self.last_usage = None

    def is_configured(self) -> bool:
        return key_looks_real(self._api_key)

    def _get_client(self) -> Groq:
        if not self.is_configured():
            raise MissingAPIKeyError(self.name)
        if self._client is None:
            self._client = Groq(api_key=self._api_key)
        return self._client

    @staticmethod
    def _is_chat_model(model_id: str) -> bool:
        lowered = model_id.lower()
        return not any(token in lowered for token in NON_CHAT_KEYWORDS)

    def list_models(self) -> list[ModelInfo]:
        """Fetch and cache chat-capable Groq models."""
        now = time.time()
        if self._models_cache is not None and (now - self._models_cache_at) < self._cache_ttl_seconds:
            return list(self._models_cache)

        client = self._get_client()
        try:
            response = client.models.list()
            data = getattr(response, "data", None) or []
            from services.attachment_service import supports_vision
            from services.model_catalog import get_catalog_entry

            models: list[ModelInfo] = []
            for item in data:
                model_id = getattr(item, "id", None) or ""
                if not model_id or not self._is_chat_model(model_id):
                    continue
                entry = get_catalog_entry("groq", model_id) or {}
                models.append(
                    ModelInfo(
                        id=model_id,
                        name=entry.get("name") or model_id,
                        owned_by=getattr(item, "owned_by", None),
                        context_window=entry.get("context_window"),
                        max_output_tokens=entry.get("max_output_tokens"),
                        supports_vision=bool(entry.get("supports_vision")) or supports_vision(model_id),
                    )
                )
            models.sort(key=lambda m: m.id.lower())
            if not models:
                models = [ModelInfo(id=self.default_model, name=self.default_model)]
            self._models_cache = models
            self._models_cache_at = now
            return list(models)
        except Exception as exc:  # noqa: BLE001 - mapped below
            mapped = self._map_exception(exc)
            logger.warning("Groq model list failed: %s", mapped.code)
            # Fall back to configured default so the UI remains usable.
            return [ModelInfo(id=self.default_model, name=self.default_model)]

    def generate_response(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: str,
    ) -> str:
        chunks = list(
            self.generate_stream(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
        )
        text = "".join(chunks).strip()
        if not text:
            raise EmptyResponseError()
        return text

    def generate_stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: str,
    ) -> Generator[str, None, None]:
        self.last_usage = None
        client = self._get_client()
        chat_messages = self.build_chat_messages(messages, system_prompt)
        selected_model = (model or self.default_model).strip()

        try:
            create_kwargs = {
                "model": selected_model,
                "messages": chat_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            # Older groq SDK builds reject stream_options.
            stream = client.chat.completions.create(**create_kwargs)
            yielded = False
            for event in stream:
                try:
                    usage = getattr(event, "usage", None)
                    if usage is not None:
                        from services.base_provider import UsageInfo

                        self.last_usage = UsageInfo(
                            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
                        )
                    choices = getattr(event, "choices", None) or []
                    if not choices:
                        continue
                    delta = getattr(choices[0], "delta", None)
                    content = getattr(delta, "content", None) if delta is not None else None
                    if content:
                        yielded = True
                        yield content
                except (AttributeError, IndexError) as exc:
                    logger.error("Malformed Groq stream chunk: %s", type(exc).__name__)
                    raise MalformedResponseError() from exc
            if not yielded:
                raise EmptyResponseError()
        except Exception as exc:  # noqa: BLE001
            if isinstance(
                exc,
                (
                    MissingAPIKeyError,
                    InvalidAPIKeyError,
                    NetworkUnavailableError,
                    APITimeoutError,
                    RateLimitError,
                    ModelUnavailableError,
                    InvalidModelError,
                    EmptyResponseError,
                    MalformedResponseError,
                ),
            ):
                raise
            raise self._map_exception(exc, selected_model) from exc

    def test_connection(self) -> dict[str, Any]:
        if not self.is_configured():
            raise MissingAPIKeyError(self.name)
        # Bypass cache so Settings "Test Connection" is a real check.
        self._models_cache = None
        models = self.list_models()
        # list_models swallows some errors and falls back; probe the client once more.
        try:
            client = self._get_client()
            client.models.list()
        except Exception as exc:  # noqa: BLE001
            raise self._map_exception(exc) from exc
        return {
            "provider": self.name,
            "configured": True,
            "available": True,
            "model_count": len(models),
        }

    def _map_exception(self, exc: Exception, model: str | None = None) -> Exception:
        """Map Groq SDK / HTTP errors to friendly provider errors."""
        message = str(exc).lower()
        status = getattr(exc, "status_code", None)

        if isinstance(exc, GroqRateLimitError) or status == 429:
            return RateLimitError()
        if isinstance(exc, GroqTimeoutError):
            return APITimeoutError()
        if isinstance(exc, APIConnectionError):
            return NetworkUnavailableError()
        if isinstance(exc, APIStatusError):
            detail = ""
            try:
                body = getattr(exc, "body", None)
                if isinstance(body, dict):
                    err = body.get("error") or {}
                    detail = str(err.get("message") or body)[:280]
                elif body:
                    detail = str(body)[:280]
            except Exception:  # noqa: BLE001
                detail = ""
            if not detail:
                detail = str(exc)[:280]
            if status in {401, 403} or "invalid api key" in message or "unauthorized" in message:
                return InvalidAPIKeyError()
            if status == 404 or "model" in message and ("not found" in message or "does not exist" in message):
                return ModelUnavailableError(model)
            if status == 400 and ("model" in message or "does not exist" in message):
                return InvalidModelError(model)
            if status == 429:
                return RateLimitError()
            logger.error("Groq APIStatusError status=%s: %s", status, detail[:200])
            if status and status >= 400:
                from services.base_provider import ProviderError

                return ProviderError(
                    "PROVIDER_ERROR",
                    detail or f"Groq rejected the request (HTTP {status}).",
                )
            return NetworkUnavailableError(detail or None)

        if "timeout" in message:
            return APITimeoutError()
        if "api key" in message or "unauthorized" in message or "authentication" in message:
            return InvalidAPIKeyError()
        if "rate limit" in message or "429" in message:
            return RateLimitError()
        if "model" in message and ("not found" in message or "does not exist" in message):
            return ModelUnavailableError(model)
        if "connection" in message or "network" in message:
            return NetworkUnavailableError()

        logger.error("Unhandled Groq error type=%s", type(exc).__name__)
        return NetworkUnavailableError()
