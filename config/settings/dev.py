from .base import *  # noqa: F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)
DEMO_MODE = env.bool("DEMO_MODE", default=True)  # local demo data and the bot simulator
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]"])
INTERNAL_IPS = ["127.0.0.1"]
