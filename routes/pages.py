"""HTML page routes."""

from flask import Blueprint, current_app, render_template

from config import running_on_vercel

pages_bp = Blueprint("pages", __name__)


@pages_bp.get("/")
def index():
    """Serve the main single-page chat workspace."""
    return render_template(
        "index.html",
        app_bootstrap={
            "hosted": running_on_vercel(),
            "preferStream": bool(current_app.config.get("PREFER_STREAM", True)),
            "maxUploadMb": int(current_app.config.get("MAX_UPLOAD_SIZE_MB", 8)),
            "durableDatabase": bool(current_app.config.get("DURABLE_DATABASE", False)),
        },
    )