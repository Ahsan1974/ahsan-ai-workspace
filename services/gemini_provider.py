"""Google Gemini provider via Generative Language API."""

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
    MissingAPIKeyError,
    ModelInfo,
    ModelUnavailableError,
    NetworkUnavailableError,
    ProviderError,
    RateLimitError,
    UsageInfo,
)
from services.model_catalog import PROVIDER_MODEL_CATALOG
from services.provider_keys import key_looks_real

logger = logging.getLogger(__name__)


class GeminiProvider(BaseLLMProvider):
    name = "gemini"
    display_name = "Gemini"

    def __init__(self, api_key: str, default_model: str) -> None:
        self._api_key = (api_key or "").strip()
        self.default_model = default_model or "gemini-2.0-flash"
        self._models_cache: list[ModelInfo] | None = None
        self._models_cache_at = 0.0
        self.last_usage: UsageInfo | None = None
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def is_configured(self) -> bool:
        return key_looks_real(self._api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }

    def list_models(self) -> list[ModelInfo]:
        now = time.time()
        if self._models_cache is not None and now - self._models_cache_at < 300:
            return list(self._models_cache)

        catalog = [
            ModelInfo(
                id=item["id"],
                name=item["name"],
                context_window=item.get("context_window"),
                max_output_tokens=item.get("max_output_tokens"),
                supports_vision=bool(item.get("supports_vision")),
            )
            for item in PROVIDER_MODEL_CATALOG.get("gemini", [])
        ]
        if not self.is_configured():
            return catalog

        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.get(f"{self.base_url}/models", headers=self._headers())
            if response.status_code in {401, 403}:
                raise InvalidAPIKeyError()
            if response.status_code >= 400:
                return catalog
            payload = response.json()
            models: list[ModelInfo] = []
            for item in payload.get("models") or []:
                model_name = str(item.get("name") or "")
                if not model_name.startswith("models/"):
                    continue
                model_id = model_name.replace("models/", "", 1)
                methods = item.get("supportedGenerationMethods") or []
                if "generateContent" not in methods:
                    continue
                if "embedding" in model_id.lower():
                    continue
                models.append(
                    ModelInfo(
                        id=model_id,
                        name=model_id,
                        context_window=item.get("inputTokenLimit"),
                        max_output_tokens=item.get("outputTokenLimit"),
                    )
                )
            if not models:
                models = catalog
            # Keep the list usable: prefer known chat models from our catalog,
            # then fill with other live generateContent gemini models.
            catalog_ids = {m.id for m in catalog}
            preferred = [m for m in models if m.id in catalog_ids]
            extras = [m for m in models if m.id not in catalog_ids and "gemini" in m.id.lower()]
            for item in preferred:
                item.supports_vision = True
            for item in extras:
                item.supports_vision = True
            models = (preferred + extras[:10]) or catalog
            models.sort(key=lambda m: (0 if m.id in catalog_ids else 1, m.id.lower()))
            self._models_cache = models
            self._models_cache_at = now
            return list(models)
        except ProviderError:
            raise
        except Exception:  # noqa: BLE001
            return catalog

    @staticmethod
    def _to_gemini_contents(messages: list[dict[str, Any]], system_prompt: str) -> tuple[str | None, list[dict]]:
        system = (system_prompt or "").strip() or None
        contents: list[dict] = []
        for message in messages:
            role = message.get("role")
            raw = message.get("content", "")
            gemini_role = "user" if role == "user" else "model"
            parts: list[dict] = []
            if isinstance(raw, list):
                for part in raw:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text" and part.get("text"):
                        parts.append({"text": part["text"]})
                    elif part.get("type") == "image_url":
                        url = ((part.get("image_url") or {}).get("url") or "")
                        if url.startswith("data:") and ";base64," in url:
                            header, b64 = url.split(";base64,", 1)
                            mime = header.replace("data:", "", 1) or "image/png"
                            parts.append({"inline_data": {"mime_type": mime, "data": b64}})
            else:
                text = str(raw or "")
                if text:
                    parts.append({"text": text})
            if parts:
                contents.append({"role": gemini_role, "parts": parts})
        return system, contents

    def generate_response(self, messages, model, temperature, max_tokens, system_prompt) -> str:
        text = "".join(
            self.generate_stream(messages, model, temperature, max_tokens, system_prompt)
        ).strip()
        if not text:
            raise EmptyResponseError()
        return text

    def generate_stream(self, messages, model, temperature, max_tokens, system_prompt) -> Generator[str, None, None]:
        if not self.is_configured():
            raise MissingAPIKeyError(self.name)
        self.last_usage = None
        selected = (model or self.default_model).strip()
        system, contents = self._to_gemini_contents(messages, system_prompt)
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        url = f"{self.base_url}/models/{selected}:streamGenerateContent?alt=sse"
        yielded = False
        try:
            with httpx.Client(timeout=90.0) as client:
                with client.stream("POST", url, headers=self._headers(), json=body) as response:
                    if response.status_code in {401, 403}:
                        raise InvalidAPIKeyError()
                    if response.status_code == 429:
                        raise RateLimitError(self.display_name)
                    if response.status_code == 404:
                        raise ModelUnavailableError(selected)
                    if response.status_code >= 400:
                        logger.error("Gemini HTTP %s", response.status_code)
                        raise NetworkUnavailableError()

                    for line in response.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data:
                            continue
                        try:
                            payload = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        usage = payload.get("usageMetadata") or {}
                        if usage:
                            prompt = int(usage.get("promptTokenCount") or 0)
                            candidates = int(usage.get("candidatesTokenCount") or 0)
                            total = int(usage.get("totalTokenCount") or (prompt + candidates))
                            self.last_usage = UsageInfo(prompt, candidates, total)
                        for candidate in payload.get("candidates") or []:
                            parts = ((candidate.get("content") or {}).get("parts")) or []
                            for part in parts:
                                text = part.get("text")
                                if text:
                                    yielded = True
                                    yield text
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise APITimeoutError() from exc
        except httpx.HTTPError as exc:
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
