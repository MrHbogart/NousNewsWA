import secrets
print("DJANGO_SECRET_KEY=" + secrets.token_urlsafe(50))
print("DJANGO_DB_PASSWORD=" + secrets.token_urlsafe(32))
print("CRAWLER_DB_PASSWORD=" + secrets.token_urlsafe(32))
