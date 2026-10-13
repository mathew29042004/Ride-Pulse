# Ride Pulse

**A full ride-hailing platform: rider app, driver app and operations console**, built on Django,
PostgreSQL and React. Riders book rides with upfront fares and track their driver live; drivers go
online, accept trip offers and start trips with a ride PIN; the operations team watches a live city
map, verifies drivers, tunes surge pricing, handles support and SOS alerts, and reads analytics.

It runs in three cities (Chennai, Bengaluru, Coimbatore) with a bot fleet that drives in real time,
so every screen has something happening the moment you open it.

| | |
| --- | --- |
| **Back end** | Python 3.12 · Django 5.2 LTS · Django REST Framework · Channels (WebSockets) · Celery |
| **Data** | PostgreSQL 16 (partial unique indexes, BRIN, ArrayField, `generate_series` reporting) · Redis |
| **Front end** | React 19 · TypeScript · Vite · Tailwind CSS · TanStack Query · Leaflet / Google Maps · Recharts |
| **API** | 123 REST operations, JWT auth, OpenAPI 3 docs (Swagger UI and ReDoc) |
| **Quality** | 132 tests (88% coverage) + Playwright browser tests + Locust load test · Ruff · strict TypeScript · GitHub Actions · Docker |
| **Ops** | Render blueprint · Sentry · Prometheus `/metrics` · JSON logs · installable PWA |

---

## Quick start

You need Python 3.12 (or [uv](https://docs.astral.sh/uv/)). PostgreSQL and Node.js are installed
into the project's virtualenv, so nothing else is required on the machine.

```bash
make setup     # venv + dependencies, local PostgreSQL, migrations, demo data, React build
make dev       # web server and bot simulator together → http://localhost:8000
```

Or with Docker (Postgres, Redis, web, Celery worker and beat, simulator):

```bash
docker compose up --build
```

### Demo accounts

All demo accounts use the password **`RidePulse@2026`** (created by `make seed`; the login page
has one-click buttons for each).

| Role | Email | Try |
| --- | --- | --- |
| Rider | `rider@ridepulse.dev` | Book a ride from T. Nagar to Marina Beach and watch a bot driver pick you up |
| Driver | `driver@ridepulse.dev` | Go online, tap the map to move, accept a trip, start it with the rider's PIN |
| Operations | `ops@ridepulse.dev` | Live map, trips, driver verification, surge overrides, analytics |
| Support | `support@ridepulse.dev` | Ticket queue, refunds, SOS safety desk |
| Admin | `admin@ridepulse.dev` | Everything, plus the audit trail and the Django admin at `/admin/` |

To play both sides yourself, open the rider app in one tab and the driver app in another: each tab
keeps its own sign-in, and opening an app with the wrong account offers a one-click switch. Put the
driver online near the rider's pickup, then book.

---

## What's inside

### Rider app (phone-style)
Map with nearby cars · "Where to?" search over landmarks, areas and saved places · set pickup or
drop by moving the map under a fixed pin (the address updates as it settles) · upfront fares
for Bike, Auto, Mini, Sedan and SUV with ETAs, surge badge and a line-by-line fare breakdown ·
UPI, card, cash or wallet · promo codes · live tracking with the driver's car moving on the map ·
4-digit ride PIN · in-trip chat with the driver (quick replies, unread badge, notifications; bot
drivers answer) · SOS · rating, tags and tips · PDF receipts · wallet top-ups and dues · help
tickets. Bottom sheets drag between peek, normal and full, with the Book button pinned.

### Driver app (phone-style)
Online/offline with compliance checks (expired documents or unpaid dues block going online) ·
surge zones on the map · trip offers with a chime, vibration and a 20-second countdown ring that
turns amber, then red · chat with the rider · navigate, arrive (only within
500 m of the pickup), start with the PIN, complete · cash-collection prompts · earnings by day,
week and month · payouts · document upload and vehicle registration · safety score and
acceptance rate.

Both apps install as a **PWA** (manifest, icons, a service worker that serves the app shell
offline and never caches live data). Regenerate the icons with `python scripts/make_icons.py`.

### Operations console (desktop)
KPI dashboard · live map of every car and trip (WebSockets with polling fallback) · trip detail
with timeline, GPS route and **dispatch decisions** (who was offered the trip and their ranking
score) · driver verification queue · suspend and reinstate drivers · block riders · surge board
with manual overrides · fare-card editing · promotions · support queue with SLA timers, internal
notes and refunds · SOS desk · payouts and a live ledger integrity check · analytics with a demand
heatmap · CSV export · field-level audit trail.

---

## How it works

```mermaid
flowchart LR
  subgraph Clients
    R[Rider app]
    D[Driver app]
    O[Ops console]
  end
  subgraph Django["Django (ASGI: Daphne)"]
    API[REST API · DRF + JWT]
    WS[WebSockets · Channels]
    SVC[Domain services<br/>dispatch · pricing · payments · support]
  end
  PG[(PostgreSQL 16)]
  RD[(Redis)]
  CW[Celery worker + beat<br/>dispatch sweep · surge · payouts · SLAs]
  SIM[Simulator<br/>bot drivers and riders]
  GM[Google Maps Platform<br/>optional]

  R & D & O -->|HTTPS| API
  R & D & O <-->|live events| WS
  API --> SVC --> PG
  SVC -->|publish after commit| RD --> WS
  CW --> SVC
  SIM --> SVC
  SVC -.->|Routes API| GM
  R & D -.->|Maps JS · Places| GM
```

Business logic lives in plain service functions (`apps/*/services.py`); API views, the simulator,
Celery tasks and the demo seeder all call the same functions, so behaviour is identical everywhere.

### Trip lifecycle

```
REQUESTED ─accept─▶ DRIVER_ASSIGNED ─arrive─▶ DRIVER_ARRIVED ─PIN─▶ IN_PROGRESS ─▶ COMPLETED
    │  ▲                  │                        │
    │  └─driver cancels───┘ (re-dispatched)        │
    ├─▶ NO_DRIVER_FOUND (5-minute timeout)         │
    └──────────────────────────────────────────────┴──▶ CANCELLED (fees by policy)
```

Every transition goes through one state machine (`apps/rides/workflow.py`) and is recorded on the
trip timeline and in the audit trail.

### Dispatch
* **Sequential (default):** candidates come from an index-friendly bounding box on online drivers
  plus an exact haversine distance computed *inside PostgreSQL*. They are ranked by pickup ETA plus
  small "virtual minute" penalties for low ratings, low acceptance and poor safety scores. The best
  driver gets a 20-second offer; declines and timeouts pass it to the next.
* **Batched:** each sweep solves one assignment problem over all open requests and free drivers in
  a city with the **Hungarian algorithm** (`apps/rides/hungarian.py`), minimising total pickup time
  instead of greedily matching one request at a time. It's tested against brute force.
* **Never double-booked:** partial unique indexes allow one active trip per rider and per driver,
  and one pending offer per driver, so even racing workers can't break the rules.

### Pricing
`fare = max(base + km × rate + minutes × rate + paid waiting, minimum) × surge + fees − promo + 5% GST`.
The engine (`apps/pricing/fare.py`) is pure and explains itself line by line. Fares are
**upfront**: the quoted price stands unless the real route is more than 20% longer, or 30% slower,
than estimated. Promotions are funded by the platform, so the driver's earning never shrinks.
**Surge** comes from demand (recent requests) against supply (free drivers) in each zone, smoothed
and capped at 3×; operations can override it for events.

### Money
Every rupee moves through a **double-entry ledger**: each transaction's entries sum to zero, and
wallet balances only change through entries. `GET /api/v1/ledger/` re-verifies both invariants
from the database. Cash trips leave the platform's share as driver dues; failed card payments
become rider dues; payments use **idempotency keys**; weekly payouts can fail and reverse cleanly.

### Real time
Services publish events only **after the database transaction commits** (`transaction.on_commit`),
so a client never hears about a state it can't read. Trip, driver and ops channels authenticate
with the session cookie or a JWT.

Without Redis, events still cross processes: they're published with PostgreSQL **`LISTEN/NOTIFY`**
(`apps/realtime/relay.py`), and each web process relays what it hears to its sockets. So a bot
driver moving in the simulator process reaches the rider's map in milliseconds. With `REDIS_URL`
set, the Redis channel layer does this instead. Every screen also polls as a fallback.

On the map, cars **glide** between GPS updates (each move lasts as long as the gap between
updates, so motion is continuous) and **turn smoothly**. During a trip the car is snapped onto the
route, the part already driven disappears, and the ETA counts the road that's left ("4.6 km left ·
drop by 5:49 pm"). Simulated drivers follow the same route line riders see. Nearby cars carry a
daily-rotating anonymous key, so they can be animated without revealing which driver is which.

### PostgreSQL features used
Partial unique indexes and partial indexes · BRIN indexes for append-only GPS pings and audit logs
· `ArrayField` · `DISTINCT ON` · `generate_series` + `FILTER` for gap-free time series · geohash
prefixes for demand heatmaps · haversine distance in SQL · `INSERT … ON CONFLICT … RETURNING` for
gap-free reference numbers · `SELECT … FOR UPDATE (SKIP LOCKED)` in dispatch.

---

## Google Maps integration

The platform works out of the box with **OpenStreetMap** and built-in route estimates. Add Google
Maps keys and it switches to Google, with no code changes:

| | Without keys | With Google keys |
| --- | --- | --- |
| Map tiles | OpenStreetMap (Leaflet) | Google Maps (`@vis.gl/react-google-maps`), light and dark |
| "Where to?" search | Ride Pulse landmarks and areas | **Google Places Autocomplete**: any address in India |
| Dropped pins | Nearest landmark or area | **Google reverse geocoding** |
| Trip distance and ETA | Straight line × 1.3 road factor, time-of-day speed profile | **Routes API**: real roads, live traffic |
| Route on the map | Smooth arc | **Actual road polyline** (stored with the trip) |

**Setup**
1. In the [Google Cloud console](https://console.cloud.google.com/google/maps-apis), create a
   project with billing, and enable *Maps JavaScript API*, *Places API (New)*, *Geocoding API* and
   *Routes API*.
2. Create two keys:
   * a **browser key** restricted to those browser APIs and your site's referrers
     (`http://localhost:8000/*`);
   * a **server key** restricted to the Routes API and your server's IP.
3. Put them in `.env` as `GOOGLE_MAPS_BROWSER_KEY` and `GOOGLE_MAPS_API_KEY` and restart.

**Built to fail safely.** If the server key fails or is slow (2.5 s timeout), trips fall back to
the built-in estimate. If Google rejects the browser key at runtime (bad key, billing disabled, or
an unauthorised domain), the apps switch to OpenStreetMap instead of breaking. Route lookups are
cached for 5 minutes per origin and destination.

**Cost.** Billing accounts in India get 70,000 free events per month for Dynamic Maps,
Autocomplete, Geocoding, Compute Routes (Essentials) and Route Matrix, and 35,000 for
traffic-aware Compute Routes (Pro). Beyond that, prices start at about $0.85–$3 per 1,000
([India pricing](https://developers.google.com/maps/billing-and-pricing/pricing-india); elsewhere
the free caps are 10,000 and 5,000, see
[global pricing](https://developers.google.com/maps/billing-and-pricing/pricing)). A portfolio demo
stays well inside the free tier. Check the current price lists before running real traffic.

---

## API

* Swagger UI: <http://localhost:8000/api/docs/> · ReDoc: `/api/redoc/` · schema: `/api/schema/`
* Authenticate with `POST /api/v1/auth/token/` and send `Authorization: Bearer <access>`.
* Errors share one envelope: `{"error": {"code", "message", "field", "details"}}`.

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/token/ -H 'Content-Type: application/json' \
  -d '{"email":"rider@ridepulse.dev","password":"RidePulse@2026"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access"])')

curl -s -X POST localhost:8000/api/v1/fares/estimate/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"pickup":{"lat":13.0418,"lng":80.2341},"dropoff":{"lat":13.05,"lng":80.2824}}'
```

Access is **capability-based**: roles map to capabilities (`trips.manage`, `payments.refund`, …)
in one place (`apps/accounts/roles.py`), views declare what each action needs, and anything
unmapped is denied. Riders and drivers only ever see their own records.

### More rider features
* **Share trip:** a public "follow my ride" link (`/track/<token>`) shows the car, driver and
  plate live, with no login; no phone numbers, PIN or fare, and it expires an hour after the ride.
* **Schedule a ride** up to 7 days ahead. A background job (`dispatch_scheduled_rides`, every
  minute, `SKIP LOCKED` so several workers never double-book) turns it into a normal trip
  request eight minutes before pickup, or tells the rider why it couldn't.
* **A stop on the way:** fares, distance and ETA cover both legs plus a stop allowance; road
  polylines are joined; bots drive through the stop.
* **Referrals:** invite links pre-fill the code; after the friend's first ride both wallets get
  ₹50 from the promotions budget, as one balanced ledger transaction, exactly once.
* **Razorpay** for wallet top-ups (test or live keys in `.env`): the server creates the order,
  Checkout takes the payment, and the wallet is credited only after the HMAC signature is
  verified, by the browser callback or the `payment.captured` webhook, whichever is first.

---

## Deploy

**Render (free plan):** push the repo to GitHub, then in Render choose *New → Blueprint* and pick
the repository. `render.yaml` creates the web service (Docker) and a PostgreSQL database; the
start script migrates, seeds demo data and runs the bot simulator next to the server. Real-time
updates work without Redis thanks to the PostgreSQL relay. Optional keys (Google Maps, Razorpay,
Sentry, metrics token) are set in the Render dashboard, never in git.

**Anywhere with Docker:** `docker compose up --build` runs the full stack (Postgres, Redis, web,
Celery worker and beat, simulator).

### Production checklist
* `python manage.py check --deploy` passes with `config.settings.prod` (HSTS, secure cookies,
  SSL redirect, `X-Frame-Options`, content-type sniffing off).
* **Errors:** set `SENTRY_DSN` to report exceptions (no personal data sent).
* **Metrics:** Prometheus scrapes `/metrics` with `METRICS_TOKEN`: request counts and latency
  histograms per view, plus live business gauges (trips by status, drivers by availability, open
  tickets, scheduled rides waiting, ledger balanced).
* **Logs:** `LOG_FORMAT=json` writes one JSON object per line, each tagged with the request id
  that is also returned as `X-Request-ID`.
* **Load:** 30 concurrent riders against the dev server: 0 failures, median 15 ms, p95 140 ms
  (login dominates, by design: password hashing is slow on purpose).

---

## Development

```bash
make help        # all commands
make test        # 132 tests (unit, integration on PostgreSQL, API, WebSocket, seed)
make e2e         # browser tests: Playwright drives Chromium through a full trip
make loadtest    # Locust: 50 riders browsing fares and cars for a minute
make lint        # Ruff + TypeScript type-check
make check       # everything CI runs, plus migration and OpenAPI checks
make frontend-dev   # Vite with hot reload on :5173, proxying the API to :8000
make reset       # wipe and reseed the demo (three weeks of history in about 40 s)
```

| Path | What lives there |
| --- | --- |
| `apps/rides` | trip model, state machine, dispatch, Hungarian assignment, receipts |
| `apps/pricing` | fare engine, surge, promotions, fare cards |
| `apps/payments` | double-entry ledger, wallets, gateway, payouts |
| `apps/drivers` · `apps/riders` | onboarding, documents, availability, GPS, safety score |
| `apps/support` | tickets, SLAs, refunds, SOS incidents |
| `apps/geo` | cities, zones, landmarks, routing, Google Routes client, geohash |
| `apps/realtime` | WebSocket consumers, broadcasting, PostgreSQL LISTEN/NOTIFY relay |
| `apps/analytics` | KPIs, time series, heatmaps, CSV export |
| `apps/audit` · `apps/notifications` | audit trail with field diffs, in-app and email notifications |
| `apps/simulation` | demo-history seeder and the live bot simulator |
| `frontend/src` | React apps: `pages/rider`, `pages/driver`, `pages/ops`, map abstraction in `components/map` |

Fares, drivers, riders and trips are simulated; payments go through a mock gateway (any UPI ID
containing `fail` is declined, to exercise the failure path).
