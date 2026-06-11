# Official Playwright image: Python + Chromium + all system libs preinstalled.
# The image tag must match the playwright version pinned in requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY tempail_api ./tempail_api
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENV HEADLESS=true \
    PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]
# Exactly 1 worker: the app holds a single shared browser session.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "--timeout", "120", "app:app"]
