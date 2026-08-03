"""Settings API tests."""

from __future__ import annotations


def test_get_and_update_settings(client):
    initial = client.get("/api/settings")
    assert initial.status_code == 200
    data = initial.get_json()["data"]
    assert data["theme"] == "dark"
    assert data["temperature"] == 0.7
    assert "database_path" in data
    assert "default_system_prompt" in data

    updated = client.put(
        "/api/settings",
        json={
            "theme": "light",
            "temperature": 0.2,
            "max_tokens": 2048,
            "enter_to_send": False,
        },
    )
    assert updated.status_code == 200
    body = updated.get_json()["data"]
    assert body["theme"] == "light"
    assert body["temperature"] == 0.2
    assert body["max_tokens"] == 2048
    assert body["enter_to_send"] is False

    reloaded = client.get("/api/settings").get_json()["data"]
    assert reloaded["theme"] == "light"
    assert reloaded["enter_to_send"] is False


def test_invalid_settings_rejected(client):
    response = client.put("/api/settings", json={"temperature": 5})
    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_SETTINGS"


def test_reset_system_prompt(client):
    client.put("/api/settings", json={"system_prompt": "Temporary prompt"})
    reset = client.post("/api/settings/reset-system-prompt")
    assert reset.status_code == 200
    prompt = reset.get_json()["data"]["system_prompt"]
    assert "Ahsan's personal AI assistant" in prompt


def test_clear_all_conversations(client):
    client.post("/api/conversations", json={"title": "A"})
    client.post("/api/conversations", json={"title": "B"})
    cleared = client.delete("/api/settings/conversations")
    assert cleared.status_code == 200
    assert cleared.get_json()["data"]["cleared"] == 2
    listed = client.get("/api/conversations").get_json()["data"]
    assert listed == []


def test_provider_status_never_returns_key(client, app):
    app.config["GROQ_API_KEY"] = "secret-value-not-for-clients"
    response = client.get("/api/providers/status?provider=groq")
    assert response.status_code == 200
    body = response.get_json()
    text = response.data.decode("utf-8")
    assert "secret-value-not-for-clients" not in text
    assert body["data"]["configured"] is True
    assert "api_key" not in body["data"]
