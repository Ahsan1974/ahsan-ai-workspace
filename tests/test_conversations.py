"""Conversation and message API tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.base_provider import RateLimitError


def test_create_and_list_conversations(client):
    created = client.post("/api/conversations", json={"title": "Architecture notes", "model": "llama-3.3-70b-versatile"})
    assert created.status_code == 201
    body = created.get_json()
    assert body["success"] is True
    assert body["data"]["title"] == "Architecture notes"

    listed = client.get("/api/conversations")
    assert listed.status_code == 200
    items = listed.get_json()["data"]
    assert len(items) == 1
    assert items[0]["id"] == body["data"]["id"]


def test_rename_and_delete_conversation(client):
    created = client.post("/api/conversations", json={"title": "Old title"}).get_json()["data"]
    conversation_id = created["id"]

    renamed = client.patch(f"/api/conversations/{conversation_id}", json={"title": "New title"})
    assert renamed.status_code == 200
    assert renamed.get_json()["data"]["title"] == "New title"

    deleted = client.delete(f"/api/conversations/{conversation_id}")
    assert deleted.status_code == 200
    assert deleted.get_json()["data"]["deleted"] is True

    missing = client.get(f"/api/conversations/{conversation_id}")
    assert missing.status_code == 404
    assert missing.get_json()["success"] is False
    assert missing.get_json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_message_persistence_without_provider_call(client, app_ctx):
    from services.conversation_service import ConversationService

    conversation = ConversationService.create_conversation(provider="groq", model="llama-3.3-70b-versatile")
    user = ConversationService.add_message(
        conversation.id,
        role="user",
        content="Explain dependency injection",
        provider="groq",
        model="llama-3.3-70b-versatile",
        auto_title=True,
    )
    assistant = ConversationService.add_message(
        conversation.id,
        role="assistant",
        content="Dependency injection supplies collaborators from outside a class.",
        provider="groq",
        model="llama-3.3-70b-versatile",
    )

    loaded = client.get(f"/api/conversations/{conversation.id}").get_json()["data"]
    assert loaded["title"].startswith("Explain dependency injection")
    assert len(loaded["messages"]) == 2
    assert loaded["messages"][0]["id"] == user.id
    assert loaded["messages"][1]["id"] == assistant.id


def test_search_conversations(client):
    client.post("/api/conversations", json={"title": "Python review"})
    client.post("/api/conversations", json={"title": "Java notes"})
    result = client.get("/api/conversations?search=python")
    titles = [item["title"] for item in result.get_json()["data"]]
    assert titles == ["Python review"]


def test_send_message_streams_and_saves(client):
    conversation = client.post("/api/conversations", json={"title": "New Chat"}).get_json()["data"]

    fake_provider = MagicMock()
    fake_provider.generate_stream.return_value = iter(["Hello ", "from ", "Groq"])

    with patch("routes.messages.get_provider", return_value=fake_provider):
        response = client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "Hi there", "stream": True, "model": "llama-3.3-70b-versatile"},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.content_type
        body = response.data.decode("utf-8")
        assert "event: token" in body
        assert "event: done" in body

    loaded = client.get(f"/api/conversations/{conversation['id']}").get_json()["data"]
    assert len(loaded["messages"]) == 2
    assert loaded["messages"][0]["role"] == "user"
    assert loaded["messages"][1]["content"] == "Hello from Groq"
    assert loaded["title"].startswith("Hi there")


def test_export_conversation_json_and_markdown(client, app_ctx):
    from services.conversation_service import ConversationService

    conversation = ConversationService.create_conversation(provider="groq", model="test-model", title="Export me")
    ConversationService.add_message(conversation.id, "user", "Hello")
    ConversationService.add_message(conversation.id, "assistant", "World", provider="groq", model="test-model")

    md = client.get(f"/api/conversations/{conversation.id}/export/markdown")
    assert md.status_code == 200
    assert b"# Export me" in md.data
    assert b"Hello" in md.data

    js = client.get(f"/api/conversations/{conversation.id}/export/json")
    assert js.status_code == 200
    payload = js.get_json()
    assert payload["export_version"] == 1
    assert payload["conversation"]["title"] == "Export me"
    assert len(payload["conversation"]["messages"]) == 2


def test_export_all_excludes_secrets(client, app):
    app.config["GROQ_API_KEY"] = "should-never-appear"
    client.post("/api/conversations", json={"title": "One"})
    response = client.get("/api/export/all")
    assert response.status_code == 200
    text = response.data.decode("utf-8")
    assert "should-never-appear" not in text
    payload = response.get_json()
    assert "settings" in payload
    assert "GROQ_API_KEY" not in payload.get("settings", {})
