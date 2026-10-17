"""Team chat: channels by department and state, direct messages, groups, task threads,
@mentions, unread counts, privacy, and pre-set replies only from demo staff nobody is using."""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Role, StaffProfile
from apps.chat import services
from apps.chat.models import Conversation, Message
from apps.notifications.models import Notification
from apps.workspace import services as work

from ..conftest import make_rider, make_staff

pytestmark = pytest.mark.django_db

_ids = iter(range(1, 10_000))


def hire(role, department, state="Tamil Nadu", boss=None, *, first=None):
    user = make_staff(role)
    if first:
        user.first_name = first
        user.save(update_fields=["first_name"])
    StaffProfile.objects.create(
        user=user,
        employee_id=f"C{next(_ids):05d}",
        title=role.title(),
        department=department,
        state=state,
        reports_to=boss,
        joined_on=date(2025, 1, 1),
    )
    return user


@pytest.fixture
def team():
    boss = hire(Role.OPS_MANAGER, "OPERATIONS", first="Meena")
    boss_profile = boss.staff_profile
    agent = hire(Role.SUPPORT_AGENT, "SUPPORT", boss=boss_profile, first="Ravi")
    mechanic = hire(Role.FLEET_EXECUTIVE, "MAINTENANCE", "Karnataka", boss_profile, first="Divya")
    services.sync_channels()
    return boss, agent, mechanic


def test_channels_follow_department_and_state(team):
    _boss, agent, mechanic = team
    general = Conversation.objects.get(kind="CHANNEL", slug="general")
    assert general.members.count() == 3
    support = Conversation.objects.get(kind="CHANNEL", slug="support")
    assert set(support.members.values_list("user_id", flat=True)) == {agent.pk}
    karnataka = Conversation.objects.get(kind="CHANNEL", slug="karnataka")
    assert set(karnataka.members.values_list("user_id", flat=True)) == {mechanic.pk}
    assert services.sync_channels()["memberships_added"] == 0  # idempotent


def test_direct_messages_mentions_unread_and_privacy(api, team):
    boss, agent, mechanic = team
    dm = services.open_direct(boss, agent.pk)
    assert services.open_direct(agent, boss.pk) == dm  # one conversation per pair
    agent.last_login = timezone.now()  # Ravi is signed in: a real person, no pre-set reply
    agent.save(update_fields=["last_login"])
    services.send(dm, boss, "Can you check the refund queue today?")
    assert Message.objects.filter(conversation=dm, automated=True).count() == 0
    assert services.total_unread(agent) == 1
    services.mark_read(dm, agent)
    assert services.total_unread(agent) == 0

    general = Conversation.objects.get(slug="general")
    message = services.send(general, boss, "@divya please share the upkeep numbers")
    assert message.mentions == [mechanic.pk]
    assert Notification.objects.filter(user=mechanic, title__contains="mentioned you").exists()

    outsider = api(mechanic)
    assert outsider.get(f"/api/v1/chat/{dm.pk}/messages/").status_code == 403
    assert api(make_rider().user).get("/api/v1/chat/").status_code == 403  # staff only


def test_demo_staff_reply_only_when_nobody_is_signed_in_as_them(
    team, django_capture_on_commit_callbacks
):
    boss, _agent, mechanic = team  # mechanic has never signed in: a demo employee
    dm = services.open_direct(boss, mechanic.pk)
    with django_capture_on_commit_callbacks(execute=True):
        services.send(dm, boss, "Please send the service report by today")
    replies = Message.objects.filter(conversation=dm, author=mechanic)
    assert replies.count() == 1 and replies.get().automated
    assert replies.get().body in services.REPLIES["request"]


def test_groups_and_task_threads(api, team):
    boss, agent, mechanic = team
    with pytest.raises(Exception, match="two other people"):
        services.create_group(boss, name="Pair", member_ids=[agent.pk])
    group = services.create_group(boss, name="Monsoon prep", member_ids=[agent.pk, mechanic.pk])
    assert group.members.count() == 3
    task = work.create_tasks(
        manager=boss,
        title="Call 20 inactive drivers",
        due_at=timezone.now() + timedelta(days=1),
        assignee_ids=[agent.pk],
    )[0]
    client = api(agent)
    thread_id = client.post("/api/v1/chat/thread/", {"task_id": task.pk}, format="json").json()[
        "id"
    ]
    assert set(
        Conversation.objects.get(pk=thread_id).members.values_list("user_id", flat=True)
    ) == {
        boss.pk,
        agent.pk,
    }
    sent = client.post(f"/api/v1/chat/{thread_id}/send/", {"body": "Done 12 so far"}, format="json")
    assert sent.status_code == 201
    inbox = api(boss).get("/api/v1/chat/").json()
    assert inbox["unread"] >= 1
    assert any(c["kind"] == "TASK" and c["unread"] == 1 for c in inbox["conversations"])
