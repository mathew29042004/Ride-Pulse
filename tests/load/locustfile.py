"""Load test: riders opening the app, browsing fares and checking on cars, like real traffic.

    python manage.py loadtest_users --count 50
    locust -f tests/load/locustfile.py --host http://localhost:8000 \\
        --users 50 --spawn-rate 10 --run-time 1m --headless

(``make loadtest`` does both.) Bookings aren't included on purpose: each rider can only have one
active trip, and fare estimates are the expensive, high-volume read in a ride-hailing app.
"""

import itertools
import os
import random

from locust import HttpUser, between, task

PASSWORD = os.environ.get("LOADTEST_PASSWORD", "loadtest-pass-2026")
_ids = itertools.count()

# Pickup and drop points around Chennai (all inside the service area).
SPOTS = [
    (13.0418, 80.2341),  # T. Nagar
    (13.0500, 80.2824),  # Marina Beach
    (13.0827, 80.2757),  # Chennai Central
    (13.0850, 80.2101),  # Anna Nagar
    (12.9941, 80.1709),  # Airport
    (13.0067, 80.2206),  # Guindy
    (12.9010, 80.2279),  # Sholinganallur
]


class Rider(HttpUser):
    wait_time = between(1, 4)

    def on_start(self):
        n = next(_ids) % int(os.environ.get("LOADTEST_USERS", "50"))
        response = self.client.post(
            "/api/v1/auth/token/",
            json={"email": f"loadtest+{n}@ridepulse.dev", "password": PASSWORD},
            name="auth/token",
        )
        response.raise_for_status()
        self.client.headers["Authorization"] = f"Bearer {response.json()['access']}"
        self.home = random.choice(SPOTS)

    @task(5)
    def nearby_cars(self):
        lat, lng = self.home
        self.client.get(f"/api/v1/fares/nearby-drivers/?lat={lat}&lng={lng}", name="nearby-drivers")

    @task(3)
    def fare_estimate(self):
        dropoff = random.choice([s for s in SPOTS if s != self.home])
        self.client.post(
            "/api/v1/fares/estimate/",
            json={
                "pickup": {"lat": self.home[0], "lng": self.home[1]},
                "dropoff": {"lat": dropoff[0], "lng": dropoff[1]},
            },
            name="fares/estimate",
        )

    @task(2)
    def active_trip(self):
        self.client.get("/api/v1/trips/active/", name="trips/active")

    @task(1)
    def history_and_wallet(self):
        self.client.get("/api/v1/trips/?page_size=10", name="trips/list")
        self.client.get("/api/v1/wallet/", name="wallet")

    @task(1)
    def open_app(self):
        self.client.get("/api/config/", name="config")
        self.client.get("/api/v1/auth/me/", name="auth/me")
