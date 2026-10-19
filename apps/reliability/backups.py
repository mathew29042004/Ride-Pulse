"""Nightly database backups and a weekly restore drill.

A backup nobody has restored is a hope, not a backup. So:

* Every night: ``pg_dump`` (custom format, compressed) to ``BACKUP_DIR``, with a SHA-256
  checksum and the row counts of key tables at that moment. The newest ``KEEP`` are kept.
* Every week (and on demand): the restore drill takes the latest backup, checks its checksum,
  restores it into a fresh scratch database, compares the row counts, checks the ledger still
  balances to the paisa, times the whole restore (our real recovery time), then drops the
  scratch database. Ops → Backups shows every run; a failure alerts like any failing job.

In production the dump would also be copied off the server (e.g. to S3 in another region);
here it stays in ``backups/`` (git-ignored).
"""

import hashlib
import os
import shutil
import subprocess
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .jobs import tracked
from .models import BackupKind, BackupRun

KEEP = 14
# Tables whose row counts must match after a restore (the money and the trips above all).
KEY_TABLES = [
    "accounts_user",
    "riders_riderprofile",
    "drivers_driverprofile",
    "rides_trip",
    "payments_ledgertransaction",
    "payments_ledgerentry",
    "payments_wallet",
    "support_supportticket",
]


def backup_dir() -> Path:
    path = Path(getattr(settings, "BACKUP_DIR", settings.BASE_DIR / "backups"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _bin(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    try:
        import pgserver

        return str(Path(pgserver.__file__).parent / "pginstall" / "bin" / name)
    except ImportError as exc:
        raise RuntimeError(f"{name} not found: install the PostgreSQL client tools") from exc


def _db(name: str | None = None) -> tuple[list[str], dict]:
    db = settings.DATABASES["default"]
    args = [
        "-h",
        db.get("HOST") or "127.0.0.1",
        "-p",
        str(db.get("PORT") or 5432),
        "-U",
        db["USER"],
    ]
    env = {**os.environ, "PGPASSWORD": db.get("PASSWORD") or ""}
    return [*args, "-d", name or db["NAME"]], env


def _conninfo(dbname: str | None = None) -> dict:
    db = settings.DATABASES["default"]
    return {
        "host": db.get("HOST") or "127.0.0.1",
        "port": db.get("PORT") or 5432,
        "user": db["USER"],
        "password": db.get("PASSWORD") or "",
        "dbname": dbname or db["NAME"],
        "autocommit": True,
    }


def _counts(cursor) -> dict:
    out = {}
    for table in KEY_TABLES:
        cursor.execute(f'SELECT count(*) FROM "{table}"')
        out[table] = cursor.fetchone()[0]
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@tracked("backup", every=timedelta(days=1))
def backup(*, user=None) -> dict:
    started, clock = timezone.now(), time.perf_counter()
    run = BackupRun.objects.create(kind=BackupKind.BACKUP, started_at=started, started_by=user)
    path = backup_dir() / f"ridepulse-{timezone.localtime(started):%Y%m%d-%H%M%S}.dump"
    try:
        import psycopg

        # Count rows and dump from the same snapshot, so the counts describe exactly what's in
        # the file even while trips keep coming in.
        with psycopg.connect(**_conninfo()) as conn, conn.cursor() as cursor:
            cursor.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute("SELECT pg_export_snapshot()")
            snapshot = cursor.fetchone()[0]
            counts = _counts(cursor)
            args, env = _db()
            subprocess.run(
                [
                    _bin("pg_dump"),
                    "-Fc",
                    "-Z",
                    "6",
                    "--no-owner",
                    f"--snapshot={snapshot}",
                    "-f",
                    str(path),
                    *args,
                ],
                check=True,
                env=env,
                capture_output=True,
                text=True,
                timeout=3600,
            )
            cursor.execute("COMMIT")
        run.file_name, run.size_bytes, run.sha256 = path.name, path.stat().st_size, _sha256(path)
        run.details, run.ok = {"counts": counts}, True
    except (subprocess.SubprocessError, OSError, RuntimeError) as exc:
        run.error = getattr(exc, "stderr", None) or str(exc)
    run.finished_at, run.seconds = timezone.now(), round(time.perf_counter() - clock, 2)
    run.save()
    _prune()
    if not run.ok:
        raise RuntimeError(f"Backup failed: {run.error[:300]}")
    return {"file": run.file_name, "bytes": run.size_bytes}


def _prune() -> None:
    keep = set(
        BackupRun.objects.filter(kind=BackupKind.BACKUP, ok=True)
        .order_by("-started_at")
        .values_list("file_name", flat=True)[:KEEP]
    )
    for path in backup_dir().glob("ridepulse-*.dump"):
        if path.name not in keep:
            path.unlink(missing_ok=True)


@tracked("restore-drill", every=timedelta(days=7))
def restore_drill(*, user=None) -> dict:
    import psycopg

    started, clock = timezone.now(), time.perf_counter()
    run = BackupRun.objects.create(kind=BackupKind.DRILL, started_at=started, started_by=user)
    checks: list[dict] = []
    source = (
        BackupRun.objects.filter(kind=BackupKind.BACKUP, ok=True).order_by("-started_at").first()
    )
    scratch = f"ridepulse_drill_{started:%Y%m%d%H%M%S}"
    admin = _conninfo()
    created = False
    try:
        if source is None:
            raise RuntimeError("There's no backup to restore yet.")
        path = backup_dir() / source.file_name
        checks.append(
            {"check": "Backup file is there", "ok": path.exists(), "detail": source.file_name}
        )
        if not path.exists():
            raise RuntimeError(f"{source.file_name} is missing from {backup_dir()}")
        same = _sha256(path) == source.sha256
        checks.append({"check": "Checksum matches", "ok": same, "detail": source.sha256[:12]})
        if not same:
            raise RuntimeError("The backup file has changed since it was written.")
        with psycopg.connect(**admin) as conn:
            conn.execute(f'CREATE DATABASE "{scratch}"')
        created = True
        args, env = _db(scratch)
        restore_clock = time.perf_counter()
        subprocess.run(
            [_bin("pg_restore"), "--no-owner", "--exit-on-error", *args, str(path)],
            check=True,
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,
        )
        restore_seconds = round(time.perf_counter() - restore_clock, 2)
        checks.append(
            {
                "check": "Restores without errors",
                "ok": True,
                "detail": f"{restore_seconds}s to restore",
            }
        )
        with psycopg.connect(**{**admin, "dbname": scratch}) as conn, conn.cursor() as cursor:
            restored = _counts(cursor)
            cursor.execute("SELECT coalesce(sum(amount), 0) FROM payments_ledgerentry")
            ledger_total = cursor.fetchone()[0]
            cursor.execute(
                "SELECT count(*) FROM (SELECT transaction_id FROM payments_ledgerentry "
                "GROUP BY transaction_id HAVING sum(amount) <> 0) t"
            )
            unbalanced = cursor.fetchone()[0]
        expected = source.details.get("counts", {})
        for table in KEY_TABLES:
            ok = restored.get(table) == expected.get(table)
            checks.append(
                {
                    "check": f"{table} rows",
                    "ok": ok,
                    "detail": f"{restored.get(table)} restored, {expected.get(table)} backed up",
                }
            )
        checks.append(
            {
                "check": "Ledger balances",
                "ok": ledger_total == 0 and unbalanced == 0,
                "detail": f"total {ledger_total}, {unbalanced} unbalanced transactions",
            }
        )
        run.ok = all(c["ok"] for c in checks)
        run.file_name = source.file_name
        run.details = {
            "checks": checks,
            "restore_seconds": restore_seconds,
            "backup_age_hours": round((started - source.started_at).total_seconds() / 3600, 1),
        }
    except (subprocess.SubprocessError, OSError, RuntimeError, psycopg.Error) as exc:
        run.error = (getattr(exc, "stderr", None) or str(exc))[:2000]
        run.details = {"checks": checks}
    finally:
        if created:
            with psycopg.connect(**admin) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
    run.finished_at, run.seconds = timezone.now(), round(time.perf_counter() - clock, 2)
    run.save()
    if not run.ok:
        _alert(run)
        raise RuntimeError(f"Restore drill failed: {run.error or 'a check failed'}")
    return {"restore_seconds": run.details["restore_seconds"], "checks": len(checks)}


def _alert(run: BackupRun) -> None:
    from apps.accounts.models import Role, User
    from apps.notifications.models import Level
    from apps.notifications.services import notify

    for admin in User.objects.filter(role=Role.ADMIN, is_active=True)[:10]:
        notify(
            admin,
            "Restore drill failed",
            run.error[:200] or "A check failed: see Backups.",
            level=Level.DANGER,
            link="/ops/backups",
        )


def row(run: BackupRun) -> dict:
    return {
        "id": run.pk,
        "kind": run.kind,
        "kind_label": run.get_kind_display(),
        "started_at": run.started_at,
        "seconds": run.seconds,
        "ok": run.ok,
        "file_name": run.file_name,
        "size_bytes": run.size_bytes,
        "sha256": run.sha256[:12],
        "details": run.details,
        "error": run.error[:500],
        "by": run.started_by.get_full_name() if run.started_by_id else "Scheduled",
    }


def overview() -> dict:
    last_backup = BackupRun.objects.filter(kind=BackupKind.BACKUP, ok=True).first()
    last_drill = BackupRun.objects.filter(kind=BackupKind.DRILL).first()
    now = timezone.now()
    return {
        "backup_dir": str(backup_dir()),
        "keep": KEEP,
        "last_backup_hours": round((now - last_backup.started_at).total_seconds() / 3600, 1)
        if last_backup
        else None,
        "last_drill_ok": last_drill.ok if last_drill else None,
        "last_restore_seconds": (last_drill.details or {}).get("restore_seconds")
        if last_drill
        else None,
        "runs": [row(r) for r in BackupRun.objects.select_related("started_by")[:40]],
    }
