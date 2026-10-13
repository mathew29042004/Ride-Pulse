from datetime import date, datetime, time, timedelta

from django.utils import timezone


def today() -> date:
    return timezone.localdate()


def local_midnight(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min))


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """[start, end) of a local calendar day as aware datetimes."""
    start = local_midnight(day)
    return start, local_midnight(day + timedelta(days=1))


def age_in_years(born: date, on: date) -> int:
    years = on.year - born.year
    if (on.month, on.day) < (born.month, born.day):
        years -= 1
    return max(years, 0)


def minutes_between(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return (end - start).total_seconds() / 60


def week_start(day: date) -> date:
    """Monday of the week containing ``day``."""
    return day - timedelta(days=day.weekday())
