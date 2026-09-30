# NousNews

Full-stack news platform with a Nuxt 3 frontend, a Django REST API backend, and a agent pipeline that builds hourly briefs from curated sources.

## Features

- Nuxt 3 SSR frontend with Tailwind styling
- Django REST Framework API
- Postgres-backed agent, seeds, logs, and exports
- Hourly briefs and headline summaries
- Docker-first deployment with health checks

## Project structure

```
NousNews/
├── backend/                   # Django backend
├── frontend/                  # Nuxt 3 frontend
├── claude/                    # Claude Code project docs (start at claude/CLAUDE.md)
├── docker-compose.yml         # Full-stack Docker Compose
├── docker-compose.dev.yml     # Dev overlay: bind mounts, hot reload
├── .env.example                # Env template (copy to .env)
└── passgen.py                  # Helper for generating secrets
```

## Quick start (Docker)

1) Configure the environment file:

```bash
cp .env.example .env
```

2) Start the full stack:

```bash
docker compose up --build
```

For local development with hot reload and bind-mounted source, layer the dev
overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Services:
- Frontend: http://127.0.0.1:3001
- Backend API: http://127.0.0.1:8081/api
- Agent worker: `agent` container (no port; controlled from `/agent-control`
  or Django admin)

Optional: create a Django superuser in Docker by setting these in `backend/.env`:

```
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@example.com
DJANGO_SUPERUSER_PASSWORD=change-me
```

## Local development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
python manage.py migrate
python manage.py seed_sources
uvicorn config.asgi:application --reload   # runserver can't stream SSE
python manage.py run_forever                # agent worker, in a second shell
```

The API will be available at http://127.0.0.1:8000/api

Create an admin user if needed:

```bash
python manage.py createsuperuser
```

### Frontend

```bash
cd frontend
npm install
cp ../.env.example .env
```

For local development, set these in `frontend/.env` to match your local ports:

```
NUXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api
NUXT_PUBLIC_SITE_DOMAIN=http://127.0.0.1:3000
```

Then start the dev server:

```bash
npm run dev
```

## Environment variables

See `.env.example` for the full list with defaults and comments. In Docker,
one root `.env` feeds every service; `POSTGRES_*` is the source of truth for
the database and is mapped into `DJANGO_DB_*` for the backend by
`docker-compose.yml`. For bare-metal local dev, copy `.env.example` into
`backend/.env` and `frontend/.env` instead (each app's `.env` loader only
reads its own directory).

Key groups:
- `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD`
- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CORS_ALLOWED_ORIGINS`, `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_SUPERUSER_*` (optional — leave `DJANGO_SUPERUSER_USERNAME`/
  `_PASSWORD` blank to skip creating an admin account)
- `NUXT_PUBLIC_API_BASE_URL`, `NUXT_PUBLIC_SITE_DOMAIN`

You can generate secure secrets with:

```bash
python passgen.py
```

## API endpoints

Base URL: `/api` (see `backend/config/urls.py` for the top-level include list).

Articles and briefs (`backend/articles/urls.py`):
- `GET /health/` — always 200 while the API is up; `agent` reports whether
  the worker is alive and when it last ran news/price syncs
- `GET /lasthour/`
- `GET /briefs/?page=0&limit=10` — final briefs of every timeframe, newest
  period end first
- `GET /articles/{uuid-or-slug}/`

Live updates (Server-Sent Events, `backend/articles/stream.py`):
- `GET /stream/home/` — `event: home` with `{lasthour, briefs}` on connect
  and whenever content changes; `event: prices` with `{id, price_series}`
  for the current hour's brief on every price tick; `: ping` every 15s
- `GET /stream/articles/{uuid-or-slug}/` — `event: article` on connect and
  on change; `event: prices` for that article's charts on every price tick
- Both are pushed via Postgres `LISTEN/NOTIFY` (well under a second after a
  write); the worker syncs prices every `price_loop_interval_seconds`
  (default 15s), independent of the news run

Agent (`backend/agent/urls.py`; all need a control token from
`POST /agent/control/login/`, sent as `Authorization: Bearer <token>`):
- `GET|PUT /agent/config/` (`llm_base_url` is read-only here; set it in
  Django admin)
- `GET /agent/logs/`
- `GET /agent/control/state/`, `/stats/`, `/logs/`, `/dashboard/`
- `POST /agent/control/start/`, `/run-once/`, `/pause/`, `/resume/`,
  `/stop/` — these only set flags; the `agent` worker container applies
  them within about a second

Prices (`backend/prices/urls.py`, mounted at `/api/prices/`):
- `GET /health/`
- `GET /series/`
- `GET /series/{symbol}/latest/`

Frontend server routes: `/sitemap.xml`, `/rss.xml`, `/robots.txt`.

## Agent worker and commands

The agent runs as its own compose service (`agent`, `python manage.py
run_forever`), not inside the web process. It polls `AgentConfig` every
second: `run_forever_enabled` / `run_forever_paused` / `run_once_requested`
are the control flags, and it writes its heartbeat to the `AgentWorker` row.
It also prunes old data once a day.

Backend management commands:
- `python manage.py seed_sources` — load default news/price sources (never
  overwrites an existing `AgentConfig`)
- `python manage.py run_forever` — the agent worker
- `python manage.py sync_price_feeds` — one-off price sync
- `python manage.py prune_data` — delete logs/raw news/candles past
  retention (`AGENT_LOG_RETENTION_DAYS`, `RAW_NEWS_RETENTION_DAYS`,
  `CANDLE_RETENTION_DAYS`)

## Deployment notes

- The Docker compose file exposes backend on port 8081 and frontend on 3001.
- `DJANGO_SECRET_KEY` is required when `DJANGO_DEBUG=false`; the backend
  refuses to start with a missing or placeholder key.
- The backend serves ASGI via uvicorn (needed for SSE). If a reverse proxy
  sits in front, disable response buffering for `/api/stream/` (the app
  already sends `X-Accel-Buffering: no`).
- Set `DJANGO_DEBUG=false` and configure allowed hosts and CSRF origins.

## Contributing

Issues and pull requests are welcome. Please include context, steps to reproduce, and screenshots where helpful.
