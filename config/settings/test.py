import tempfile

from .base import *  # noqa: F403
from .base import DATABASES, REST_FRAMEWORK

DEBUG = False
DEMO_MODE = True
SECRET_KEY = "test-secret-key-that-is-long-enough-for-hs256-signing"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
MEDIA_ROOT = tempfile.mkdtemp(prefix="ridepulse-test-media-")
STATIC_ROOT = tempfile.mkdtemp(prefix="ridepulse-test-static-")
CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}

CELERY_BROKER_URL = ""
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {
        "anon": "10000/min",
        "user": "10000/min",
        "fare_estimate": "10000/min",
        "location": "10000/min",
        "registration": "10000/min",
        "otp": "10000/min",
        "login": "10000/min",
        "booking": "10000/min",
    },
}

LOGGING = {"version": 1, "disable_existing_loggers": False}

CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
REALTIME_RELAY = "layer"
SMS_BACKEND = "console"
VAPID_PUBLIC_KEY = VAPID_PRIVATE_KEY = ""
RAZORPAY_KEY_ID = RAZORPAY_KEY_SECRET = RAZORPAY_WEBHOOK_SECRET = (
    ""  # tests that need the PostgreSQL relay switch it on themselves
)

GOOGLE_MAPS_API_KEY = ""
GOOGLE_MAPS_BROWSER_KEY = ""

# Async (Channels) tests reach the database from worker threads; close those connections promptly
# so the test database can be dropped at the end of the run.
DATABASES["default"]["CONN_MAX_AGE"] = 0
