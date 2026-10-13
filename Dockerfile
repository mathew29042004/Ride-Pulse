# syntax=docker/dockerfile:1

# --- 1. Build the React apps ---------------------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# --- 2. Python runtime ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app
RUN useradd --create-home --uid 10001 ridepulse

COPY requirements/base.txt requirements/base.txt
RUN pip install -r requirements/base.txt

COPY . .
COPY --from=frontend /app/frontend/dist ./frontend/dist

# collectstatic needs settings but no real secrets or database.
RUN DJANGO_SECRET_KEY=build-only DJANGO_ALLOWED_HOSTS=localhost python manage.py collectstatic --noinput

USER ridepulse
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/')"

# Daphne serves HTTP and WebSockets from the same ASGI application.
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
