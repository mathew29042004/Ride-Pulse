"""Backups and the restore drill against the real test database: a backup with a checksum and
row counts, a drill that restores it into a scratch database and passes every check, and a
tampered backup failing the drill (and alerting admins)."""

import pytest

from apps.accounts.models import Role
from apps.notifications.models import Notification
from apps.reliability import backups
from apps.reliability.models import BackupRun

from ..conftest import make_staff

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _dir(settings, tmp_path):
    settings.BACKUP_DIR = tmp_path


def test_backup_then_drill_passes(tmp_path):
    result = backups.backup()
    run = BackupRun.objects.get(kind="BACKUP")
    assert run.ok and (tmp_path / result["file"]).stat().st_size == run.size_bytes
    assert len(run.sha256) == 64 and "rides_trip" in run.details["counts"]
    drill = backups.restore_drill()
    assert drill["checks"] >= len(backups.KEY_TABLES) + 3
    last = BackupRun.objects.filter(kind="DRILL").get()
    assert last.ok and all(c["ok"] for c in last.details["checks"])


def test_a_tampered_backup_fails_the_drill_and_alerts(tmp_path):
    admin = make_staff(Role.ADMIN)
    result = backups.backup()
    with (tmp_path / result["file"]).open("ab") as f:
        f.write(b"x")
    with pytest.raises(RuntimeError, match="changed"):
        backups.restore_drill()
    assert not BackupRun.objects.filter(kind="DRILL").get().ok
    assert Notification.objects.filter(user=admin, title="Restore drill failed").exists()


def test_no_backup_yet():
    with pytest.raises(RuntimeError, match="no backup"):
        backups.restore_drill()


def test_api(api, ops):
    assert api(ops).get("/api/v1/ops/backups/").status_code in (200, 403)
    admin = make_staff(Role.ADMIN)
    client = api(admin)
    data = client.post("/api/v1/ops/backups/run/").json()
    assert data["runs"][0]["ok"] and data["last_backup_hours"] == 0
