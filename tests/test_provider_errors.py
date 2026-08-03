"""Provider error mapping and missing-key tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.base_provider import (
    InvalidAPIKeyError,
    MissingAPIKeyError,
    RateLimitError,
)
from services.groq_provider import GroqProvider


def test_missing_api_key_on_send(client):
    conversation = client.post("/api/conversations", json={"title": "Key test"}).get_json()["data"]
    response = client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"content": "Hello", "stream": False},
    )
    assert response.status_code == 502
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "MISSING_API_KEY"
    assert "API key" in body["error"]["message"]


def test_rate_limit_error_mapping():
    provider = GroqProvider(api_key="test-key", default_model="llama-3.3-70b-versatile")

    class FakeRateLimit(Exception):
        status_code = 429

    mapped = provider._map_exception(FakeRateLimit("rate limit exceeded"))
    assert isinstance(mapped, RateLimitError)
    assert "rate or quota limit" in mapped.message


def test_invalid_api_key_mapping():
    provider = GroqProvider(api_key="bad-key", default_model="llama-3.3-70b-versatile")

    class FakeUnauthorized(Exception):
        status_code = 401

    mapped = provider._map_exception(FakeUnauthorized("Invalid API Key"))
    assert isinstance(mapped, InvalidAPIKeyError)


def test_stream_rate_limit_surfaces_friendly_message(client):
    conversation = client.post("/api/conversations", json={"title": "Rate"}).get_json()["data"]
    fake_provider = MagicMock()
    fake_provider.generate_stream.side_effect = RateLimitError()

    with patch("routes.messages.get_provider", return_value=fake_provider):
        response = client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "Hello", "stream": True},
        )
        assert response.status_code == 200
        body = response.data.decode("utf-8")
        assert "event: error" in body
        assert "RATE_LIMIT" in body
        assert "rate or quota limit" in body.lower() or "limit" in body.lower()

    # User message is saved; assistant message is not.
    loaded = client.get(f"/api/conversations/{conversation['id']}").get_json()["data"]
    assert len(loaded["messages"]) == 1
    assert loaded["messages"][0]["role"] == "user"


def test_is_configured_false_without_key():
    provider = GroqProvider(api_key="", default_model="llama-3.3-70b-versatile")
    assert provider.is_configured() is False
    try:
        provider._get_client()
        assert False, "Expected MissingAPIKeyError"
    except MissingAPIKeyError as exc:
        assert exc.code == "MISSING_API_KEY"


def test_non_chat_models_filtered():
    assert GroqProvider._is_chat_model("llama-3.3-70b-versatile") is True
    assert GroqProvider._is_chat_model("whisper-large-v3") is False
    assert GroqProvider._is_chat_model("distil-whisper-large-v3-en") is False
