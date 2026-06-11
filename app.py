"""WSGI entrypoint.

Run locally:    python app.py
Run production: gunicorn --workers 1 --threads 8 --timeout 120 app:app

Exactly one worker process must be used: the app owns a single shared
browser session (see ``tempail_api.extensions``).
"""

from __future__ import annotations

import os

from tempail_api import create_app

app = create_app()


if __name__ == "__main__":
    # threaded=True is safe: the scraper serializes all browser access
    # onto its own worker thread.
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        threaded=True,
    )
