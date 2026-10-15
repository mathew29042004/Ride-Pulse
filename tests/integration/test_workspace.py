"""Manager workspace: tasks, daily meetings and check-ins down the org chart."""

from datetime import date, timedelta

import pytest

from apps.accounts.models import Role, StaffProfile
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation
from apps.notifications.models import Notification
from apps.workspace import scorecards, services
from apps.workspace.models import Meeting, MeetingStatus, TaskStatus

from ..conftest import make_staff

pytestmark = pytest.mark.django_db

_ids = iter(range(1, 10_000))


def hire(user, title, department="OPERATIONS", boss=None):
    return StaffProfile.objects.create(
        user=user,
        employee_id=f"T{next(_ids):05d}",
        title=title,
        department=department,
        reports_to=boss,
        joined_on=date(2025, 1, 1),
    )


@pytest.fixture
def org(admin):
    """admin → regional → associate (rides) → two fleet executives; plus another regional."""
    regional = make_staff(Role.REGIONAL_MANAGER)
    associate = make_staff(Role.ASSOC_RIDES)
    exec_a, exec_b = make_staff(Role.FLEET_EXECUTIVE), make_staff(Role.FLEET_EXECUTIVE)
    other_regional = make_staff(Role.REGIONAL_MANAGER)
    r = hire(regional, "Regional manager", "LEADERSHIP")
    hire(other_regional, "Regional manager", "LEADERSHIP")
    a = hire(associate, "Associate manager", "RIDES", r)
    hire(exec_a, "Fleet executive", "MAINTENANCE", a)
    hire(exec_b, "Fleet executive", "MAINTENANCE", a)
    return {
        "admin": admin,
        "regional": regional,
        "associate": associate,
        "exec_a": exec_a,
        "exec_b": exec_b,
        "other": other_regional,
    }


def test_admin_with_a_profile_manages_whoever_reports_to_them(org, now):
    top = hire(org["admin"], "Head of operations", "LEADERSHIP")
    StaffProfile.objects.filter(user=org["regional"]).update(reports_to=top)
    assert services.direct_reports(org["admin"]) == {org["regional"].pk, org["other"].pk}
    tasks = services.create_tasks(
        manager=org["admin"],
        title="Numbers",
        whole_team=True,
        due_at=now + timedelta(days=1),
        now=now,
    )
    assert {t.assignee for t in tasks} == {org["regional"], org["other"]}


def test_work_follows_the_org_chart(org, now):
    assert services.team_of(org["regional"]) == {
        org["associate"].pk,
        org["exec_a"].pk,
        org["exec_b"].pk,
    }
    assert org["other"].pk in services.team_of(org["admin"])
    assert services.direct_reports(org["admin"]) == {org["regional"].pk, org["other"].pk}
    with pytest.raises(ActionNotPermitted):  # not in their team
        services.create_tasks(
            manager=org["regional"],
            title="Audit cabs",
            assignee_ids=[org["other"].pk],
            due_at=now + timedelta(days=1),
            now=now,
        )
    with pytest.raises(ActionNotPermitted):  # no going up the chart
        services.create_tasks(
            manager=org["exec_a"],
            title="Help me",
            assignee_ids=[org["associate"].pk],
            due_at=now + timedelta(days=1),
            now=now,
        )


def test_team_task_progress_and_completion(org, now):
    tasks = services.create_tasks(
        manager=org["associate"],
        title="Verify 20 drivers today",
        whole_team=True,
        target=20,
        priority="HIGH",
        due_at=now + timedelta(hours=8),
        now=now,
    )
    assert {t.assignee for t in tasks} == {org["exec_a"], org["exec_b"]}
    assert len({t.batch for t in tasks}) == 1 and tasks[0].batch
    assert Notification.objects.filter(user=org["exec_a"], title__startswith="New task").exists()

    task = next(t for t in tasks if t.assignee == org["exec_a"])
    with pytest.raises(ActionNotPermitted):
        services.update_task(task, user=org["exec_b"], progress=5)
    task = services.update_task(task, user=org["exec_a"], progress=8, now=now)
    assert task.status == TaskStatus.TODO and task.progress == 8
    task = services.update_task(task, user=org["exec_a"], progress=20, now=now)
    assert task.status == TaskStatus.DONE and task.completed_at == now
    assert Notification.objects.filter(user=org["associate"], title__contains="finished").exists()


def test_status_requests_comments_and_overdue(org, now):
    (task,) = services.create_tasks(
        manager=org["regional"],
        title="Weekly safety report",
        assignee_ids=[org["associate"].pk],
        due_at=now + timedelta(hours=2),
        now=now,
    )
    with pytest.raises(ActionNotPermitted):  # a peer can't chase
        services.ask_status(task, user=org["exec_a"])
    services.ask_status(task, user=org["admin"], now=now)  # admin is above everyone
    assert services.pending_status_requests(task)
    services.comment(task, user=org["associate"], body="Half done", now=now + timedelta(minutes=5))
    assert not services.pending_status_requests(task)

    assert services.flag_overdue(now=now + timedelta(hours=1)) == 0
    assert services.flag_overdue(now=now + timedelta(hours=3)) == 1
    assert services.flag_overdue(now=now + timedelta(hours=4)) == 0  # flagged once
    assert Notification.objects.filter(user=org["regional"], title__startswith="Overdue").exists()

    task = services.reassign_or_cancel(
        task, user=org["regional"], assignee_id=org["exec_b"].pk, now=now
    )
    assert task.assignee == org["exec_b"] and task.status == TaskStatus.TODO
    task = services.reassign_or_cancel(task, user=org["regional"], cancel=True, now=now)
    assert task.status == TaskStatus.CANCELLED


def test_daily_standup_with_action_items(org, now):
    with pytest.raises(BusinessRuleViolation):
        services.schedule_meeting(
            organizer=org["associate"], title="Stand-up", starts_at=now - timedelta(hours=1)
        )
    meeting = services.schedule_meeting(
        organizer=org["associate"],
        title="Fleet stand-up",
        starts_at=now + timedelta(hours=1),
        whole_team=True,
        agenda="Pending documents",
        repeats_daily=True,
        now=now,
    )
    assert meeting.attendees.count() == 3  # organiser + two executives
    services.respond(meeting, user=org["exec_b"], accept=False)
    assert Notification.objects.filter(user=org["associate"], title__contains="can't make").exists()
    with pytest.raises(ActionNotPermitted):
        services.respond(meeting, user=org["other"], accept=True)

    meeting, tasks = services.complete_meeting(
        meeting,
        user=org["associate"],
        notes="Backlog is 40 documents",
        present_ids=[org["exec_a"].pk],
        action_items=[{"title": "Clear the RC backlog", "assignee_id": org["exec_a"].pk}],
        now=now + timedelta(hours=1, minutes=20),
    )
    assert meeting.status == MeetingStatus.DONE
    assert tasks[0].meeting == meeting and tasks[0].assignee == org["exec_a"]
    assert meeting.attendees.get(user=org["exec_b"]).attended is False
    following = Meeting.objects.filter(series=meeting.series).exclude(pk=meeting.pk).get()
    assert following.starts_at > meeting.starts_at and following.status == "SCHEDULED"
    assert services.roll_daily_standups(now=now) == 0  # nothing missing


def test_dashboard_scorecards(org, now):
    services.create_tasks(
        manager=org["regional"],
        title="Overdue thing",
        assignee_ids=[org["exec_a"].pk],
        due_at=now + timedelta(minutes=1),
        now=now,
    )
    (done,) = services.create_tasks(
        manager=org["regional"],
        title="Quick win",
        assignee_ids=[org["exec_b"].pk],
        due_at=now + timedelta(hours=1),
        now=now,
    )
    services.update_task(done, user=org["exec_b"], status="DONE", now=now)
    board = scorecards.scorecards(org["regional"], now=now + timedelta(minutes=5))
    assert board["totals"]["people"] == 3
    assert board["totals"]["overdue_tasks"] == 1 and board["totals"]["done_tasks"] == 1
    row = next(r for r in board["people"] if r["user_id"] == org["exec_b"].pk)
    assert row["on_time_rate"] == 100 and not row["direct_report"]
    assert board["people"][0]["user_id"] == org["exec_a"].pk  # overdue people first


def test_api(api, org, now):
    boss, worker = api(org["associate"]), api(org["exec_a"])
    people = boss.get("/api/v1/work/people/").json()
    assert {p["id"] for p in people} == {org["exec_a"].pk, org["exec_b"].pk}
    created = boss.post(
        "/api/v1/work/tasks/",
        {
            "title": "Call 5 inactive drivers",
            "assignee_ids": [org["exec_a"].pk],
            "due_at": (now + timedelta(days=1)).isoformat(),
            "target": 5,
        },
        format="json",
    )
    assert created.status_code == 201
    pk = created.json()[0]["id"]
    assert worker.get("/api/v1/work/tasks/?scope=mine").json()["results"][0]["id"] == pk
    boss.post(f"/api/v1/work/tasks/{pk}/ask_status/")
    assert worker.get(f"/api/v1/work/tasks/{pk}/").json()["awaiting_update"] is True
    done = worker.post(
        f"/api/v1/work/tasks/{pk}/update_status/", {"progress": 5, "note": "All called"}
    ).json()
    assert done["status"] == "DONE" and done["comments"][-1]["body"] == "All called"
    assert api(org["exec_b"]).get(f"/api/v1/work/tasks/{pk}/").status_code == 404
    assert boss.get("/api/v1/work/dashboard/").json()["totals"]["done_tasks"] == 1

    meeting = boss.post(
        "/api/v1/work/meetings/",
        {
            "title": "Stand-up",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "whole_team": True,
            "repeats_daily": True,
        },
        format="json",
    ).json()
    assert (
        worker.get("/api/v1/work/meetings/?when=upcoming").json()["results"][0]["my_response"]
        == "INVITED"
    )
    worker.post(f"/api/v1/work/meetings/{meeting['id']}/respond/", {"accept": True})
    assert api(make_staff(Role.RIDER)).get("/api/v1/work/tasks/").status_code == 403


def test_staff_bots_do_their_work(org, now, monkeypatch):
    import random

    from apps.workspace import bots

    monkeypatch.setattr(bots, "SLACKER_SHARE", 0)

    (task,) = services.create_tasks(
        manager=org["associate"],
        title="Verify 10 drivers",
        assignee_ids=[org["exec_a"].pk],
        target=10,
        due_at=now + timedelta(hours=1),
        now=now,
    )
    services.schedule_meeting(
        organizer=org["associate"],
        title="Stand-up",
        starts_at=now + timedelta(hours=1),
        whole_team=True,
        now=now,
    )
    rng = random.Random(4)
    for minutes in range(2, 60, 2):
        bots.tick(now=now + timedelta(minutes=minutes), rng=rng)
    task.refresh_from_db()
    assert task.status == TaskStatus.DONE and task.progress == 10
    assert not Meeting.objects.get().attendees.filter(response="INVITED").exists()
