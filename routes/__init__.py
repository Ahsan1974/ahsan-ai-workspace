"""Route blueprints package."""

from flask import Flask

from routes.conversations import conversations_bp
from routes.dashboard import dashboard_bp
from routes.exports import exports_bp
from routes.messages import messages_bp
from routes.pages import pages_bp
from routes.providers import providers_bp
from routes.settings import settings_bp


def register_blueprints(app: Flask) -> None:
    """Attach all route blueprints to the Flask app."""
    app.register_blueprint(pages_bp)
    app.register_blueprint(conversations_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(exports_bp)
    app.register_blueprint(dashboard_bp)
