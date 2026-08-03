"""HTML page routes."""

from flask import Blueprint, render_template

pages_bp = Blueprint("pages", __name__)


@pages_bp.get("/")
def index():
    """Serve the main single-page chat workspace."""
    return render_template("index.html")
