"""Background jobs and request speed, for the Platform health page.

* ``@tracked("name", every=...)`` on a scheduled job records each run (start, duration, result,
  error) in ``JobStatus``, whoever runs it: Celery beat in production, the simulator in the
  demo. A job is **late** when it hasn't run for three of its intervals, **failing** when its
  last run raised.
* Requests slower than ``SLOW_REQUEST_MS`` are logged (``SlowRequest``) by the metrics
  middleware; the page shows the slowest routes and the per-route latency from the Prometheus
  histogram. When a route is slow 10+ times in 15 minutes, ops get one alert an hour.
"""

import functools
import logging
import time
from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import Count, F, Max
from django.utils import timezone

logger = logging.getLogger(__name__)

SLOW_ALERT_COUNT = 10
SLOW_ALERT_WINDOW = timedelta(minutes=15)
SLOW_KEEP = timedelta(days=7)


def _summary(result) -> dict:
    if isinstance(result, dict):
        return {
            k: v for k, v in list(result.items())[:8] if isinstance(v, int | float | str | bool)
        }
    if isinstance(result, int | float | str | bool):
        return {"result": result}
    return {}


def _record(name: str, every: timedelta, started, ms: int, *, result=None, error: str = "") -> None:
    from .models import JobStatus

    now = timezone.now()
    fields = {
        "every_seconds": int(every.total_seconds()),
        "last_started_at": started,
        "last_finished_at": now,
        "last_duration_ms": ms,
        "last_ok": not error,
        "last_error": error[:300],
    }
    if not error:
        fields["last_result"] = _summary(result)
    try:
        # A savepoint: recording must never break (or be broken by) the caller's transaction.
        with transaction.atomic():
            status, _ = JobStatus.objects.get_or_create(name=name, defaults=fields)
            updates = {**fields, "runs": F("runs") + 1}
            if error:
                updates.update(failures=F("failures") + 1, last_failed_at=now)
            JobStatus.objects.filter(pk=status.pk).update(**updates)
    except DatabaseError as exc:  # e.g. the caller's transaction is already broken
        logger.warning("Couldn't record job %s: %s", name, exc)


def tracked(name: str, *, every: timedelta):
    def wrap(func):
        @functools.wraps(func)
        def run(*args, **kwargs):
            started = timezone.now()
            clock = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                _record(
                    name,
                    every,
                    started,
                    int((time.perf_counter() - clock) * 1000),
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise
            _record(name, every, started, int((time.perf_counter() - clock) * 1000), result=result)
            return result

        return run

    return wrap


def jobs_overview(now=None) -> list[dict]:
    from .models import JobStatus

    now = now or timezone.now()
    rows = []
    for job in JobStatus.objects.all():
        late = job.last_finished_at is None or now - job.last_finished_at > timedelta(
            seconds=job.every_seconds * 3
        )
        rows.append(
            {
                "name": job.name,
                "every_seconds": job.every_seconds,
                "last_finished_at": job.last_finished_at,
                "last_duration_ms": job.last_duration_ms,
                "last_ok": job.last_ok,
                "last_error": job.last_error,
                "last_result": job.last_result,
                "runs": job.runs,
                "failures": job.failures,
                "state": "FAILING" if not job.last_ok else "LATE" if late else "OK",
            }
        )
    order = {"FAILING": 0, "LATE": 1, "OK": 2}
    return sorted(rows, key=lambda r: (order[r["state"]], r["name"]))


# --- Request speed -------------------------------------------------------------------------------


def slow_threshold_ms() -> int:
    return int(getattr(settings, "SLOW_REQUEST_MS", 500))


def record_slow(method: str, route: str, status: int, ms: int) -> None:
    from .models import SlowRequest

    try:
        with transaction.atomic():
            SlowRequest.objects.create(
                route=route[:120], method=method, status=status, duration_ms=ms, at=timezone.now()
            )
    except DatabaseError as exc:
        logger.warning("Couldn't record a slow request: %s", exc)


def latency_by_route(limit: int = 12) -> dict:
    """From this process's Prometheus histogram: requests, average and ~p95 per route."""
    from apps.core import metrics

    rows = []
    with metrics._lock:
        for (method, route), count in metrics._latency_count.items():
            if count < 3 or route == "unmatched":
                continue
            buckets = metrics._latency_buckets[(method, route)]
            p95 = next(
                (
                    bound
                    for bound, n in zip(metrics.BUCKETS, buckets, strict=True)
                    if n >= count * 0.95
                ),
                None,
            )
            rows.append(
                {
                    "route": route,
                    "method": method,
                    "requests": count,
                    "avg_ms": round(1000 * metrics._latency_sum[(method, route)] / count),
                    "p95_ms": int(p95 * 1000) if p95 is not None else None,
                }
            )
    errors = sum(n for (_, _, status), n in metrics._requests.items() if status.startswith("5"))
    total = sum(metrics._requests.values())
    rows.sort(key=lambda r: (-(r["p95_ms"] or 10_000), -r["requests"]))
    return {"routes": rows[:limit], "requests": total, "server_errors": errors}


def slow_overview(now=None) -> dict:
    from .models import SlowRequest

    now = now or timezone.now()
    day = SlowRequest.objects.filter(at__gte=now - timedelta(hours=24))
    return {
        "threshold_ms": slow_threshold_ms(),
        "last_24h": day.count(),
        "by_route": list(
            day.values("method", "route")
            .annotate(n=Count("pk"), worst_ms=Max("duration_ms"), last=Max("at"))
            .order_by("-n")[:10]
        ),
        "recent": list(day.values("method", "route", "status", "duration_ms", "at")[:15]),
    }


@tracked("slow-request-check", every=timedelta(minutes=5))
def check_slow(now=None) -> dict:
    """Alert ops (once an hour per route) when a route keeps being slow; prune old rows."""
    from apps.notifications.models import Level, Notification
    from apps.notifications.services import notify_role

    from .models import SlowRequest

    now = now or timezone.now()
    SlowRequest.objects.filter(at__lt=now - SLOW_KEEP).delete()
    alerted = 0
    for row in (
        SlowRequest.objects.filter(at__gte=now - SLOW_ALERT_WINDOW)
        .values("method", "route")
        .annotate(n=Count("pk"), worst=Max("duration_ms"))
        .filter(n__gte=SLOW_ALERT_COUNT)
    ):
        title = f"Slow: {row['method']} {row['route']}"
        if Notification.objects.filter(
            title=title, created_at__gte=now - timedelta(hours=1)
        ).exists():
            continue
        notify_role(
            "OPS_MANAGER",
            title,
            f"{row['n']} requests over {slow_threshold_ms()} ms in 15 minutes "
            f"(worst {row['worst']} ms). See Platform health.",
            level=Level.WARNING,
            link="/ops/platform",
        )
        alerted += 1
    return {"alerted": alerted}
