"""Browser end-to-end tests (Playwright + Chromium) against a live Django server.

Run with ``make e2e`` after ``make frontend`` (they use the built React app) and a one-off
``python -m playwright install chromium``. Skipped by the normal test run (``-m "not e2e"``).
"""

import base64
import os

import pytest

# Playwright's sync API keeps an event loop running on the test thread, so Django would refuse
# ORM calls from the test body. They're safe here: nothing else uses this thread.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

# A 1x1 transparent PNG: map tiles are served locally so tests never depend on the internet.
BLANK_TILE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


@pytest.fixture
def page(page):
    page.route(
        "https://tile.openstreetmap.org/**",
        lambda route: route.fulfill(status=200, body=BLANK_TILE, content_type="image/png"),
    )
    page.set_default_timeout(15_000)
    return page
