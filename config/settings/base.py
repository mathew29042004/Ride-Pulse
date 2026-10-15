"""Settings shared by every environment. Environment-specific modules import * from here."""

from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-ride-pulse-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
# Demo mode: the demo seeders (seed_demo, grow_network, generate_history) and the bot simulator
# only run when this is on. They create logins with a published password and can wipe data, so
# a real deployment must leave it off. On by default for local development (DEBUG).
DEMO_MODE = env.bool("DEMO_MODE", default=DEBUG)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "daphne",  # must precede staticfiles: `runserver` then serves ASGI incl. WebSockets
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",
    # Third party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "django_filters",
    "corsheaders",
    "channels",
    # Ride Pulse domains
    "apps.core",
    "apps.accounts",
    "apps.audit",
    "apps.notifications",
    "apps.geo",
    "apps.riders",
    "apps.drivers",
    "apps.pricing",
    "apps.rides",
    "apps.payments",
    "apps.support",
    "apps.analytics",
    "apps.realtime",
    "apps.simulation",
    "apps.portal",
    "apps.workspace",
    "apps.intelligence",
    "apps.fleet",
    "apps.reliability",
    "apps.trust",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestContextMiddleware",
    "apps.core.metrics.MetricsMiddleware",
]

# Prometheus scrapes /metrics with "Authorization: Bearer <METRICS_TOKEN>".
METRICS_TOKEN = env("METRICS_TOKEN", default="")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.portal.context_processors.portal",
            ],
        },
    },
]

# --- Database ------------------------------------------------------------------------------
# PostgreSQL only: the schema relies on partial unique indexes, ArrayField, full-text search,
# BRIN indexes, DISTINCT ON and generate_series() reporting queries.
DATABASES = {
    "default": env.db(
        "DATABASE_URL", default="postgres://ridepulse:ridepulse@127.0.0.1:5433/ridepulse"
    )
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth ----------------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- I18N ----------------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# --- Static and media ----------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static", ("app", BASE_DIR / "frontend" / "dist")]
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# --- Cache ---------------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="")
if REDIS_URL:
    CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# --- Email ---------------------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Ride Pulse <no-reply@ridepulse.local>")
# Real delivery (e.g. Gmail): EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend plus these.
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_TIMEOUT = 10

# --- REST API ------------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "3000/hour",
        "fare_estimate": "120/min",
        "location": "240/min",
        "registration": "10/hour",
        "otp": "10/min",
        "login": "20/min",
        "booking": "30/hour",
    },
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Ride Pulse API",
    "DESCRIPTION": (
        "REST API for the Ride Pulse ride-hailing platform: riders, drivers and onboarding, "
        "fare estimates and surge pricing, trip booking and dispatch, payments and wallets, "
        "support and safety, and analytics. Live updates are pushed over WebSockets "
        "(`/ws/trips/<id>/`, `/ws/driver/`, `/ws/ops/`).\n\n"
        "Authenticate with `POST /api/v1/auth/token/` and send `Authorization: Bearer <access>`."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "ENUM_NAME_OVERRIDES": {
        "RoleEnum": "apps.accounts.models.Role",
        "TripStatusEnum": "apps.rides.models.TripStatus",
        "PaymentMethodEnum": "apps.payments.models.PaymentMethod",
        "DriverAvailabilityEnum": "apps.drivers.models.Availability",
        "OnboardingStatusEnum": "apps.drivers.models.OnboardingStatus",
        "TicketStatusEnum": "apps.support.models.TicketStatus",
        "WorkTaskStatusEnum": "apps.workspace.models.TaskStatus",
        "MeetingStatusEnum": "apps.workspace.models.MeetingStatus",
        "DataRequestKindEnum": "apps.trust.models.RequestKind",
        "ClaimKindEnum": "apps.trust.models.ClaimKind",
        "TaskUpdateStatusEnum": [("IN_PROGRESS", "IN_PROGRESS"), ("DONE", "DONE")],
        "OnlinePaymentMethodEnum": [("UPI", "UPI"), ("CARD", "CARD"), ("WALLET", "WALLET")],
        "ParcelCategoryEnum": "apps.rides.models.ParcelCategory",
        "ServiceEnum": [
            ("RIDE", "RIDE"),
            ("PARCEL", "PARCEL"),
            ("RENTAL", "RENTAL"),
            ("INTERCITY", "INTERCITY"),
        ],
        "PackageServiceEnum": [("RENTAL", "RENTAL"), ("INTERCITY", "INTERCITY")],
        "EstimateServiceEnum": [("RIDE", "RIDE"), ("PARCEL", "PARCEL")],
        "TicketCategoryEnum": "apps.support.models.TicketCategory",
    },
}

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

# --- Celery --------------------------------------------------------------------------------
# Without a broker, tasks run inline so the whole app works with nothing but PostgreSQL.
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="") or None
CELERY_TASK_ALWAYS_EAGER = not CELERY_BROKER_URL
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BEAT_SCHEDULE = {
    "outbox-relay": {"task": "reliability.relay_outbox", "schedule": timedelta(seconds=10)},
    "trust-privacy": {"task": "trust.privacy_daily", "schedule": crontab(hour=3, minute=15)},
    "fleet-upkeep": {"task": "fleet.upkeep_sweep", "schedule": crontab(hour=7, minute=30)},
    "fleet-quests": {"task": "fleet.end_quests", "schedule": timedelta(minutes=15)},
    "intel-weather": {"task": "intelligence.refresh_weather", "schedule": timedelta(minutes=30)},
    "intel-alerts": {"task": "intelligence.check_alerts", "schedule": timedelta(minutes=5)},
    "intel-nudges": {"task": "intelligence.nudge_drivers", "schedule": timedelta(minutes=10)},
    "intel-fraud": {"task": "intelligence.fraud_scan", "schedule": timedelta(hours=1)},
    "intel-briefing": {
        "task": "intelligence.morning_briefing",
        "schedule": crontab(hour=8, minute=0),
    },
    "work-overdue": {"task": "workspace.flag_overdue", "schedule": timedelta(minutes=5)},
    "work-standups": {"task": "workspace.roll_daily_standups", "schedule": timedelta(minutes=15)},
    "dispatch-sweep": {"task": "rides.dispatch_sweep", "schedule": timedelta(seconds=10)},
    "scheduled-rides": {"task": "rides.dispatch_scheduled_rides", "schedule": timedelta(minutes=1)},
    "surge-recompute": {"task": "pricing.recompute_surge", "schedule": timedelta(minutes=2)},
    "price-alerts": {"task": "pricing.check_price_alerts", "schedule": timedelta(minutes=2)},
    "ride-checks": {"task": "rides.run_ride_checks", "schedule": timedelta(minutes=1)},
    "driver-wellbeing": {"task": "drivers.wellbeing_sweep", "schedule": timedelta(minutes=5)},
    "city-coverage": {"task": "pricing.sync_city_coverage", "schedule": crontab(hour=5, minute=0)},
    "stale-drivers-offline": {
        "task": "drivers.mark_stale_drivers_offline",
        "schedule": timedelta(minutes=5),
    },
    "document-expiry": {
        "task": "drivers.check_document_expiry",
        "schedule": crontab(hour=6, minute=0),
    },
    "purge-location-pings": {
        "task": "drivers.purge_location_pings",
        "schedule": crontab(hour=3, minute=30),
    },
    "weekly-payouts": {
        "task": "payments.create_weekly_payouts",
        "schedule": crontab(day_of_week="mon", hour=4, minute=0),
    },
    "support-sla": {"task": "support.escalate_sla_breaches", "schedule": crontab(minute="*/15")},
}

# --- Logging -------------------------------------------------------------------------------
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_context": {"()": "apps.core.logging.RequestContextFilter"}},
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s",
        },
        "json": {"()": "apps.core.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            # LOG_FORMAT=json in production: one structured object per line.
            "formatter": "json" if env("LOG_FORMAT", default="text") == "json" else "standard",
            "filters": ["request_context"],
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apps": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

# --- Ride Pulse business configuration -----------------------------------------------------
RIDE_PULSE = {
    "COMPANY_NAME": "Ride Pulse Mobility",
    # Shown on invoices. Demo values: set the real GSTIN and registered address in production.
    "COMPANY_GSTIN": env("COMPANY_GSTIN", default="33AABCR1234F1Z5"),
    "COMPANY_ADDRESS": env("COMPANY_ADDRESS", default="Anna Salai, Chennai, Tamil Nadu 600002"),
    "SUPPORT_EMAIL": env("SUPPORT_EMAIL", default="support@ridepulse.dev"),
    "CURRENCY_SYMBOL": "₹",
    "GST_RATE": "0.05",  # GST on ride-hailing services in India
    "PLATFORM_COMMISSION_PERCENT": "20",
    "DISPATCH_MODE": env("DISPATCH_MODE", default="SEQUENTIAL"),  # or BATCHED
    "DISPATCH_RADIUS_KM": "5",
    "DISPATCH_MAX_RADIUS_KM": "8",
    "OFFER_TIMEOUT_SECONDS": 20,
    "REQUEST_TIMEOUT_SECONDS": 300,
    "LOCATION_STALE_SECONDS": 180,
    "ARRIVAL_RADIUS_METERS": 500,
    "FREE_CANCELLATION_SECONDS": 120,
    "MAX_DRIVER_DUES": "500",
    "ROAD_DISTANCE_FACTOR": "1.3",
    "SURGE_MAX_MULTIPLIER": "3.0",
    "SURGE_WINDOW_MINUTES": 10,
    "SURGE_SMOOTHING": "0.5",
    "UPFRONT_DISTANCE_TOLERANCE": "1.2",
    "UPFRONT_DURATION_TOLERANCE": "1.3",
    "PAYOUT_MINIMUM": "100",
    "REFERRAL_BONUS": "50",  # each, to the inviter and the new rider, after their first trip
    # Ride Pass (monthly subscription): price, length, % off each ride (capped), no booking fee.
    "RIDE_PASS_PRICE": "99",
    "RIDE_PASS_DAYS": 30,
    "RIDE_PASS_PERCENT": "10",
    "RIDE_PASS_MAX_DISCOUNT": "30",
    # Driver daily goals: (trips completed today, bonus for reaching it). Bonuses add up.
    # Public address of the site, used in links sent by SMS (trusted contacts).
    "APP_URL": env("APP_URL", default="http://localhost:8000"),
    # Night Safe mode (local hours) and Ride Check thresholds: (normal, night).
    "NIGHT_SAFE_HOURS": [22, 6],
    "RIDE_CHECK_STOP_MINUTES": [5, 3],
    "RIDE_CHECK_OFF_ROUTE_KM": ["2.0", "1.0"],
    "RIDE_CHECK_ANSWER_MINUTES": 3,
    "DRIVER_GOALS": [[5, "75"], [10, "125"]],
    # Driver Wellbeing: a 20-minute break after 6 hours of driving (gaps under 20 min don't
    # count as rest), a warning 30 minutes before, and a rest bonus once a day for a proper
    # break after 4+ hours.
    # Bid your fare: the rider may offer 85% – 150% of the upfront price; drivers can counter
    # with these steps; the rider has 2 minutes to take a counter-offer.
    "FARE_OFFER_RANGE": ["0.85", "1.50"],
    "COUNTER_STEPS": ["10", "20", "30"],
    "COUNTER_VALID_SECONDS": 120,
    # Sure Ride: a small fee for "driver within N minutes or ₹30 back" (N = ETA + buffer).
    "SURE_RIDE_FEE": "5",
    "SURE_RIDE_REFUND": "30",
    "SURE_RIDE_BUFFER_MINUTES": 4,
    "SURE_RIDE_MIN_MINUTES": 6,
    # Hourly rentals: (hours, km included) packages; per-hour price and overage per car type
    # (scaled by the city's fare multiplier).
    "RENTAL_PACKAGES": [[1, 10], [2, 20], [4, 40], [8, 80]],
    "RENTAL_RATES": {
        "MINI": {"hour": "280", "extra_km": "12", "extra_min": "2"},
        "SEDAN": {"hour": "340", "extra_km": "14", "extra_min": "2.5"},
        "SUV": {"hour": "450", "extra_km": "18", "extra_min": "3"},
    },
    # Intercity (outstation): per km, with minimum billed km, and a daily driver allowance
    # (100% to the driver). Tolls and parking are paid by the rider on the way.
    "INTERCITY_PER_KM": {"MINI": "11", "SEDAN": "13", "SUV": "17"},
    "INTERCITY_MIN_KM_ONE_WAY": 100,
    "INTERCITY_MIN_KM_PER_DAY": 250,
    "INTERCITY_DRIVER_ALLOWANCE": "300",
    "INTERCITY_RANGE_KM": [40, 600],
    # Zero-commission day pass for drivers: flat price per day by vehicle.
    "DRIVER_DAY_PASS": {"BIKE": "19", "AUTO": "29", "MINI": "49", "SEDAN": "49", "SUV": "59"},
    # Fare Lock: fix a commute's normal price for a week (±60 min of the time, chosen weekdays).
    "FARE_LOCK_FEE": "49",
    "FARE_LOCK_DAYS": 7,
    "FARE_LOCK_WINDOW_MINUTES": 60,
    "FARE_LOCK_MATCH_METERS": 400,
    # Eco score: grams of CO2 per km for each vehicle (per trip, shared by its riders) vs the
    # rider driving their own petrol car alone; 1 point per 100 g saved; 100 points = ₹10.
    "ECO_BASELINE_G_PER_KM": 170,
    "ECO_G_PER_KM": {"BIKE": 45, "AUTO": 70, "MINI": 120, "SEDAN": 140, "SUV": 180, "EV": 20},
    "ECO_POINTS_PER_100G": 1,
    "ECO_REDEEM": [100, "10"],
    "WELLBEING_MAX_DRIVING_MINUTES": 360,
    "WELLBEING_BREAK_MINUTES": 20,
    "WELLBEING_WARN_MINUTES": 30,
    "WELLBEING_BONUS_AFTER_MINUTES": 240,
    "WELLBEING_REST_BONUS": "10",
    # Rough running cost per km (fuel/charge + upkeep) for the drivers' real hourly earnings.
    "RUNNING_COST_PER_KM": {"BIKE": "2.2", "AUTO": "3.5", "MINI": "6", "SEDAN": "7", "SUV": "9"},
    "GOING_HOME_PER_DAY": 2,
    "GOING_HOME_MINUTES": 60,
    "LOCATION_PING_RETENTION_DAYS": 7,
    "TICKET_SLA_HOURS": {"URGENT": 1, "HIGH": 4, "NORMAL": 24, "LOW": 72},
    # TDS under section 194-O (e-commerce operators): 0.1% of gross fares from 1 Oct 2024, or
    # 5% when the driver has no PAN on file (section 206AA). Deducted with the weekly statement.
    "TDS_RATE_WITH_PAN": "0.001",
    "TDS_RATE_WITHOUT_PAN": "0.05",
    # Fleet owners keep this share of their drivers' trip earnings (set per owner, default).
    "FLEET_OWNER_SHARE_PERCENT": "20",
    # Vehicle service interval (km) and how early to warn; documents warned 30 days ahead.
    "SERVICE_INTERVAL_KM": {
        "BIKE": 3000,
        "AUTO": 5000,
        "MINI": 10000,
        "SEDAN": 10000,
        "SUV": 10000,
    },
    "SERVICE_WARN_KM": 500,
    "DOCUMENT_WARN_DAYS": 30,
    # EVs: usable range on a full battery (km) by vehicle, and the reserve kept for reaching a
    # charger after the trip.
    "EV_RANGE_KM": {"BIKE": 90, "AUTO": 120, "MINI": 250, "SEDAN": 300, "SUV": 350},
    "EV_RESERVE_KM": 15,
    # Airport queue: drivers inside the airport zone wait in line; leaving it for longer than
    # this drops them out.
    "AIRPORT_QUEUE_GRACE_MINUTES": 5,
    # Privacy requests (access, correction, grievances) are answered within this many days.
    "PRIVACY_RESPONSE_DAYS": 30,
}

# --- Google Maps Platform (optional) ---------------------------------------------------------
# Server key: Routes API (real road distance, traffic-aware ETAs, route polylines).
# Browser key: Maps JavaScript API + Places in the React apps (restrict it by HTTP referrer).
# Leave both empty to use OpenStreetMap tiles and built-in route estimates.
GOOGLE_MAPS_API_KEY = env("GOOGLE_MAPS_API_KEY", default="")
# The data platform's published summary (data/pipeline/report.py), shown on Ops > Data insights.
DATA_INSIGHTS_PATH = Path(
    env("DATA_INSIGHTS_PATH", default=str(BASE_DIR / "data" / "reports" / "insights.json"))
)
# Language Bridge: free-text chat translation (the phrasebook works without it).
GOOGLE_TRANSLATE_API_KEY = env("GOOGLE_TRANSLATE_API_KEY", default="")
GOOGLE_MAPS_BROWSER_KEY = env("GOOGLE_MAPS_BROWSER_KEY", default="")
GOOGLE_MAPS_MAP_ID = env("GOOGLE_MAPS_MAP_ID", default="DEMO_MAP_ID")
GOOGLE_ROUTES_TRAFFIC_AWARE = env.bool("GOOGLE_ROUTES_TRAFFIC_AWARE", default=True)

# --- SMS (phone login codes) -----------------------------------------------------------------
# console (default: codes go to the log, and to the app in DEBUG), twilio or msg91.
SMS_BACKEND = env("SMS_BACKEND", default="console")
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID", default="")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN", default="")
TWILIO_FROM = env("TWILIO_FROM", default="")
MSG91_AUTH_KEY = env("MSG91_AUTH_KEY", default="")
MSG91_TEMPLATE_ID = env("MSG91_TEMPLATE_ID", default="")

# --- Web Push (optional) ---------------------------------------------------------------------
# Generate with `python manage.py generate_vapid_keys`. Empty: push notifications are off.
VAPID_PUBLIC_KEY = env("VAPID_PUBLIC_KEY", default="")
VAPID_PRIVATE_KEY = env("VAPID_PRIVATE_KEY", default="")
VAPID_SUBJECT = env("VAPID_SUBJECT", default="mailto:support@ridepulse.dev")

# --- Masked calling (optional) ---------------------------------------------------------------
# Exotel click-to-call bridges rider and driver through a virtual number (demo mode if unset).
EXOTEL_SID = env("EXOTEL_SID", default="")
EXOTEL_API_KEY = env("EXOTEL_API_KEY", default="")
EXOTEL_API_TOKEN = env("EXOTEL_API_TOKEN", default="")
EXOTEL_CALLER_ID = env("EXOTEL_CALLER_ID", default="")
EXOTEL_SUBDOMAIN = env("EXOTEL_SUBDOMAIN", default="api.exotel.com")

# --- Razorpay (optional) ---------------------------------------------------------------------
# Test keys (rzp_test_...) from the Razorpay dashboard enable real checkout for wallet top-ups.
# Leave empty to use the built-in simulated gateway.
RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID", default="")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET", default="")
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET", default="")

# Map servers need to know which site is asking: OpenStreetMap blocks tile requests that carry no
# Referer ("Access blocked"), and Google checks it against the browser key's allowed referrers.
# Django's default ("same-origin") drops it on cross-site requests; this sends only the origin.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# --- Channels (WebSockets) ---------------------------------------------------------------
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    # Per-process layer; events from other processes arrive via PostgreSQL (REALTIME_RELAY).
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
# "postgres": fan WebSocket events out across processes with LISTEN/NOTIFY (no Redis needed).
# "layer": hand them straight to the channel layer (Redis already reaches every process).
REALTIME_RELAY = env("REALTIME_RELAY", default="layer" if REDIS_URL else "postgres")
