"""Nightly pruning deletes only old, no-longer-needed rows."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.reliability.retention import prune

from ..conftest import make_rider

pytestmark = pytest.mark.django_db


def test_prune_keeps_recent_rows():
    now = timezone.now()
    rider = make_rider()
    notify(rider.user, "old", "x")
    notify(rider.user, "new", "x")
    Notification.objects.filter(title="old").update(
        is_read=True, created_at=now - timedelta(days=100)
    )
    assert prune(now=now)["notifications"] == 1
    assert list(Notification.objects.filter(user=rider.user).values_list("title", flat=True)) == [
        "new"
    ]
