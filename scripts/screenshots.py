#!/usr/bin/env python
"""Take the README screenshots from the running app (``make dev`` first).

    .venv/bin/python scripts/screenshots.py [--base http://localhost:8000]

Signs in with the demo accounts and saves JPEGs to docs/screenshots/. Needs Playwright's
Chromium once: ``.venv/bin/python -m playwright install chromium``.
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}


def demo_password() -> str:
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    import django

    django.setup()
    from apps.simulation.seed import DEMO_PASSWORD

    return DEMO_PASSWORD


def tokens(base: str, email: str, password: str) -> dict:
    request = urllib.request.Request(
        f"{base}/api/v1/auth/token/",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read())


def shoot(browser, base, auth, path, name, *, viewport=DESKTOP, wait="networkidle", settle=2500):
    context = browser.new_context(viewport=viewport, device_scale_factor=1, color_scheme="dark")
    layout = "phone" if viewport is PHONE else "desktop"
    context.add_init_script(
        f"localStorage.setItem('rp.access', {json.dumps(auth['access'])});"
        f"localStorage.setItem('rp.refresh', {json.dumps(auth['refresh'])});"
        f"localStorage.setItem('rp.layout', {json.dumps(layout)});"
    )
    page = context.new_page()
    page.goto(f"{base}{path}", wait_until=wait)
    page.wait_for_timeout(settle)  # map tiles and the sheet animation
    page.screenshot(path=str(OUT / f"{name}.jpg"), type="jpeg", quality=82)
    context.close()
    print(f"  {name}.jpg")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    args = parser.parse_args()
    base = args.base
    from playwright.sync_api import sync_playwright

    password = demo_password()
    rider = tokens(base, "rider@ridepulse.dev", password)
    driver = tokens(base, "driver@ridepulse.dev", password)
    admin = tokens(base, "admin@ridepulse.dev", password)
    OUT.mkdir(parents=True, exist_ok=True)
    drop = "to=13.0500,80.2824&name=Marina%20Beach"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        shoot(browser, base, rider, "/ride", "rider-home")
        shoot(browser, base, rider, f"/ride/book?{drop}&type=MINI", "rider-book")
        shoot(browser, base, rider, "/ride/book?service=PARCEL&" + drop, "rider-parcel")
        shoot(browser, base, rider, "/ride/packages?service=INTERCITY", "rider-intercity")
        shoot(browser, base, rider, "/ride", "rider-home-phone", viewport=PHONE)
        shoot(
            browser, base, rider, f"/ride/book?{drop}&type=MINI", "rider-book-phone", viewport=PHONE
        )
        shoot(browser, base, driver, "/drive", "driver-home")
        shoot(browser, base, driver, "/drive/earnings", "driver-earnings")
        shoot(browser, base, admin, "/ops", "ops-dashboard")
        shoot(browser, base, admin, "/ops/live", "ops-live-map")
        shoot(browser, base, admin, "/ops/insights", "ops-data-insights", settle=3500)
        shoot(browser, base, admin, "/ops/team", "ops-team")
        browser.close()


if __name__ == "__main__":
    main()
