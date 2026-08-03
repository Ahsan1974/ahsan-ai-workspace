"""OpenAI-compatible chat providers (SambaNova, OpenRouter, Mistral, etc.)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Generator

import httpx

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
    ProviderError,
    RateLimitError,
    UsageInfo,
)
from services.model_catalog import PROVIDER_MODEL_CATALOG

logger = logging.getLogger(__name__)

SKIP_MODEL_KEYWORDS = (
    "embed",
    "embedding",
    "whisper",
    "tts",
    "audio",
    "speech",
    "transcribe",
    "moderation",
    "rerank",
    "guard",
    "cli",
    "ocr",
    "image-edit",
)


class OpenAICompatibleProvider(BaseLLMProvider):
    """Generic chat + streaming client for OpenAI-compatible HTTP APIs."""

    def __init__(
        self,
        *,
        name: str,
        display_name: str,
        api_key: str,
        base_url: str,
        default_model: str,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 120.0,
        include_usage_stream_option: bool = True,
        catalog_only_when_large: bool = True,
    ) -> None:
        self.name = name
        self.display_name = display_name
        self._api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        self.timeout = timeout
        self.include_usage_stream_option = include_usage_stream_option
        self.catalog_only_when_large = catalog_only_when_large
        self._models_cache: list[ModelInfo] | None = None
        self._models_cache_at = 0.0
        self.last_usage: UsageInfo | None = None

    def is_configured(self) -> bool:
        return bool(self._api_key) and self._api_key.lower() not in {
            "put_your_key_here",
            "changeme",
        }

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        return headers

    @staticmethod
    def _is_chat_model(model_id: str) -> bool:
        lowered = (model_id or "").lower()
        return not any(token in lowered for token in SKIP_MODEL_KEYWORDS)

    def _filter_models(self, models: list[ModelInfo], catalog: list[ModelInfo]) -> list[ModelInfo]:
        catalog_map = {m.id: m for m in catalog}
        filtered: list[ModelInfo] = []
        for model in models:
            if not self._is_chat_model(model.id):
                continue
            # Skip OpenRouter "routing" aliases that start with ~
            if model.id.startswith("~"):
                continue
            meta = catalog_map.get(model.id)
            if meta:
                filtered.append(meta)
            else:
                # Keep live xAI Grok models even if catalog is slightly behind.
                if "grok" in model.id.lower():
                    filtered.append(
                        ModelInfo(
                            id=model.id,
                            name=f"{model.id} (xAI Grok)",
                            owned_by=model.owned_by,
                            context_window=256000,
                            max_output_tokens=16384,
                            supports_vision=True,
                        )
                    )
                else:
                    filtered.append(model)

        # Large provider lists: keep curated catalog hits + any Grok models.
        if self.catalog_only_when_large and len(filtered) > 35 and catalog:
            available_ids = {m.id for m in filtered}
            curated = [m for m in catalog if m.id in available_ids]
            grok_live = [m for m in filtered if "grok" in m.id.lower()]
            merged: list[ModelInfo] = []
            seen: set[str] = set()
            for model in curated + grok_live:
                if model.id in seen:
                    continue
                merged.append(model)
                seen.add(model.id)
            filtered = merged or list(catalog)

        defaults = {self.default_model}
        filtered.sort(
            key=lambda m: (
                0 if "grok" in m.id.lower() else 1,
                0 if m.id in defaults else 1,
                m.id.lower(),
            )
        )
        return filtered

    def list_models(self) -> list[ModelInfo]:
        now = time.time()
        if self._models_cache is not None and now - self._models_cache_at < 300:
            return list(self._models_cache)

        catalog = [
            ModelInfo(
                id=item["id"],
                name=item.get("name") or item["id"],
                context_window=item.get("context_window"),
                max_output_tokens=item.get("max_output_tokens"),
                supports_vision=bool(item.get("supports_vision")),
            )
            for item in PROVIDER_MODEL_CATALOG.get(self.name, [])
        ]

        if not self.is_configured():
            return catalog or [ModelInfo(id=self.default_model, name=self.default_model)]

        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.get(f"{self.base_url}/models", headers=self._headers())
            if response.status_code in {401, 403}:
                raise InvalidAPIKeyError()
            if response.status_code >= 400:
                logger.warning("%s model list HTTP %s", self.name, response.status_code)
                self._models_cache = catalog or [ModelInfo(id=self.default_model, name=self.default_model)]
                self._models_cache_at = now
                return list(self._models_cache)

            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            models: list[ModelInfo] = []
            if isinstance(data, list):
                for item in data:
                    model_id = (item or {}).get("id") if isinstance(item, dict) else None
                    if not model_id:
                        continue
                    models.append(ModelInfo(id=model_id, name=model_id, owned_by=(item or {}).get("owned_by")))
            if not models:
                models = catalog
            merged = self._filter_models(models, catalog)
            if not merged:
                merged = catalog or [ModelInfo(id=self.default_model, name=self.default_model)]
            self._models_cache = merged
            self._models_cache_at = now
            return list(merged)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s model list failed: %s", self.name, type(exc).__name__)
            return catalog or [ModelInfo(id=self.default_model, name=self.default_model)]

    def generate_response(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: str,
    ) -> str:
        text = "".join(
            self.generate_stream(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
        ).strip()
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
        if not self.is_configured():
            raise MissingAPIKeyError(self.name)

        self.last_usage = None
        chat_messages = self.build_chat_messages(messages, system_prompt)
        selected = (model or self.default_model).strip()
        body: dict[str, Any] = {
            "model": selected,
            "messages": chat_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if self.include_usage_stream_option:
            body["stream_options"] = {"include_usage": True}

        yielded = False
        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=body,
                ) as response:
                    if response.status_code in {401, 403}:
                        raise InvalidAPIKeyError()
                    if response.status_code == 429:
                        raise RateLimitError(self.display_name)
                    if response.status_code == 404:
                        raise ModelUnavailableError(selected)
                    if response.status_code >= 400:
                        detail = response.read().decode("utf-8", errors="replace")[:500]
                        detail_l = detail.lower()
                        if any(
                            token in detail_l
                            for token in (
                                "context",
                                "too long",
                                "maximum context",
                                "token",
                                "length",
                                "payload too large",
                            )
                        ):
                            raise ProviderError(
                                "INPUT_TOO_LONG",
                                "The attached content is too large for this model. "
                                "Try a shorter PDF, fewer pages, or a model with a larger context window.",
                            )
                        if "model" in detail_l:
                            raise InvalidModelError(selected)
                        if "stream_options" in detail_l or "unknown" in detail_l:
                            # Retry once without stream_options for picky providers.
                            if self.include_usage_stream_option and "stream_options" in body:
                                self.include_usage_stream_option = False
                                yield from self.generate_stream(
                                    messages, model, temperature, max_tokens, system_prompt
                                )
                                return
                        logger.error("%s chat error HTTP %s: %s", self.name, response.status_code, detail[:200])
                        raise NetworkUnavailableError(detail[:280] or f"HTTP {response.status_code}")

                    for line in response.iter_lines():
                        if not line:
                            continue
                        if line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            payload = json.loads(data)
                        except json.JSONDecodeError as exc:
                            raise MalformedResponseError() from exc

                        usage = payload.get("usage")
                        if isinstance(usage, dict):
                            self.last_usage = UsageInfo(
                                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                                completion_tokens=int(usage.get("completion_tokens") or 0),
                                total_tokens=int(usage.get("total_tokens") or 0),
                            )

                        choices = payload.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yielded = True
                            yield content
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise APITimeoutError() from exc
        except httpx.HTTPError as exc:
            raise NetworkUnavailableError() from exc
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, ProviderError):
                raise
            logger.exception("%s stream failed", self.name)
            raise NetworkUnavailableError() from exc

        if not yielded:
            raise EmptyResponseError()

    def test_connection(self) -> dict[str, Any]:
        if not self.is_configured():
            raise MissingAPIKeyError(self.name)
        self._models_cache = None
        models = self.list_models()
        return {
            "provider": self.name,
            "configured": True,
            "available": True,
            "model_count": len(models),
        }


def create_sambanova_provider(api_key: str, default_model: str) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="sambanova",
        display_name="SambaNova",
        api_key=api_key,
        base_url="https://api.sambanova.ai/v1",
        default_model=default_model or "Meta-Llama-3.3-70B-Instruct",
    )


def create_openrouter_provider(api_key: str, default_model: str) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="openrouter",
        display_name="OpenRouter",
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_model=default_model or "openai/gpt-4o-mini",
        extra_headers={
            "HTTP-Referer": "http://127.0.0.1:5000",
            "X-Title": "Ahsan AI Workspace",
        },
        catalog_only_when_large=True,
    )


def create_mistral_provider(api_key: str, default_model: str) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="mistral",
        display_name="Mistral",
        api_key=api_key,
        base_url="https://api.mistral.ai/v1",
        default_model=default_model or "mistral-small-latest",
        include_usage_stream_option=False,
        catalog_only_when_large=True,
    )
