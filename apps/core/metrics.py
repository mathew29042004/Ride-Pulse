"""Prometheus metrics at ``/metrics``, with no extra dependencies.

Two kinds of numbers:

* HTTP traffic (requests, latency histogram, by method, route and status), counted per
  process by ``MetricsMiddleware``. Prometheus scrapes each process and sums them.
* Business gauges read from PostgreSQL at scrape time: trips by live status, drivers online,
  open support tickets, scheduled rides waiting, ledger balance check.

Protected by ``METRICS_TOKEN`` (``Authorization: Bearer <token>``); without a token configured
the endpoint only answers in DEBUG.
"""

import hmac
import threading
import time
from collections import defaultdict

from django.conf import settings
from django.http import Http404, HttpResponse
from django.urls import Resolver404, resolve
from django.views.decorators.cache import never_cache

BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

_lock = threading.Lock()
_requests: dict[tuple[str, str, str], int] = defaultdict(int)
_latency_buckets: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * len(BUCKETS))
_latency_sum: dict[tuple[str, str], float] = defaultdict(float)
_latency_count: dict[tuple[str, str], int] = defaultdict(int)


def _route(path: str) -> str:
    """The view's name ("trip-detail"), not the raw path, so /trips/1/ and /trips/2/ share
    one series and the number of series stays bounded."""
    try:
        match = resolve(path)
    except Resolver404:
        return "unmatched"
    return match.view_name or match.route or "unmatched"


def observe(method: str, path: str, status: int, seconds: float) -> None:
    route = _route(path)
    with _lock:
        _requests[(method, route, str(status))] += 1
        key = (method, route)
        for i, bound in enumerate(BUCKETS):
            if seconds <= bound:
                _latency_buckets[key][i] += 1
        _latency_sum[key] += seconds
        _latency_count[key] += 1


class MetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        if not request.path.startswith(("/static/", "/metrics")):
            observe(
                request.method, request.path, response.status_code, time.perf_counter() - started
            )
        return response


def _labels(**labels: str) -> str:
    inner = ",".join(f'{k}="{str(v).replace(chr(34), "")}"' for k, v in labels.items())
    return "{" + inner + "}"


def _business_gauges() -> list[str]:
    from django.db.models import Count

    from apps.drivers.models import Availability, DriverProfile
    from apps.payments.services import verify_ledger
    from apps.rides.models import ACTIVE_STATUSES, ScheduledRide, ScheduledRideStatus, Trip
    from apps.support.models import OPEN_TICKET_STATUSES, SupportTicket

    lines = [
        "# HELP ridepulse_trips_active Trips currently in each live status.",
        "# TYPE ridepulse_trips_active gauge",
    ]
    counts = dict(
        Trip.objects.filter(status__in=ACTIVE_STATUSES)
        .values_list("status")
        .annotate(n=Count("id"))
        .values_list("status", "n")
    )
    for status in ACTIVE_STATUSES:
        lines.append(f"ridepulse_trips_active{_labels(status=status)} {counts.get(status, 0)}")
    drivers = dict(
        DriverProfile.objects.values_list("availability")
        .annotate(n=Count("id"))
        .values_list("availability", "n")
    )
    lines += [
        "# HELP ridepulse_drivers Drivers by availability.",
        "# TYPE ridepulse_drivers gauge",
        *(
            f"ridepulse_drivers{_labels(availability=a)} {drivers.get(a, 0)}"
            for a in Availability.values
        ),
        "# HELP ridepulse_support_tickets_open Support tickets not yet resolved.",
        "# TYPE ridepulse_support_tickets_open gauge",
        "ridepulse_support_tickets_open "
        f"{SupportTicket.objects.filter(status__in=OPEN_TICKET_STATUSES).count()}",
        "# HELP ridepulse_scheduled_rides_waiting Scheduled rides not yet dispatched.",
        "# TYPE ridepulse_scheduled_rides_waiting gauge",
        "ridepulse_scheduled_rides_waiting "
        f"{ScheduledRide.objects.filter(status=ScheduledRideStatus.SCHEDULED).count()}",
        "# HELP ridepulse_ledger_balanced 1 if every ledger transaction sums to zero.",
        "# TYPE ridepulse_ledger_balanced gauge",
        f"ridepulse_ledger_balanced {int(verify_ledger()['balanced'])}",
    ]
    return lines


def render() -> str:
    lines = [
        "# HELP ridepulse_http_requests_total HTTP requests by method, route and status.",
        "# TYPE ridepulse_http_requests_total counter",
    ]
    with _lock:
        requests = dict(_requests)
        buckets = {k: list(v) for k, v in _latency_buckets.items()}
        sums, counts = dict(_latency_sum), dict(_latency_count)
    for (method, route, status), n in sorted(requests.items()):
        labels = _labels(method=method, route=route, status=status)
        lines.append(f"ridepulse_http_requests_total{labels} {n}")
    lines += [
        "# HELP ridepulse_http_request_duration_seconds Request latency.",
        "# TYPE ridepulse_http_request_duration_seconds histogram",
    ]
    for (method, route), hits in sorted(buckets.items()):
        for bound, n in zip(BUCKETS, hits, strict=True):
            labels = _labels(method=method, route=route, le=bound)
            lines.append(f"ridepulse_http_request_duration_seconds_bucket{labels} {n}")
        total = counts[(method, route)]
        inf = _labels(method=method, route=route, le="+Inf")
        base = _labels(method=method, route=route)
        lines += [
            f"ridepulse_http_request_duration_seconds_bucket{inf} {total}",
            f"ridepulse_http_request_duration_seconds_sum{base} {sums[(method, route)]:.6f}",
            f"ridepulse_http_request_duration_seconds_count{base} {total}",
        ]
    lines += _business_gauges()
    return "\n".join(lines) + "\n"


@never_cache
def metrics_view(request):
    token = getattr(settings, "METRICS_TOKEN", "")
    if token:
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied, token):
            raise Http404
    elif not settings.DEBUG:
        raise Http404
    return HttpResponse(render(), content_type="text/plain; version=0.0.4; charset=utf-8")
