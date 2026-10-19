"""Quiet hours and the daily digest: routine notifications wait, urgent ones never do."""

from datetime import datetime

import pytest
from django.utils import timezone

from apps.notifications.models import Level, Notification, NotificationPreference
from apps.notifications.services import notify, send_digests

from ..conftest import make_staff

pytestmark = pytest.mark.django_db


def test_digest_holds_routine_and_sends_one_summary(api):
    user = make_staff("SUPPORT_AGENT")
    r = api(user).post("/api/v1/notifications/preferences/", {"digest": True}, format="json")
    assert r.json()["digest"] is True
    notify(user, "Shift swapped", "x")
    notify(user, "Payslip ready", "x", level=Level.SUCCESS)
    notify(user, "SOS on your trip", "x", level=Level.DANGER)
    held = dict(Notification.objects.values_list("title", "held"))
    assert held == {"Shift swapped": True, "Payslip ready": True, "SOS on your trip": False}
    assert send_digests() == 1
    digest = Notification.objects.get(title__startswith="Your daily digest")
    assert "2 updates" in digest.title and "Shift swapped" in digest.body


def test_quiet_hours_wrap_past_midnight():
    pref = NotificationPreference(quiet_from=22, quiet_until=7)
    at = lambda h: timezone.make_aware(datetime(2026, 10, 20, h, 30))  # noqa: E731
    assert pref.is_quiet(at(23)) and pref.is_quiet(at(3)) and not pref.is_quiet(at(12))
