#!/bin/sh
# Start command for Render (see render.yaml). The free plan has no background workers, so
# one container runs everything: migrations, the demo seeder and bot simulator in the
# background, and Daphne serving HTTP and WebSockets in the foreground.
set -e

python manage.py migrate --noinput

# Seeding is slow on a small instance, so it runs after the server is up instead of
# delaying it. Once demo data exists, seed_demo exits at once and the simulator starts.
(
  python manage.py seed_demo --days "${SEED_DAYS:-7}" || true
  exec python manage.py simulate --quiet --drivers "${SIM_DRIVERS:-12}"
) &

exec daphne -b 0.0.0.0 -p "${PORT:-8000}" config.asgi:application
