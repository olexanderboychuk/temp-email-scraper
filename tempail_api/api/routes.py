"""REST endpoints exposing the tempail.com scraper."""

from __future__ import annotations

from flask import Blueprint, Response, jsonify

from tempail_api.extensions import get_scraper

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.get("/health")
def health() -> Response:
    """Liveness probe; does not touch the browser."""
    return jsonify({"status": "ok"})


@api_bp.get("/email")
def current_email() -> Response:
    """Return the currently active temporary email address."""
    return jsonify({"email": get_scraper().get_email()})


@api_bp.get("/inbox")
def inbox() -> Response:
    """Return metadata of all received emails (empty list if none)."""
    return jsonify(get_scraper().get_inbox())


@api_bp.get("/email/<mail_id>")
def email_detail(mail_id: str) -> Response:
    """Return the full content of a single email by its id."""
    return jsonify(get_scraper().get_message(mail_id))


@api_bp.post("/email/refresh")
def refresh_email() -> Response:
    """Generate a brand-new address and return it."""
    return jsonify({"email": get_scraper().refresh_email()})
