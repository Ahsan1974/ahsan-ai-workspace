"""Export and import API routes."""

from __future__ import annotations

import json
import logging

from flask import Blueprint, Response, current_app, request

from routes.helpers import error_response, success_response
from services.conversation_service import ConversationService, ServiceError
from services.export_service import ExportService

logger = logging.getLogger(__name__)

exports_bp = Blueprint("exports", __name__, url_prefix="/api")


@exports_bp.get("/conversations/<int:conversation_id>/export/markdown")
def export_conversation_markdown(conversation_id: int):
    try:
        conversation = ConversationService.get_conversation(conversation_id)
        content = ExportService.conversation_to_markdown(conversation)
        filename = f"conversation-{conversation.id}.md"
        return Response(
            content,
            mimetype="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ServiceError as exc:
        return error_response(exc.code, exc.message, exc.status_code)


@exports_bp.get("/conversations/<int:conversation_id>/export/json")
def export_conversation_json(conversation_id: int):
    try:
        conversation = ConversationService.get_conversation(conversation_id)
        payload = ExportService.conversation_to_json(conversation)
        filename = f"conversation-{conversation.id}.json"
        return Response(
            json.dumps(payload, indent=2, ensure_ascii=False),
            mimetype="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ServiceError as exc:
        return error_response(exc.code, exc.message, exc.status_code)


@exports_bp.get("/export/all")
def export_all():
    payload = ExportService.export_all()
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="personal-ai-workspace-export.json"'},
    )


@exports_bp.post("/import")
def import_data():
    max_mb = int(current_app.config.get("MAX_IMPORT_SIZE_MB", 10))
    max_bytes = max_mb * 1024 * 1024

    payload = None
    if request.files.get("file"):
        uploaded = request.files["file"]
        raw = uploaded.read()
        if len(raw) > max_bytes:
            return error_response(
                "IMPORT_FILE_TOO_LARGE",
                f"Import file exceeds the maximum size of {max_mb} MB.",
                413,
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return error_response("INVALID_JSON_IMPORT", "Import file is not valid JSON.")
    else:
        content_length = request.content_length or 0
        if content_length > max_bytes:
            return error_response(
                "IMPORT_FILE_TOO_LARGE",
                f"Import file exceeds the maximum size of {max_mb} MB.",
                413,
            )
        payload = request.get_json(silent=True)
        if payload is None:
            return error_response("INVALID_JSON_IMPORT", "Request body must be valid JSON.")

    try:
        result = ExportService.import_payload(payload)
        return success_response(result)
    except ServiceError as exc:
        return error_response(exc.code, exc.message, exc.status_code)
    except Exception:  # noqa: BLE001
        logger.exception("Import failed unexpectedly")
        return error_response("INVALID_JSON_IMPORT", "Unable to import the provided file.")
