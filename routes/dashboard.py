"""Usage dashboard API routes."""

from __future__ import annotations

from flask import Blueprint

from routes.helpers import success_response
from services.usage_service import UsageService

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api")


@dashboard_bp.get("/dashboard/usage")
def usage_dashboard():
    return success_response(UsageService.dashboard())
