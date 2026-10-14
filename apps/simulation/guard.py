"""Refuse to run demo-data commands outside demo mode (see settings.DEMO_MODE)."""

from django.conf import settings
from django.core.management.base import CommandError


def require_demo_mode(command: str) -> None:
    if not getattr(settings, "DEMO_MODE", False):
        raise CommandError(
            f"`{command}` creates demo accounts with a published password and fake activity, "
            "so it only runs in demo mode. Set DEMO_MODE=true for a demo site (never for a real "
            "deployment)."
        )
