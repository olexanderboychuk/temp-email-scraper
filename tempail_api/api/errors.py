"""Global JSON error handlers - the API never returns an HTML traceback."""

from __future__ import annotations

import logging

from flask import Flask, Response, jsonify
from werkzeug.exceptions import HTTPException

from tempail_api.exceptions import (
    AntiBotChallengeError,
    EmailNotFoundError,
    ScraperError,
    ScraperTimeoutError,
)

logger = logging.getLogger(__name__)


def _json_error(name: str, message: str, status: int) -> tuple[Response, int]:
    return jsonify({"error": name, "message": message}), status


def register_error_handlers(app: Flask) -> None:
    """Attach all global error handlers to the application."""

    @app.errorhandler(EmailNotFoundError)
    def handle_not_found(error: EmailNotFoundError) -> tuple[Response, int]:
        logger.info("Mail not found: %s", error)
        return _json_error("not_found", str(error), 404)

    @app.errorhandler(AntiBotChallengeError)
    def handle_antibot(error: AntiBotChallengeError) -> tuple[Response, int]:
        logger.warning("Anti-bot challenge: %s", error)
        return _json_error("anti_bot_challenge", str(error), 503)

    @app.errorhandler(ScraperTimeoutError)
    def handle_timeout(error: ScraperTimeoutError) -> tuple[Response, int]:
        logger.error("Scraper timeout: %s", error)
        return _json_error(
            "service_unavailable",
            "The upstream mail service did not respond in time. Try again shortly.",
            503,
        )

    @app.errorhandler(ScraperError)
    def handle_scraper_error(error: ScraperError) -> tuple[Response, int]:
        logger.error("Scraper failure: %s", error, exc_info=True)
        return _json_error(
            "internal_error",
            "Browser automation failed. See server logs.",
            500,
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException) -> tuple[Response, int]:
        return _json_error(
            error.name.lower().replace(" ", "_"),
            error.description or error.name,
            error.code or 500,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(_error: Exception) -> tuple[Response, int]:
        logger.exception("Unhandled error")
        return _json_error("internal_error", "An unexpected error occurred.", 500)
