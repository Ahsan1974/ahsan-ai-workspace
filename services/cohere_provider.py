"""Cohere Chat API provider."""

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

logger = logging.getLogger(__name__)


class CohereProvider(BaseLLMProvider):
    name = "cohere"
    display_name = "Cohere"

    def __init__(self, api_key: str, default_model: str) -> None:
        self._api_key = (api_key or "").strip()
        self.default_model = default_model or "command-r-plus-08-2024"
        self.base_url = "https://api.cohere.com"
        self._models_cache: list[ModelInfo] | None = None
        self._models_cache_at = 0.0
        self.last_usage: UsageInfo | None = None

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
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
            )
            for item in PROVIDER_MODEL_CATALOG.get("cohere", [])
        ]
        self._models_cache = catalog
        self._models_cache_at = now
        return list(catalog)

    @staticmethod
    def _split_messages(messages: list[dict[str, Any]], system_prompt: str) -> tuple[str, list[dict], str]:
        system = (system_prompt or "").strip()
        chat_history: list[dict] = []
        latest_user = ""
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            if isinstance(content, list):
                texts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                content = "\n".join(t for t in texts if t)
            text = str(content or "").strip()
            if not text:
                continue
            if role == "user":
                latest_user = text
                chat_history.append({"role": "user", "message": text})
            elif role == "assistant":
                chat_history.append({"role": "chatbot", "message": text})
        # Cohere wants current message separate from history.
        if chat_history and chat_history[-1]["role"] == "user":
            chat_history = chat_history[:-1]
        return system, chat_history, latest_user

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
        system, history, latest = self._split_messages(messages, system_prompt)
        if not latest:
            raise EmptyResponseError()

        body: dict[str, Any] = {
            "model": selected,
            "message": latest,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if system:
            body["preamble"] = system
        if history:
            body["chat_history"] = history

        yielded = False
        try:
            with httpx.Client(timeout=90.0) as client:
                with client.stream(
                    "POST",
                    f"{self.base_url}/v1/chat",
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
                        logger.error("Cohere HTTP %s", response.status_code)
                        raise NetworkUnavailableError()

                    for line in response.iter_lines():
                        if not line:
                            continue
                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError:
                            if line.startswith("data:"):
                                try:
                                    payload = json.loads(line[5:].strip())
                                except json.JSONDecodeError:
                                    continue
                            else:
                                continue
                        event_type = payload.get("event_type") or payload.get("type")
                        if event_type in {"text-generation", "content-delta"}:
                            text = payload.get("text") or ((payload.get("delta") or {}).get("message") or {}).get("content", {}).get("text")
                            # v1 stream uses text-generation with text field
                            if not text:
                                text = payload.get("text")
                            if text:
                                yielded = True
                                yield text
                        elif event_type == "stream-end":
                            usage = ((payload.get("response") or {}).get("meta") or {}).get("billed_units") or {}
                            input_tokens = int(usage.get("input_tokens") or 0)
                            output_tokens = int(usage.get("output_tokens") or 0)
                            self.last_usage = UsageInfo(
                                prompt_tokens=input_tokens,
                                completion_tokens=output_tokens,
                                total_tokens=input_tokens + output_tokens,
                            )
                        else:
                            # Some responses put token text directly
                            text = payload.get("text")
                            if text and event_type != "stream-start":
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
        models = self.list_models()
        return {
            "provider": self.name,
            "configured": True,
            "available": True,
            "model_count": len(models),
        }
