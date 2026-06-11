"""HTTP layer: routes and JSON error handling."""

from tempail_api.api.errors import register_error_handlers
from tempail_api.api.routes import api_bp

__all__ = ["api_bp", "register_error_handlers"]
