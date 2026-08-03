"""HTTP helpers for consistent JSON responses."""

from __future__ import annotations

from typing import Any

from flask import jsonify


def success_response(data: Any = None, status: int = 200):
    payload: dict[str, Any] = {"success": True}
    if data is not None:
        payload["data"] = data
    return jsonify(payload), status


def error_response(code: str, message: str, status: int = 400):
    return jsonify(
        {
            "success": False,
            "error": {
                "code": code,
                "message": message,
            },
        }
    ), status
