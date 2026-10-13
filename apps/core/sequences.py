"""Concurrency-safe reference numbers.

A single ``INSERT ... ON CONFLICT DO UPDATE ... RETURNING`` statement increments the counter, so
two requests can never receive the same number and no explicit lock round trip is needed. The
row lock is held until the surrounding transaction ends, which keeps numbers gap-free when the
caller's transaction rolls back.
"""

from django.db import connection

from .models import Sequence

_UPSERT_SQL = f"""
    INSERT INTO {Sequence._meta.db_table} (key, last_value) VALUES (%s, 1)
    ON CONFLICT (key) DO UPDATE SET last_value = {Sequence._meta.db_table}.last_value + 1
    RETURNING last_value
"""


def next_value(key: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(_UPSERT_SQL, [key])
        return cursor.fetchone()[0]


def next_reference(prefix: str, *, year: int | None = None, width: int = 6) -> str:
    """``next_reference("POL", year=2026)`` -> ``"POL-2026-000001"``."""
    if year is None:
        return f"{prefix}-{next_value(prefix):0{width}d}"
    return f"{prefix}-{year}-{next_value(f'{prefix}-{year}'):0{width}d}"
