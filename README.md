# Tempail Scraper API

A production-ready Flask REST API that automates the temporary email service
[tempail.com](https://tempail.com/ua/) using Playwright (Chromium).

A single long-lived headless browser session is shared across all API
requests. Playwright's sync API is not thread-safe, so every browser
operation is serialized onto one dedicated worker thread — Flask request
threads simply submit jobs to it and wait.

## Project layout

```
app.py                          # thin WSGI entrypoint
tempail_api/
├── __init__.py                 # create_app() factory
├── config.py                   # ScraperConfig (from env) + logging setup
├── exceptions.py               # domain exceptions
├── extensions.py               # shared scraper singleton lifecycle
├── api/
│   ├── routes.py               # /api blueprint
│   └── errors.py               # global JSON error handlers
└── scraper/
    ├── selectors.py            # every tempail.com CSS selector
    ├── browser.py              # BrowserSession: Playwright lifecycle,
    │                           #   worker thread, crash recovery
    └── tempail.py              # TempailScraper: site interaction logic
```

## API

All responses are JSON.

| Method | Endpoint              | Description                                  |
| ------ | --------------------- | -------------------------------------------- |
| GET    | `/api/health`         | Liveness probe (does not touch the browser)  |
| GET    | `/api/email`          | Current active temporary email address       |
| GET    | `/api/inbox`          | List of received emails (`[]` if empty)      |
| GET    | `/api/email/<id>`     | Full content of one email (text + HTML)      |
| POST   | `/api/email/refresh`  | Discard the address, generate a new one      |

Error responses: `404` (unknown mail id), `503` (upstream timeout /
anti-bot screen), `500` (any other automation failure) — always as
`{"error": "...", "message": "..."}`.

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium --with-deps   # downloads the browser + system libs

# development server
python app.py

# or production-style (must stay at 1 worker — single browser session)
gunicorn --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:8000 app:app
```

## Run with Docker

```bash
docker compose up --build -d
docker compose logs -f tempail-api
```

## Configuration (environment variables)

| Variable            | Default                   | Description                       |
| ------------------- | ------------------------- | --------------------------------- |
| `HEADLESS`          | `true`                    | Run Chromium without a window     |
| `TEMPAIL_BASE_URL`  | `https://tempail.com/ua/` | Target locale/mirror              |
| `USER_AGENT`        | Chrome 124 desktop UA     | Browser User-Agent                |
| `NAV_TIMEOUT_MS`    | `30000`                   | Page navigation timeout           |
| `ACTION_TIMEOUT_MS` | `15000`                   | Selector/action wait timeout      |
| `OP_TIMEOUT_S`      | `60`                      | Hard ceiling per API operation    |
| `INBOX_POLL_INTERVAL_S` | `2`                 | Background inbox refresh interval |
| `USE_PERSISTENT_CONTEXT` | `true`             | Use `launch_persistent_context`   |
| `BROWSER_USER_DATA_DIR` | `/tmp/chromium-profile` | Chromium profile path      |
| `LOG_LEVEL`         | `INFO`                    | Python logging level              |
| `PORT` / `HOST`     | `8000` / `0.0.0.0`        | Dev server bind (local run only)  |

## curl examples

```bash
# Current address
curl -s http://localhost:8000/api/email
# {"email": "abc123@tempail.com"}

# Inbox (empty until something arrives)
curl -s http://localhost:8000/api/inbox
# [{"id": "a1b2c3", "sender": "GitHub", "subject": "Verify your email", "time": "2026-06-10T13:25:00+00:00"}]

# Read one email (id matches tempail slug, e.g. mail_3912965142)
curl -s http://localhost:8000/api/email/mail_3912965142
# {"id": "mail_3912965142", "sender": "...", "subject": "...", "time": "...",
#  "body_text": "...", "body_html": "<div>...</div>"}

# Rotate to a fresh address
curl -s -X POST http://localhost:8000/api/email/refresh
# {"email": "xyz789@tempail.com"}
```

## Performance

`/api/inbox` and `/api/email` read from an in-memory cache updated by a
background browser poller. They **do not** queue Playwright work on the
request path, so responses are typically under 5 ms.

- Chromium boots in the background as soon as the app starts (not on the first
  API call). For a few seconds after container start the inbox may still
  return `[]` while bootstrap finishes.
- New emails show up within `INBOX_POLL_INTERVAL_S` seconds (default 2).
- The first `GET /api/email/<id>` for a message opens it in the browser and
  can take longer; repeat requests for the same id are served from memory.
- `POST /api/email/refresh` clicks tempail's **Delete** button, clears the
  session cookies that bind the old address (`oturum`, `PHPSESSID`), then
  reloads the inbox so the site assigns a new address (keeping `cf_clearance`).

After code changes always rebuild: `docker compose up --build -d`.

## Bypassing tempail.com CAPTCHA (required for Docker)

tempail.com often serves a **reCAPTCHA** page (`Verifying your request…`)
to headless browsers. The inbox never loads, so `#eposta_adres` is not
found and bootstrap fails.

**Fix — export a real browser session once:**

```bash
source .venv/bin/activate
playwright install chromium
python scripts/capture_session.py
```

1. A visible Chromium window opens.
2. Solve the CAPTCHA and dismiss the cookie banner.
3. Wait until the temporary email address appears.
4. Press Enter in the terminal → `storage_state.json` is written.

`docker-compose.yml` mounts `./storage_state.json` read-only (with `:z`
for SELinux on Fedora). An entrypoint copies it to `/tmp/storage_state.json`
inside the container. Re-capture whenever you change `USER_AGENT` or
`HEADLESS` — Cloudflare ties `cf_clearance` to the browser fingerprint.

```bash
HEADLESS=false python scripts/capture_session.py
docker compose up --build -d
docker compose logs tempail-api | rg "storage state"
# → Loading storage state from /app/storage_state.json (N cookies, cf_clearance=True)
```

The API will return `503` with `"error": "anti_bot_challenge"` until a
valid session file is mounted.

## Notes & maintenance

- **Selectors**: tempail.com changes its markup occasionally. Every CSS
  selector lives in `tempail_api/scraper/selectors.py` (each entry is a
  comma-separated fallback chain), so fixes are one-line edits.
- **Anti-bot**: `playwright-stealth` + `launch_persistent_context` (Chromium
  profile on disk) + optional `storage_state.json` seed on first boot. Without a
  saved session, headless Docker is usually blocked by reCAPTCHA. Set
  `USE_PERSISTENT_CONTEXT=false` to fall back to an ephemeral browser context.
- **Full-screen ads**: a `MutationObserver` init script removes
  `#ad_position_box` as soon as it appears; the poller also clicks
  `#dismiss-button` / «Закрити» or force-removes the overlay if needed.
- **Scaling**: the design is intentionally one-browser-per-process. To scale
  horizontally, run multiple containers — each gets its own mailbox.
