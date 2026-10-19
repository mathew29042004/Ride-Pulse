"""Staff attendance: clock in and out, matched to the roster.

* **Clock in** from 30 minutes before your shift. More than ``GRACE`` after the start is late.
  Staff without shifts (managers, office teams) are measured against office hours, 9:30–6:30.
* **Clock out**: under 4 hours worked is a half day. Forgot to clock out? The day is closed at the
  shift end that night and marked so the person can ask for a correction.
* **Absent**: a rostered shift that ended with no clock-in, and no approved leave. The manager is
  told the next morning. Approved leave shows as leave, never as absent.
* **Corrections**: if the times are wrong, the employee asks for a correction with a reason; their
  manager (anyone above them in the org chart) approves or declines it.
"""

from collections import Counter
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation

EARLY = timedelta(minutes=30)
GRACE = timedelta(minutes=10)
HALF_DAY = timedelta(hours=4)
OFFICE_HOURS = (time(9, 30), time(18, 30))


class AttendanceStatus(models.TextChoices):
    WORKING = "WORKING", "Clocked in"
    PRESENT = "PRESENT", "Present"
    LATE = "LATE", "Late"
    HALF_DAY = "HALF_DAY", "Half day"
    ABSENT = "ABSENT", "Absent"
    ON_LEAVE = "ON_LEAVE", "On leave"
    NO_CLOCK_OUT = "NO_OUT", "Didn't clock out"


class CorrectionStatus(models.TextChoices):
    NONE = "", "—"
    PENDING = "PENDING", "Waiting for approval"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Not approved"


class Attendance(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attendance"
    )
    day = models.DateField()
    shift = models.ForeignKey(
        "workspace.Shift", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    expected_start = models.DateTimeField()
    expected_end = models.DateTimeField()
    clock_in = models.DateTimeField(null=True, blank=True)
    clock_out = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=8, choices=AttendanceStatus.choices)
    late_minutes = models.PositiveIntegerField(default=0)
    worked_minutes = models.PositiveIntegerField(default=0)
    # A correction the employee asked for.
    correction_in = models.DateTimeField(null=True, blank=True)
    correction_out = models.DateTimeField(null=True, blank=True)
    correction_reason = models.CharField(max_length=200, blank=True)
    correction_status = models.CharField(
        max_length=8, choices=CorrectionStatus.choices, blank=True, default=""
    )
    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        app_label = "workspace"
        ordering = ["-day"]
        constraints = [
            models.UniqueConstraint(fields=["user", "day"], name="attendance_once_a_day")
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.day} {self.status}"


def _aware(day: date, t: time) -> datetime:
    return timezone.make_aware(datetime.combine(day, t))


def _expected(user, now: datetime):
    """The shift this clock-in belongs to: one starting within 30 min or already running."""
    from .models import Shift

    shift = (
        Shift.objects.filter(user=user, starts_at__lte=now + EARLY, ends_at__gt=now)
        .order_by("starts_at")
        .first()
    )
    if shift:
        return shift, shift.day, shift.starts_at, shift.ends_at
    today = timezone.localdate(now)
    return None, today, _aware(today, OFFICE_HOURS[0]), _aware(today, OFFICE_HOURS[1])


def _on_leave(user, day: date) -> bool:
    from .models import LeaveRequest, LeaveStatus

    return LeaveRequest.objects.filter(
        user=user, status=LeaveStatus.APPROVED, starts_on__lte=day, ends_on__gte=day
    ).exists()


def _settle(record: Attendance) -> Attendance:
    """Work out late minutes, hours worked and the day's status from the times."""
    if record.clock_in is None:
        return record
    late = record.clock_in - record.expected_start
    record.late_minutes = max(0, int(late.total_seconds() // 60)) if late > GRACE else 0
    if record.clock_out is None:
        record.status = AttendanceStatus.WORKING
        return record
    worked = record.clock_out - record.clock_in
    record.worked_minutes = max(0, int(worked.total_seconds() // 60))
    record.status = (
        AttendanceStatus.HALF_DAY
        if worked < HALF_DAY
        else AttendanceStatus.LATE
        if record.late_minutes
        else AttendanceStatus.PRESENT
    )
    return record


def check_site(user, lat, lng) -> None:
    """Staff with a work site must clock in there (within its radius)."""
    from apps.geo.distance import haversine_km

    profile = getattr(user, "staff_profile", None)
    if not profile or profile.work_lat is None:
        return
    if lat is None or lng is None:
        raise BusinessRuleViolation(
            "Allow location so we can check you're at work.", field="location"
        )
    metres = haversine_km(profile.work_lat, profile.work_lng, lat, lng) * 1000
    if metres > profile.work_radius_m:
        raise BusinessRuleViolation(
            f"You're {metres / 1000:.1f} km from your workplace. Clock in when you get there.",
            field="location",
        )


def clock_in(user, *, now=None, lat=None, lng=None) -> Attendance:
    now = now or timezone.now()
    check_site(user, lat, lng)
    shift, day, start, end = _expected(user, now)
    if now < start - EARLY:
        raise BusinessRuleViolation(
            f"Your shift starts at {timezone.localtime(start):%I:%M %p}. "
            "Clock in from 30 minutes before."
        )
    if now >= end:
        raise BusinessRuleViolation(
            "Your shift has ended. Ask your manager for a correction instead."
        )
    record, created = Attendance.objects.get_or_create(
        user=user,
        day=day,
        defaults={
            "shift": shift,
            "expected_start": start,
            "expected_end": end,
            "clock_in": now,
            "status": AttendanceStatus.WORKING,
        },
    )
    if not created:
        if record.clock_in:
            raise BusinessRuleViolation(
                f"You clocked in at {timezone.localtime(record.clock_in):%I:%M %p}."
            )
        record.clock_in = now  # e.g. marked absent too early, or on leave but came in
    _settle(record).save()
    return record


def clock_out(user, *, now=None) -> Attendance:
    now = now or timezone.now()
    record = (
        Attendance.objects.filter(user=user, clock_in__isnull=False, clock_out__isnull=True)
        .order_by("-day")
        .first()
    )
    if record is None:
        raise BusinessRuleViolation("You haven't clocked in.")
    record.clock_out = now
    _settle(record).save()
    return record


def close_day(*, now=None) -> dict:
    """Run every hour: close forgotten clock-outs at shift end, mark shifts nobody turned up for."""
    from .models import Shift

    now = now or timezone.now()
    stats = {"closed": 0, "absent": 0, "leave": 0}
    for record in Attendance.objects.filter(
        clock_in__isnull=False, clock_out__isnull=True, expected_end__lt=now - timedelta(hours=2)
    ):
        record.clock_out = record.expected_end
        _settle(record)
        record.status = AttendanceStatus.NO_CLOCK_OUT
        record.save()
        stats["closed"] += 1
    missed = (
        Shift.objects.filter(ends_at__lt=now, ends_at__gte=now - timedelta(days=2))
        .exclude(user__attendance__day=models.F("day"))
        .select_related("user")
    )
    for shift in missed:
        leave = _on_leave(shift.user, shift.day)
        Attendance.objects.get_or_create(
            user=shift.user,
            day=shift.day,
            defaults={
                "shift": shift,
                "expected_start": shift.starts_at,
                "expected_end": shift.ends_at,
                "status": AttendanceStatus.ON_LEAVE if leave else AttendanceStatus.ABSENT,
            },
        )
        stats["leave" if leave else "absent"] += 1
        if not leave:
            _tell_manager(
                shift.user,
                f"No clock-in for the {shift.get_slot_display()} shift on {shift.day:%d %b}.",
            )
    return stats


def _tell_manager(user, body: str) -> None:
    from apps.notifications.models import Level
    from apps.notifications.services import notify

    manager = getattr(getattr(user, "staff_profile", None), "reports_to", None)
    if manager is not None:
        notify(
            manager.user,
            f"{user.get_full_name()} was absent",
            body,
            level=Level.WARNING,
            link="/ops/attendance",
        )


def request_correction(
    record: Attendance, *, user, clock_in_at, clock_out_at, reason: str
) -> Attendance:
    if record.user_id != user.pk:
        raise ActionNotPermitted("You can only correct your own attendance.")
    if len(reason.strip()) < 5:
        raise BusinessRuleViolation("Say why the times need correcting.", field="reason")
    if clock_out_at and clock_in_at and clock_out_at <= clock_in_at:
        raise BusinessRuleViolation("Clock-out must be after clock-in.", field="clock_out")
    if record.day < timezone.localdate() - timedelta(days=31):
        raise BusinessRuleViolation("Corrections can be asked for up to a month later.")
    record.correction_in, record.correction_out = clock_in_at, clock_out_at
    record.correction_reason, record.correction_status = (
        reason.strip()[:200],
        CorrectionStatus.PENDING,
    )
    record.save()
    _tell_manager_correction(record)
    return record


def _tell_manager_correction(record: Attendance) -> None:
    from apps.notifications.services import notify

    manager = getattr(getattr(record.user, "staff_profile", None), "reports_to", None)
    if manager is not None:
        notify(
            manager.user,
            f"Attendance correction from {record.user.get_full_name()}",
            f"{record.day:%d %b}: {record.correction_reason}",
            link="/ops/attendance",
        )


def decide_correction(record: Attendance, *, manager, approve: bool) -> Attendance:
    from apps.notifications.services import notify

    from .services import team_of

    if record.user_id not in team_of(manager):
        raise ActionNotPermitted("Only someone above them in the team can decide this.")
    if record.correction_status != CorrectionStatus.PENDING:
        raise BusinessRuleViolation("There's no correction waiting.")
    record.correction_status = CorrectionStatus.APPROVED if approve else CorrectionStatus.REJECTED
    record.corrected_by = manager
    if approve:
        record.clock_in = record.correction_in or record.clock_in
        record.clock_out = record.correction_out or record.clock_out
        _settle(record)
    record.save()
    notify(
        record.user,
        f"Attendance correction {'approved' if approve else 'not approved'}",
        f"{record.day:%d %b}",
        link="/ops/attendance",
    )
    return record


def row(r: Attendance) -> dict:
    return {
        "id": r.pk,
        "user_id": r.user_id,
        "name": r.user.get_full_name(),
        "day": r.day,
        "shift": r.shift.get_slot_display() if r.shift_id else "Office hours",
        "expected_start": r.expected_start,
        "expected_end": r.expected_end,
        "clock_in": r.clock_in,
        "clock_out": r.clock_out,
        "status": r.status,
        "status_label": r.get_status_display(),
        "late_minutes": r.late_minutes,
        "worked_minutes": r.worked_minutes,
        "correction": {
            "status": r.correction_status,
            "clock_in": r.correction_in,
            "clock_out": r.correction_out,
            "reason": r.correction_reason,
        }
        if r.correction_status
        else None,
    }


def mine(user, *, now=None) -> dict:
    now = now or timezone.now()
    shift, _day, start, end = _expected(user, now)
    open_record = (
        Attendance.objects.filter(user=user, clock_in__isnull=False, clock_out__isnull=True)
        .select_related("user", "shift")
        .first()
    )
    month = timezone.localdate(now).replace(day=1)
    records = list(
        Attendance.objects.filter(user=user, day__gte=month).select_related("user", "shift")
    )
    return {
        "working": row(open_record) if open_record else None,
        "next": {
            "shift": shift.get_slot_display() if shift else "Office hours",
            "starts": start,
            "ends": end,
        },
        "month": summary(records),
        "records": [row(r) for r in records],
    }


def summary(records) -> dict:
    counts = Counter(r.status for r in records)
    worked = [r.worked_minutes for r in records if r.worked_minutes]
    return {
        "present": counts[AttendanceStatus.PRESENT],
        "late": counts[AttendanceStatus.LATE],
        "half_day": counts[AttendanceStatus.HALF_DAY],
        "absent": counts[AttendanceStatus.ABSENT],
        "on_leave": counts[AttendanceStatus.ON_LEAVE],
        "no_clock_out": counts[AttendanceStatus.NO_CLOCK_OUT],
        "avg_hours": round(sum(worked) / len(worked) / 60, 1) if worked else None,
    }


def team(manager, *, now=None) -> dict:
    """Today's board and this month's summary for everyone below the manager."""
    from apps.accounts.models import User

    from .models import Shift
    from .services import team_of

    now = now or timezone.now()
    today = timezone.localdate(now)
    ids = team_of(manager)
    people = {u.pk: u for u in User.objects.filter(pk__in=ids, is_active=True)}
    month = list(
        Attendance.objects.filter(user_id__in=ids, day__gte=today.replace(day=1)).select_related(
            "user", "shift"
        )
    )
    by_user: dict[int, list] = {}
    for r in month:
        by_user.setdefault(r.user_id, []).append(r)
    todays = {r.user_id: r for r in month if r.day == today}
    rostered = set(
        Shift.objects.filter(user_id__in=ids, day=today).values_list("user_id", flat=True)
    )
    board = []
    for uid, user in sorted(people.items(), key=lambda kv: kv[1].get_full_name()):
        r = todays.get(uid)
        board.append(
            {
                "user_id": uid,
                "name": user.get_full_name(),
                "rostered": uid in rostered,
                "today": row(r) if r else None,
                "month": summary(by_user.get(uid, [])),
            }
        )
    pending = [
        row(r)
        for r in Attendance.objects.filter(
            user_id__in=ids, correction_status=CorrectionStatus.PENDING
        ).select_related("user", "shift")
    ]
    in_now = sum(
        1 for b in board if b["today"] and b["today"]["status"] == AttendanceStatus.WORKING
    )
    late_today = sum(1 for b in board if b["today"] and b["today"]["late_minutes"])
    return {
        "date": today,
        "in_now": in_now,
        "late_today": late_today,
        "people": board,
        "corrections": pending,
    }


def seed_demo(*, seed: int = 51, log=print) -> dict:
    """Two weeks of attendance for rostered shifts (mostly on time, some late, a few absent, leave
    respected) and office-hours attendance for managers."""
    import random

    from apps.accounts.models import StaffProfile

    from .models import Shift

    if Attendance.objects.exists():
        return {"attendance": 0}
    rng = random.Random(seed)
    now = timezone.now()
    today = timezone.localdate(now)
    rows = []
    for shift in Shift.objects.filter(day__gte=today - timedelta(days=14), ends_at__lt=now):
        if _on_leave(shift.user, shift.day):
            rows.append(
                Attendance(
                    user=shift.user,
                    day=shift.day,
                    shift=shift,
                    expected_start=shift.starts_at,
                    expected_end=shift.ends_at,
                    status=AttendanceStatus.ON_LEAVE,
                )
            )
            continue
        roll = rng.random()
        if roll < 0.03:
            rows.append(
                Attendance(
                    user=shift.user,
                    day=shift.day,
                    shift=shift,
                    expected_start=shift.starts_at,
                    expected_end=shift.ends_at,
                    status=AttendanceStatus.ABSENT,
                )
            )
            continue
        late = rng.choice([25, 40, 55]) if roll < 0.13 else rng.randint(-20, 8)
        r = Attendance(
            user=shift.user,
            day=shift.day,
            shift=shift,
            expected_start=shift.starts_at,
            expected_end=shift.ends_at,
            clock_in=shift.starts_at + timedelta(minutes=late),
            clock_out=shift.ends_at + timedelta(minutes=rng.randint(-10, 25)),
            status=AttendanceStatus.PRESENT,
        )
        rows.append(_settle(r))
    managers = StaffProfile.objects.exclude(user__shifts__isnull=False).select_related("user")[:60]
    for profile in managers:
        for back in range(1, 15):
            day = today - timedelta(days=back)
            if day.weekday() >= 5 or rng.random() < 0.04:
                continue
            start, end = _aware(day, OFFICE_HOURS[0]), _aware(day, OFFICE_HOURS[1])
            late = rng.choice([20, 35]) if rng.random() < 0.08 else rng.randint(-25, 5)
            rows.append(
                _settle(
                    Attendance(
                        user=profile.user,
                        day=day,
                        expected_start=start,
                        expected_end=end,
                        clock_in=start + timedelta(minutes=late),
                        clock_out=end + timedelta(minutes=rng.randint(-5, 60)),
                        status=AttendanceStatus.PRESENT,
                    )
                )
            )
    Attendance.objects.bulk_create(rows, ignore_conflicts=True)
    log(f"  attendance: {len(rows)} days")
    return {"attendance": len(rows)}


def seed_work_sites(*, log=print) -> dict:
    """Support desks work from the city office (the city centre in the demo); field staff
    (fleet executives) and managers who travel have no fixed site."""
    from apps.accounts.models import StaffProfile

    rows = list(
        StaffProfile.objects.filter(
            user__role__in=["SUPPORT_AGENT", "SUPPORT_LEAD"], city__isnull=False
        ).select_related("city")
    )
    for p in rows:
        p.work_lat, p.work_lng, p.work_radius_m = p.city.center_lat, p.city.center_lng, 300
    StaffProfile.objects.bulk_update(rows, ["work_lat", "work_lng", "work_radius_m"])
    log(f"  work sites: {len(rows)} desk staff")
    return {"work_sites": len(rows)}
