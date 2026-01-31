#!/bin/sh
set -e

python - <<'PY'
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
        with psycopg.connect(
            host=host,
            port=port,
            dbname=name,
            user=user,
            password=password,
        ):
            break
    except Exception:
        if attempt == 30:
            raise
        time.sleep(1)
PY

python manage.py makemigrations core articles crawler
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py add_seeds
python manage.py shell <<'PY'
import os
from django.contrib.auth import get_user_model

username = os.getenv("DJANGO_SUPERUSER_USERNAME")
email = os.getenv("DJANGO_SUPERUSER_EMAIL")
password = os.getenv("DJANGO_SUPERUSER_PASSWORD")

if username and email and password:
    User = get_user_model()
    exists = User.objects.filter(username=username).exists() or User.objects.filter(email=email).exists()
    if not exists:
        User.objects.create_superuser(username=username, email=email, password=password)
PY

exec "$@"
