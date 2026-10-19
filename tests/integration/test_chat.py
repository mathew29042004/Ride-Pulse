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


def _general():
    return Conversation.objects.get(kind="CHANNEL", slug="general")


def test_named_without_at_gets_the_reply(team, django_capture_on_commit_callbacks):
    boss, _agent, mechanic = team
    with django_capture_on_commit_callbacks(execute=True):
        services.send(_general(), boss, "Divya, can you check the Hosur workshop queue?")
    msg = Message.objects.filter(author=boss).latest("pk")
    assert msg.mentions == [mechanic.pk]  # named, no @, still counts
    reply = Message.objects.filter(automated=True).get()
    assert reply.author == mechanic and reply.body.startswith("@Meena ")


def test_at_mention_gets_only_that_person(team, django_capture_on_commit_callbacks):
    boss, agent, _mechanic = team
    with django_capture_on_commit_callbacks(execute=True):
        services.send(_general(), boss, "@ravi please close the refund tickets by today")
    assert list(Message.objects.filter(automated=True).values_list("author", flat=True)) == [
        agent.pk
    ]


def test_no_name_means_anyone_answers(team, django_capture_on_commit_callbacks):
    boss, agent, mechanic = team
    with django_capture_on_commit_callbacks(execute=True):
        services.send(_general(), boss, "Who is covering the night shift?")
    replies = Message.objects.filter(automated=True)
    assert replies.count() == 1 and replies.get().author_id in {agent.pk, mechanic.pk}


def test_at_all_notifies_everyone(team):
    boss, agent, mechanic = team
    services.send(_general(), boss, "@all town hall at 4 pm")
    msg = Message.objects.filter(author=boss).latest("pk")
    assert set(msg.mentions) == {agent.pk, mechanic.pk}
    assert Notification.objects.filter(user=agent, title__contains="mentioned you").exists()


def test_reply_react_pin_edit_delete_and_task(team, api):
    from datetime import timedelta

    boss, agent, mechanic = team
    general = _general()
    first = services.send(general, agent, "Hosur workshop has 12 cars waiting")
    answer = services.send(general, boss, "On it", reply_to=first)
    assert services.message_row(answer)["reply_to"]["id"] == first.pk
    r = api(mechanic).post(f"/api/v1/chat-messages/{first.pk}/react/", {"emoji": "👍"})
    assert r.json()["reactions"] == {"👍": [mechanic.pk]}
    api(mechanic).post(f"/api/v1/chat-messages/{first.pk}/react/", {"emoji": "👍"})
    first.refresh_from_db()
    assert first.reactions["👍"] == []  # toggled off
    api(boss).post(f"/api/v1/chat-messages/{first.pk}/pin/", {"pinned": True}, format="json")
    view = api(boss).get(f"/api/v1/chat/{general.pk}/messages/").json()
    assert view["pinned"][0]["id"] == first.pk
    assert {m["id"]: m["status"] for m in view["members"]}[boss.pk] in {"online", "away"}
    assert (
        api(boss).post(f"/api/v1/chat-messages/{first.pk}/edit/", {"body": "x"}).status_code == 403
    )  # not their message
    api(agent).post(f"/api/v1/chat-messages/{first.pk}/edit/", {"body": "Hosur: 14 cars"})
    first.refresh_from_db()
    assert first.body == "Hosur: 14 cars" and first.edited_at
    with pytest.raises(Exception, match="5 minutes"):
        services.edit(first, agent, "late", now=first.created_at + timedelta(minutes=6))
    t = api(boss).post(
        f"/api/v1/chat-messages/{first.pk}/task/", {"assignee_id": mechanic.pk}, format="json"
    )
    assert t.status_code == 201
    api(agent).post(f"/api/v1/chat-messages/{first.pk}/remove/")
    first.refresh_from_db()
    assert services.message_row(first)["deleted"] and not services.message_row(first)["body"]
