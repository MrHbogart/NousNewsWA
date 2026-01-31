# NousNews

Full-stack news platform with a Nuxt 3 frontend, a Django REST API backend, and a crawler pipeline that builds hourly briefs from curated sources.

## Features

- Nuxt 3 SSR frontend with Tailwind styling
- Django REST Framework API
- Postgres-backed crawler, seeds, logs, and exports
- Hourly briefs and headline summaries
- Docker-first deployment with health checks

## Project structure

```
NousNews/
├── backend/               # Django backend
├── frontend/              # Nuxt 3 frontend
├── docker-compose.yml     # Full-stack Docker Compose
└── passgen.py             # Helper for generating secrets
```

## Quick start (Docker)

1) Configure backend and frontend env files:

```bash
cp .env.example backend/.env
cp .env.example frontend/.env
```

2) Start the full stack:

```bash
docker compose up --build
```

Services:
- Frontend: http://127.0.0.1:3001
- Backend API: http://127.0.0.1:8081/api

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
python manage.py runserver
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

Backend (`backend/.env`):
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_DB_*`
- `DJANGO_CORS_ALLOWED_ORIGINS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_SUPERUSER_*` (optional)

Frontend (`frontend/.env`):
- `NUXT_PUBLIC_API_BASE_URL`
- `NUXT_PUBLIC_SITE_DOMAIN`

You can generate secure secrets with:

```bash
python passgen.py
```

## API endpoints

Base URL: `/api`

Articles and briefs:
- `GET /health/`
- `GET /articles/`
- `POST /articles/ingest/`
- `GET /articles/summary/?limit=5`
- `GET /briefs/`
- `GET /briefs/current/`
- `GET /briefs/headlines/?limit=12`
- `GET /briefs/{slug}/`

Crawler:
- `GET /crawler/status/`
- `POST /crawler/run/`
- `GET /crawler/config/`
- `PUT /crawler/config/`
- `GET /crawler/seeds/`
- `POST /crawler/seeds/`
- `GET /crawler/logs/?limit=50`
- `GET /crawler/export.csv`

## Crawler utilities

Backend management commands:
- `python manage.py add_seeds`
- `python manage.py crawl_loop`

## Deployment notes

- The Docker compose file exposes backend on port 8081 and frontend on 3001.
- Use a proper secret for `DJANGO_SECRET_KEY` in production.
- Set `DJANGO_DEBUG=false` and configure allowed hosts and CSRF origins.

## Contributing

Issues and pull requests are welcome. Please include context, steps to reproduce, and screenshots where helpful.
