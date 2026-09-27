# Development workflow

## Docker (recommended)

```bash
cp .env.example .env
docker compose up --build                                            # prod-like
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build   # hot reload
```

Backend: http://127.0.0.1:8081/api (port from `BACKEND_HOST_PORT`).
Frontend: http://127.0.0.1:3001 (port from `FRONTEND_HOST_PORT`).

The backend entrypoint (`backend/entrypoint.sh`) waits for Postgres, runs
`migrate --noinput`, `collectstatic`, `seed_sources`, and optionally creates
a superuser (only if both `DJANGO_SUPERUSER_USERNAME` and
`DJANGO_SUPERUSER_PASSWORD` are set) — then execs uvicorn (ASGI, needed for
the SSE endpoints) as the non-root `django` user. The `agent` service reuses
the backend image with `SKIP_SETUP=true` (setup is the backend's job) and
runs `python manage.py run_forever`.

## Bare metal

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
python manage.py migrate
python manage.py seed_sources
uvicorn config.asgi:application --reload   # not runserver: it can't stream SSE
python manage.py run_forever                # agent worker, second shell
```

```bash
cd frontend
npm install
cp ../.env.example .env   # then edit NUXT_PUBLIC_API_BASE_URL etc. for your local ports
npm run dev
```

## Changing a model

1. Edit the model.
2. `python manage.py makemigrations <app>` — run this locally (bare metal or
   `docker compose exec backend ...`), not by relying on container startup.
3. Commit the generated migration file alongside the model change.
4. `python manage.py migrate` to apply it locally before testing.

## Verifying a change

There is no CI. Before calling backend work done, run:

```bash
python manage.py test                               # agent/tests.py, agent/test_pipeline.py, articles/tests.py
python manage.py check
python manage.py makemigrations --check --dry-run   # catches missing migrations
python -m pyflakes .                                # catches unused imports/undefined names
```

`pyflakes` isn't in `requirements.txt` (it's a lint tool, not a runtime dep) —
`pip install pyflakes` into your venv/container to use it. It caught two real
undefined-name bugs and a dozen unused imports during the `agent/services.py`
→ `agent/services/` split (see `decisions/known-issues.md`) — worth running
after any multi-file move, not just single-file edits.

For anything touching `agent/services/`, also exercise the real path: run
the stack, `POST /api/agent/control/run-once/` (or set
`run_once_requested` in admin) and watch the `agent` container logs and
`/api/agent/control/logs/`. Tests mock the network; they won't catch a
broken feed or LLM call. For frontend changes, `npm run build` must pass.
