#!/bin/sh
# The image doesn't set a static Dockerfile USER because the entrypoint needs
# to run as root just long enough to chown the writable static dir on a
# fresh named volume, then drops to the non-root `django` user for
# everything else — migrations, collectstatic, seeding, and the actual
# gunicorn/runserver process. `gosu` (installed in the Dockerfile) does the
# drop.
set -e

APP_USER="${APP_USER:-django}"
STATIC_ROOT="${DJANGO_STATIC_ROOT:-/app/staticfiles}"

run_as_app() {
    if [ "$(id -u)" = "0" ]; then
        gosu "${APP_USER}:${APP_USER}" "$@"
    else
        "$@"
    fi
}

# Same as run_as_app but uses `exec` so the calling shell is replaced.
# Reserved for the final gunicorn/runserver command so signals land on the
# right PID 1.
exec_as_app() {
    if [ "$(id -u)" = "0" ]; then
        exec gosu "${APP_USER}:${APP_USER}" "$@"
    else
        exec "$@"
    fi
}

echo "Preparing static directory..."
mkdir -p "${STATIC_ROOT}"
if [ "$(id -u)" = "0" ]; then
    # Only the directory the app actually writes to — never a recursive
    # chown of /app itself. In dev, /app is the bind-mounted ./backend
    # source tree; recursively chowning it would rewrite the host
    # checkout's file ownership on every container start.
    chown -R "${APP_USER}:${APP_USER}" "${STATIC_ROOT}"
fi

echo "Waiting for the database..."
run_as_app python - <<'PY'
import os
import time
import psycopg

host = os.getenv("DJANGO_DB_HOST", "db")
port = int(os.getenv("DJANGO_DB_PORT", "5432"))
name = os.getenv("DJANGO_DB_NAME", "nousnews")
user = os.getenv("DJANGO_DB_USER", "nousnews")
password = os.getenv("DJANGO_DB_PASSWORD", "nousnews")

for attempt in range(1, 31):
    try:
        with psycopg.connect(host=host, port=port, dbname=name, user=user, password=password):
            break
    except Exception:
        if attempt == 30:
            raise
        time.sleep(1)
PY

if [ "${SKIP_SETUP:-false}" = "true" ]; then
    # The agent worker container shares the backend image; the backend
    # container owns migrations/static/seeding.
    echo "Starting application (setup skipped)..."
    exec_as_app "$@"
fi

echo "Applying database migrations..."
run_as_app python manage.py migrate --noinput

echo "Collecting static files..."
run_as_app python manage.py collectstatic --noinput

echo "Seeding sources..."
run_as_app python manage.py seed_sources

if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "Ensuring superuser exists..."
    run_as_app python manage.py shell <<'PY'
import os
from django.contrib.auth import get_user_model

username = os.environ["DJANGO_SUPERUSER_USERNAME"]
email = os.getenv("DJANGO_SUPERUSER_EMAIL", "admin@example.com")
password = os.environ["DJANGO_SUPERUSER_PASSWORD"]

User = get_user_model()
if not User.objects.filter(username=username).exists() and not User.objects.filter(email=email).exists():
    User.objects.create_superuser(username=username, email=email, password=password)
PY
fi

echo "Starting application..."
exec_as_app "$@"
