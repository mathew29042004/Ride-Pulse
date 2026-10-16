"""Running smoothly: scheduled jobs are tracked, slow requests are logged and alerted, and the
busiest lists stay within a fixed number of database queries (no N+1 creeping back)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.notifications.models import Notification
from apps.reliability import jobs
from apps.reliability.models import JobStatus, SlowRequest

from ..conftest import make_rider, make_staff
from .helpers import book, drive_to_completion

pytestmark = pytest.mark.django_db


def test_jobs_record_runs_failures_and_lateness():
    @jobs.tracked("demo-job", every=timedelta(minutes=5))
    def works():
        return {"done": 3}

    @jobs.tracked("demo-broken", every=timedelta(minutes=5))
    def breaks():
        raise ValueError("no connection")

    assert works() == {"done": 3}
    works()
    with pytest.raises(ValueError):
        breaks()
    ok, bad = JobStatus.objects.get(name="demo-job"), JobStatus.objects.get(name="demo-broken")
    assert ok.runs == 2 and ok.last_ok and ok.last_result == {"done": 3}
    assert bad.failures == 1 and not bad.last_ok and "no connection" in bad.last_error
    states = {j["name"]: j["state"] for j in jobs.jobs_overview()}
    assert states == {"demo-broken": "FAILING", "demo-job": "OK"}
    later = timezone.now() + timedelta(minutes=16)
    assert {j["name"]: j["state"] for j in jobs.jobs_overview(later)}["demo-job"] == "LATE"


def test_slow_requests_are_logged_and_alert_ops(api, settings, admin):
    settings.SLOW_REQUEST_MS = 0  # everything counts as slow for this test
    ops = make_staff(Role.OPS_MANAGER)
    client = api(admin)
    for _ in range(10):
        client.get("/api/v1/cities/")
    assert SlowRequest.objects.filter(route__icontains="city").count() == 10
    assert jobs.check_slow()["alerted"] == 1
    assert Notification.objects.filter(user=ops, title__startswith="Slow:").exists()
    assert jobs.check_slow()["alerted"] == 0  # once an hour per route
    health = client.get("/api/v1/platform/health/").json()
    assert health["speed"]["last_24h"] >= 10 and "jobs" in health


def test_busy_lists_stay_within_a_query_budget(
    api, admin, mini, make_driver, now, django_assert_max_num_queries
):
    for _ in range(4):
        make_driver(now=now)
    rider = make_rider()
    drive_to_completion(book(rider, mini, now=now), now=now)
    client = api(admin)
    with django_assert_max_num_queries(8):
        assert client.get("/api/v1/drivers/").status_code == 200
    with django_assert_max_num_queries(8):
        assert client.get("/api/v1/support/tickets/").status_code == 200
    with django_assert_max_num_queries(20):
        assert client.get("/api/v1/ops/tours/overview/").status_code == 200
