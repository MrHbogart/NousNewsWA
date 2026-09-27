import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY or SECRET_KEY in {"change-me", "replace-me-in-production"}:
    if not DEBUG:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY (see passgen.py) before running with DJANGO_DEBUG=false.")
    SECRET_KEY = "insecure-dev-only-key"

# DJANGO_INTERNAL_HOSTS: in-network names (set by docker-compose) so Nuxt SSR
# (http://backend:8000) and the container healthcheck work whatever public
# hosts DJANGO_ALLOWED_HOSTS lists.
ALLOWED_HOSTS = [
    host.strip()
    for host in (
        os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1") + "," + os.getenv("DJANGO_INTERNAL_HOSTS", "")
    ).split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "core.apps.CoreConfig",
    "articles.apps.ArticlesConfig",
    "dataset.apps.DatasetConfig",
    "agent.apps.AgentConfig",
    "prices.apps.PricesConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": os.getenv("DJANGO_DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": os.getenv("DJANGO_DB_NAME", "nousnews"),
        "USER": os.getenv("DJANGO_DB_USER", "nousnews"),
        "PASSWORD": os.getenv("DJANGO_DB_PASSWORD", "nousnews"),
        "HOST": os.getenv("DJANGO_DB_HOST", "db"),
        "PORT": os.getenv("DJANGO_DB_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "agent_control_login": "5/min",
    },
}

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_SSL_REDIRECT", "false").lower() == "true"
SESSION_COOKIE_SECURE = os.getenv("DJANGO_SESSION_COOKIE_SECURE", "false").lower() == "true"
CSRF_COOKIE_SECURE = os.getenv("DJANGO_CSRF_COOKIE_SECURE", "false").lower() == "true"
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "false").lower() == "true"
SECURE_HSTS_PRELOAD = os.getenv("DJANGO_SECURE_HSTS_PRELOAD", "false").lower() == "true"
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https")
    if os.getenv("DJANGO_SECURE_PROXY_SSL_HEADER", "false").lower() == "true"
    else None
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
    },
}

AGENT_LLM_TIMEOUT_SECONDS = float(
    os.getenv("AGENT_LLM_TIMEOUT_SECONDS", os.getenv("CRAWLER_LLM_TIMEOUT_SECONDS", os.getenv("OPENAI_TIMEOUT_SECONDS", "45")))
)
AGENT_FETCH_TIMEOUT_SECONDS = float(
    os.getenv("AGENT_FETCH_TIMEOUT_SECONDS", os.getenv("CRAWLER_FETCH_TIMEOUT_SECONDS", "20"))
)
AGENT_SOURCE_FETCH_WORKERS = int(os.getenv("AGENT_SOURCE_FETCH_WORKERS", "8"))
AGENT_LOG_MAX_CHARS = int(
    os.getenv("AGENT_LOG_MAX_CHARS", os.getenv("CRAWLER_LOG_MAX_CHARS", "200000"))
)
AGENT_LLM_RESERVED_FOR_ARTICLES = int(os.getenv("AGENT_LLM_RESERVED_FOR_ARTICLES", "2"))
AGENT_ENABLE_ECONOMIST_AGENT = os.getenv("AGENT_ENABLE_ECONOMIST_AGENT", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

AGENT_LOG_RETENTION_DAYS = int(os.getenv("AGENT_LOG_RETENTION_DAYS", "14"))
RAW_NEWS_RETENTION_DAYS = int(os.getenv("RAW_NEWS_RETENTION_DAYS", "60"))
CANDLE_RETENTION_DAYS = int(os.getenv("CANDLE_RETENTION_DAYS", "180"))
