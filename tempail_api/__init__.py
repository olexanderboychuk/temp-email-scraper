"""Flask application factory for the tempail.com scraper API."""

from __future__ import annotations

from flask import Flask

from tempail_api.api import api_bp, register_error_handlers
from tempail_api.config import configure_logging
from tempail_api.extensions import warmup_scraper


def create_app() -> Flask:
    """Build and configure the Flask application."""
    configure_logging()
    app = Flask(__name__)
    app.register_blueprint(api_bp)
    register_error_handlers(app)
    warmup_scraper()
    return app
