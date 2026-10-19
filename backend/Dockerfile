# Container image for the crm-lead API and background worker (ADR 0007).
#
# One image, two start commands (set by the host):
#   API:     uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000   (the default below)
#   Worker:  python -m app.worker
#   Release: alembic upgrade head   (run once per deployment, with the schema owner's database URL)
#
# No secrets are baked in: every setting comes from environment variables (see .env.example).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Run as a normal user, not root: a bug in the app can't change the container.
RUN useradd --create-home --uid 10001 crm
WORKDIR /app

# Dependencies first, so rebuilding after a code change reuses this (slow) layer.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts
RUN chown -R crm:crm /app
USER crm

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

# Hosts that set $PORT (Render, Railway, Heroku-style) are honoured; locally it is 8000.
CMD ["sh", "-c", "uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
