ARG PYTHON_BASE_IMAGE=python:3.12-slim

FROM ${PYTHON_BASE_IMAGE} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VENV_PATH="/opt/venv"

WORKDIR /app

RUN python -m venv ${VENV_PATH}
ENV PATH="${VENV_PATH}/bin:${PATH}"

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ---------- FINAL STAGE ----------

FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    VENV_PATH="/opt/venv" \
    APP_USER="django"

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends gosu curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder ${VENV_PATH} ${VENV_PATH}
ENV PATH="${VENV_PATH}/bin:${PATH}"

COPY . .

RUN groupadd --system "${APP_USER}" || true && \
    useradd --system --gid "${APP_USER}" --home /home/django --shell /bin/bash "${APP_USER}" || true && \
    mkdir -p /home/django /app/staticfiles && \
    chown -R "${APP_USER}:${APP_USER}" /home/django /app "${VENV_PATH}" && \
    chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
# ASGI so each worker can hold many long-lived SSE connections (/api/stream/*).
# Proxy headers are trusted only from FORWARDED_ALLOW_IPS (env; uvicorn's
# default is 127.0.0.1) — trusting "*" let any client spoof its IP.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--timeout-graceful-shutdown", "10"]
