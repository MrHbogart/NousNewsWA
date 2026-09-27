import secrets
print("DJANGO_SECRET_KEY=" + secrets.token_urlsafe(50))
print("POSTGRES_PASSWORD=" + secrets.token_urlsafe(32))
print("DJANGO_SUPERUSER_PASSWORD=" + secrets.token_urlsafe(24))
