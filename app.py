"""Personal AI Workspace — application entry point."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

from flask import Flask

from config import Config, INSTANCE_DIR
from extensions import db
from routes import register_blueprints
from services.settings_service import SettingsService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("personal_ai_workspace")


class SecretMaskingFilter(logging.Filter):
    """Mask likely secrets before they reach log handlers."""

    _pattern = re.compile(
        r"(api[_-]?key|authorization|bearer|secret|token)\s*[:=]\s*([^\s,;]+)",
        re.IGNORECASE,
    )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            masked = self._pattern.sub(r"\1=***", message)
            if masked != message:
                record.msg = masked
                record.args = ()
        except Exception:  # noqa: BLE001 - never break logging
            pass
        return True


def create_app(config_object: type = Config) -> Flask:
    """Application factory used by app.py and tests."""
    # Must be writable: on Vercel this is under /tmp (see config.INSTANCE_DIR).
    try:
        INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("Unable to create instance directory at %s", INSTANCE_DIR)
        raise

    app = Flask(
        __name__,
        instance_path=str(INSTANCE_DIR),
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(config_object)
    # Always reload templates in this local personal app so UI edits appear after refresh.
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True

    for handler in logging.root.handlers:
        handler.addFilter(SecretMaskingFilter())

    db.init_app(app)
    register_blueprints(app)

    with app.app_context():
        # Import models so metadata is registered before create_all.
        import models  # noqa: F401

        try:
            db.create_all()
            SettingsService.ensure_defaults()
        except Exception:
            logger.exception(
                "Database init failed (uri=%s, instance=%s)",
                app.config.get("SQLALCHEMY_DATABASE_URI"),
                INSTANCE_DIR,
            )
            raise

    logger.info(
        "App ready (instance=%s, db=%s)",
        INSTANCE_DIR,
        app.config.get("SQLALCHEMY_DATABASE_URI"),
    )

    @app.errorhandler(404)
    def not_found(error):  # noqa: ARG001
        from routes.helpers import error_response

        return error_response("NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def method_not_allowed(error):  # noqa: ARG001
        from routes.helpers import error_response

        return error_response("METHOD_NOT_ALLOWED", "Method not allowed.", 405)

    @app.errorhandler(413)
    def too_large(error):  # noqa: ARG001
        from routes.helpers import error_response

        return error_response("IMPORT_FILE_TOO_LARGE", "Uploaded file is too large.", 413)

    @app.errorhandler(500)
    def server_error(error):  # noqa: ARG001
        logger.exception("Unhandled server error")
        from routes.helpers import error_response

        return error_response("INTERNAL_ERROR", "An unexpected server error occurred.", 500)

    max_upload_mb = max(
        int(app.config.get("MAX_IMPORT_SIZE_MB", 10)),
        int(app.config.get("MAX_UPLOAD_SIZE_MB", 20)),
    )
    app.config["MAX_CONTENT_LENGTH"] = max_upload_mb * 1024 * 1024
    return app


# Vercel / WSGI entrypoint — must be a top-level Flask instance named "app".
app = create_app()


def main() -> None:
    host = Config.FLASK_HOST
    if host not in {"127.0.0.1", "localhost"}:
        logger.warning("Refusing non-local host binding (%s); using 127.0.0.1", host)
        host = "127.0.0.1"

    logger.info("Starting Personal AI Workspace at http://%s:%s", host, Config.FLASK_PORT)
    app.run(host=host, port=Config.FLASK_PORT, debug=Config.FLASK_DEBUG, threaded=True)


if __name__ == "__main__":
    # Ensure the project root is importable when launched as a script.
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    main()
