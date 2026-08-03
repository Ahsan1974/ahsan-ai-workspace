# Personal AI Workspace

A lightweight, local-only personal AI chat application for Windows. It uses Flask + SQLite on the backend and a polished HTML/CSS/JavaScript interface. The first provider integration is **Groq** (GroqCloud). The architecture is ready for Gemini, OpenAI, and xAI Grok later without rewriting conversation storage or the UI shell.

This app is intended for **one user on a local laptop**. It is not a commercial multi-user product.

## Features

- Sidebar with new chat, search, rename, and delete
- Streaming assistant responses from Groq
- Markdown rendering with syntax highlighting and copy-code buttons
- Provider/model selectors (Groq enabled; others marked not configured)
- Dark mode by default, optional light mode
- Customizable system prompt, temperature, token limits, and context size
- Export one conversation (Markdown/JSON) or all data (JSON)
- Import conversations from JSON
- SQLite persistence under `instance/personal_ai_workspace.db`

## Requirements

- Windows 10/11
- Python 3.11 or newer (3.12/3.13 work)
- A GroqCloud API key from the Groq console

## Windows setup

Open PowerShell in the project folder (`personal-ai-workspace`):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

### Add your Groq API key

Edit `.env` and set:

```env
GROQ_API_KEY=put_your_new_groq_api_key_here
```

Replace the placeholder with your own key. Never commit `.env` or share the key.

Optional defaults already present in `.env.example`:

```env
GROQ_DEFAULT_MODEL=llama-3.3-70b-versatile
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
FLASK_DEBUG=false
```

### Start the application

```powershell
python app.py
```

Open the browser at:

```text
http://127.0.0.1:5000
```

### PowerShell activation troubleshooting (optional)

If script activation is blocked, you can allow it for the current user:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Or run without changing policy:

```powershell
.venv\Scripts\python.exe app.py
```

## Database location

Conversations and settings are stored in:

```text
instance/personal_ai_workspace.db
```

The path is also shown in **Settings → Data**.

## Export / import

- Per conversation: use the three-dot menu → Export Markdown / Export JSON
- Full backup: Settings → Data → Export all conversations (JSON)
- Restore: Settings → Data → Import conversations (JSON)

Imports create **new** conversations. They do not blindly overwrite existing IDs. API keys are never exported.

## Running tests

Tests mock Groq and do not require a real API key:

```powershell
pytest
```

## Common errors

| Situation | What to do |
| --- | --- |
| Missing API key banner | Copy `.env.example` to `.env`, set `GROQ_API_KEY`, restart |
| Invalid API key | Generate a new Groq key and update `.env` |
| Rate limit message | Wait, or switch to another available Groq model |
| Model unavailable | The app falls back to `GROQ_DEFAULT_MODEL` and notifies you |
| Import too large | Keep JSON under `MAX_IMPORT_SIZE_MB` (default 10) |

Example rate-limit message:

> The Groq free-plan limit has been reached. Please wait before sending another request or select another available model.

## Free API rate limits

Groq free-plan accounts have request and token limits. When those limits are hit, the app shows a friendly error and does not save a partial assistant reply. You can continue after waiting or by choosing another available model.

## Security notes

- The server binds to `127.0.0.1` only by default
- API keys stay on the Flask backend and are never sent to the browser
- `.env`, database files, and exports are listed in `.gitignore`
- Do not paste API keys into chat messages, screenshots, or source control
- This is a personal local tool — do not expose it to the public internet

## Adding another provider later

1. Create `services/gemini_provider.py` implementing `BaseLLMProvider`
2. Add an environment variable such as `GEMINI_API_KEY`
3. Register the provider in `services/provider_registry.py`
4. Enable it in the provider list UI

Conversation storage, message routes, and most of the frontend can stay the same.

## Project structure

```text
personal-ai-workspace/
├── app.py
├── config.py
├── extensions.py
├── requirements.txt
├── README.md
├── .env.example
├── .gitignore
├── instance/
├── models/
├── services/
├── routes/
├── templates/
├── static/
└── tests/
```

## License

Personal use. Keep your API keys private.
