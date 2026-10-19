"""Team chat: who can talk where, sending (with @mentions), unread counts, live delivery, and
pre-set replies from demo employees.

* **Channels**: #general (everyone), one per department, one per state. Staff are members by
  their profile; ``sync_channels`` keeps that true as people join or move.
* **Direct messages** (one conversation per pair) and **groups** (named, up to 50 people).
* **Threads** on every task and meeting: the people on it are members, and anyone who can see
  the task or meeting can join the conversation by opening it.
* **@mentions**: ``@firstname.lastname`` or the part of their email before the @. A mention
  notifies the person even in a busy channel.
* **Live**: each new message goes to every member's own WebSocket (``/ws/chat/``).
* **Demo replies**: the 171 employees are demo accounts. When you message one who isn't signed
  in (no activity in the last 15 minutes), they answer with a short pre-set line, marked as an
  automatic demo reply. Anyone actually signed in replies themselves. Natural, written replies
  would need an AI service (on hold).
"""

import random
import re
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.utils import timezone
from django.utils.text import slugify

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation
from apps.notifications.models import Level
from apps.notifications.services import notify
from apps.realtime import broadcast

from .models import Conversation, ConversationKind, Member, Message

MAX_GROUP = 50
MAX_BODY = 4000
ACTIVE_WINDOW = timedelta(minutes=15)
MENTION = re.compile(r"@([a-z0-9][a-z0-9._-]{1,40})", re.IGNORECASE)


def _staff():
    from apps.accounts.models import User

    return User.objects.filter(is_active=True, staff_profile__isnull=False)


def _require_staff(user) -> None:
    if not getattr(user, "is_staff_member", False):
        raise ActionNotPermitted("Team chat is for Ride Pulse staff.")


# --- Channels --------------------------------------------------------------------------------


def _channel(slug: str, name: str, topic: str, now) -> Conversation:
    channel, _ = Conversation.objects.get_or_create(
        kind=ConversationKind.CHANNEL,
        slug=slug,
        defaults={"name": name, "topic": topic, "created_at": now},
    )
    return channel


def sync_channels(*, now: datetime | None = None) -> dict:
    """Create the standard channels and make every employee a member of theirs."""
    from apps.accounts.models import Department, StaffProfile

    now = now or timezone.now()
    wanted: dict[int, set[int]] = {}
    general = _channel("general", "general", "Company-wide news and questions", now)
    profiles = list(
        StaffProfile.objects.filter(user__is_active=True).values_list(
            "user_id", "department", "state"
        )
    )
    wanted[general.pk] = {uid for uid, _, _ in profiles}
    for code, label in Department.choices:
        channel = _channel(slugify(code.lower()), slugify(label), f"The {label} team", now)
        wanted[channel.pk] = {uid for uid, dept, _ in profiles if dept == code}
    for state in sorted({s for _, _, s in profiles if s}):
        channel = _channel(slugify(state), slugify(state), f"Everyone working in {state}", now)
        wanted[channel.pk] = {uid for uid, _, s in profiles if s == state}
    added = 0
    # The commander, the chief of staff and administrators sit in every channel.
    from apps.accounts.models import Role

    top = {uid for uid, *_ in profiles} & set(
        StaffProfile.objects.filter(
            user__role__in=[Role.COMMANDER, Role.CHIEF_OF_STAFF, Role.ADMIN], user__is_active=True
        ).values_list("user_id", flat=True)
    )
    for users in wanted.values():
        users |= top
    for conversation_id, users in wanted.items():
        have = set(
            Member.objects.filter(conversation_id=conversation_id).values_list("user_id", flat=True)
        )
        new = [
            Member(conversation_id=conversation_id, user_id=u, joined_at=now) for u in users - have
        ]
        Member.objects.bulk_create(new, ignore_conflicts=True)
        added += len(new)
    return {"channels": len(wanted), "memberships_added": added}


# --- Starting conversations --------------------------------------------------------------------


def _add(conversation: Conversation, user_ids, now) -> None:
    Member.objects.bulk_create(
        [Member(conversation=conversation, user_id=u, joined_at=now) for u in set(user_ids)],
        ignore_conflicts=True,
    )


def open_direct(user, other_id: int, *, now=None) -> Conversation:
    _require_staff(user)
    now = now or timezone.now()
    if other_id == user.pk:
        raise BusinessRuleViolation("Pick someone else to message.")
    if not _staff().filter(pk=other_id).exists():
        raise BusinessRuleViolation("That person isn't on the team.")
    key = f"{min(user.pk, other_id)}:{max(user.pk, other_id)}"
    try:
        with transaction.atomic():
            conversation, created = Conversation.objects.get_or_create(
                kind=ConversationKind.DIRECT,
                direct_key=key,
                defaults={"created_by": user, "created_at": now},
            )
    except IntegrityError:
        conversation, created = Conversation.objects.get(kind="DIRECT", direct_key=key), False
    if created:
        _add(conversation, [user.pk, other_id], now)
    return conversation


def create_group(user, *, name: str, member_ids: list[int], now=None) -> Conversation:
    _require_staff(user)
    now = now or timezone.now()
    name = " ".join(name.split())[:80]
    if len(name) < 2:
        raise BusinessRuleViolation("Give the group a name.", field="name")
    ids = set(_staff().filter(pk__in=member_ids).values_list("pk", flat=True)) | {user.pk}
    if len(ids) < 3:
        raise BusinessRuleViolation("A group needs at least two other people.", field="member_ids")
    if len(ids) > MAX_GROUP:
        raise BusinessRuleViolation(f"Groups can have up to {MAX_GROUP} people.")
    conversation = Conversation.objects.create(
        kind=ConversationKind.GROUP, name=name, created_by=user, created_at=now
    )
    _add(conversation, ids, now)
    _system(conversation, f"{user.get_full_name()} created the group", now)
    return conversation


def thread_for(
    user,
    *,
    task_id: int | None = None,
    meeting_id: int | None = None,
    ticket_id: int | None = None,
    now=None,
):
    """The conversation on a task, meeting or support ticket (made on first use). Opening it
    joins you."""
    from apps.workspace.services import visible_meetings, visible_tasks

    _require_staff(user)
    now = now or timezone.now()
    if task_id:
        task = visible_tasks(user).filter(pk=task_id).first()
        if task is None:
            raise ActionNotPermitted("You can't see that task.")
        conversation, _ = Conversation.objects.get_or_create(
            task=task,
            defaults={
                "kind": ConversationKind.TASK,
                "name": f"{task.number}: {task.title}"[:80],
                "created_at": now,
            },
        )
        people = [task.assignee_id, task.assigned_by_id]
    elif meeting_id:
        meeting = visible_meetings(user).filter(pk=meeting_id).first()
        if meeting is None:
            raise ActionNotPermitted("You can't see that meeting.")
        conversation, _ = Conversation.objects.get_or_create(
            meeting=meeting,
            defaults={
                "kind": ConversationKind.MEETING,
                "name": f"{meeting.number}: {meeting.title}"[:80],
                "created_at": now,
            },
        )
        people = [meeting.organizer_id, *meeting.attendees.values_list("user_id", flat=True)]
    elif ticket_id:
        from apps.accounts.roles import Cap
        from apps.support.models import SupportTicket

        if not user.has_capability(Cap.SUPPORT_VIEW):
            raise ActionNotPermitted("You can't see support tickets.")
        ticket = SupportTicket.objects.filter(pk=ticket_id).first()
        if ticket is None:
            raise ActionNotPermitted("That ticket doesn't exist.")
        conversation, _ = Conversation.objects.get_or_create(
            ticket=ticket,
            defaults={
                "kind": ConversationKind.TICKET,
                "name": f"{ticket.ticket_number}: {ticket.subject}"[:80],
                "created_at": now,
            },
        )
        people = [ticket.assigned_to_id] if ticket.assigned_to_id else []
    else:
        raise BusinessRuleViolation("Choose a task, a meeting or a ticket.")
    _add(conversation, [p for p in [*people, user.pk] if p], now)
    return conversation


# --- Messages ---------------------------------------------------------------------------------


def _member_ids(conversation: Conversation) -> list[int]:
    return list(conversation.members.values_list("user_id", flat=True))


def _deliver(conversation: Conversation, message: Message) -> None:
    payload = message_row(message)
    payload["conversation_id"] = conversation.pk
    for user_id in _member_ids(conversation):
        broadcast.user_event(user_id, "chat.message", payload)


def _system(conversation: Conversation, text: str, now) -> Message:
    message = Message.objects.create(conversation=conversation, body=text, created_at=now)
    Conversation.objects.filter(pk=conversation.pk).update(last_message_at=now)
    return message


EVERYONE = {"all", "here", "channel", "everyone"}


def _named(body: str, members: set[int], *, exclude: int) -> list[int]:
    """Members called by name without an @ ("Ananya, can you…" or "thanks Ananya Iyer").
    A full name always counts; a first name only when one member in the chat has it."""
    text = " " + re.sub(r"[^a-z0-9 ]+", " ", body.lower()) + " "
    people = list(
        _staff().filter(pk__in=members).exclude(pk=exclude).only("pk", "first_name", "last_name")
    )
    first_count: dict[str, int] = {}
    for u in people:
        first_count[u.first_name.lower()] = first_count.get(u.first_name.lower(), 0) + 1
    found = []
    for u in people:
        first, full = u.first_name.lower(), f"{u.first_name} {u.last_name}".lower().strip()
        if len(first) < 3:
            continue
        if f" {full} " in text or (first_count[first] == 1 and f" {first} " in text):
            found.append(u.pk)
    return found


def _mentioned(body: str, members: set[int]) -> list[int]:
    handles = {h.lower().rstrip(".") for h in MENTION.findall(body)}
    if not handles:
        return []
    if handles & EVERYONE:
        return sorted(members)
    found = []
    for user in _staff().filter(pk__in=members).only("pk", "email", "first_name", "last_name"):
        names = {
            user.email.split("@")[0].lower(),
            f"{user.first_name}.{user.last_name}".lower().replace(" ", ""),
            user.first_name.lower(),
        }
        if handles & names:
            found.append(user.pk)
    return found


def send(
    conversation: Conversation, user, body: str, *, now=None, upload=None, reply_to=None
) -> Message:
    _require_staff(user)
    now = now or timezone.now()
    body = body.strip()
    if upload is not None:
        _check_upload(upload)
    if not body and upload is None:
        raise BusinessRuleViolation("Write a message first.", field="body")
    if len(body) > MAX_BODY:
        raise BusinessRuleViolation(f"Keep messages under {MAX_BODY} characters.", field="body")
    members = set(_member_ids(conversation))
    if user.pk not in members:
        raise ActionNotPermitted("Join this conversation to post in it.")
    if reply_to is not None and reply_to.conversation_id != conversation.pk:
        raise BusinessRuleViolation("You can only reply to a message in this chat.")
    message = Message.objects.create(
        conversation=conversation,
        author=user,
        body=body,
        reply_to=reply_to,
        mentions=sorted(
            {u for u in _mentioned(body, members) if u != user.pk}
            | set(_named(body, members, exclude=user.pk))
        ),
        created_at=now,
        attachment=upload or "",
        attachment_name=(getattr(upload, "name", "") or "")[:120],
        attachment_size=getattr(upload, "size", 0) or 0,
    )
    Conversation.objects.filter(pk=conversation.pk).update(last_message_at=now)
    Member.objects.filter(conversation=conversation, user=user).update(last_read_at=now)
    _deliver(conversation, message)
    where = "you" if conversation.kind == ConversationKind.DIRECT else title_for(conversation, user)
    for user_id in message.mentions:
        notify(
            _staff().get(pk=user_id),
            f"{user.get_full_name()} mentioned you in {where}",
            body[:200],
            level=Level.INFO,
            link=f"/ops/chat/{conversation.pk}",
        )
    if conversation.kind == ConversationKind.DIRECT:
        other = next(iter(members - {user.pk}), None)
        if other:
            notify(
                _staff().get(pk=other),
                f"Message from {user.get_full_name()}",
                body[:200],
                level=Level.INFO,
                link=f"/ops/chat/{conversation.pk}",
            )
    transaction.on_commit(lambda: demo_replies(conversation.pk, message.pk))
    return message


MAX_FILE = 10 * 1024 * 1024
ALLOWED_FILES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".txt",
    ".csv",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
}
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _ext(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


def _check_upload(upload) -> None:
    if _ext(upload.name) not in ALLOWED_FILES:
        raise BusinessRuleViolation(
            "Share images, PDFs, Office documents, CSV or text files.", field="file"
        )
    if upload.size > MAX_FILE:
        raise BusinessRuleViolation("Files can be up to 10 MB.", field="file")


def typing(conversation: Conversation, user) -> None:
    """Tell the other members someone is typing (nothing is stored)."""
    payload = {"conversation_id": conversation.pk, "user_id": user.pk, "name": user.first_name}
    for user_id in _member_ids(conversation):
        if user_id != user.pk:
            broadcast.user_event(user_id, "chat.typing", payload)


def search(user, q: str, *, limit: int = 40) -> list[dict]:
    """Messages matching the words, in conversations you're in, newest first."""
    from django.contrib.postgres.search import SearchQuery, SearchVector

    q = q.strip()
    if len(q) < 2:
        return []
    mine = Member.objects.filter(user=user).values("conversation_id")
    rows = (
        Message.objects.annotate(search=SearchVector("body", config="simple"))
        .filter(conversation_id__in=mine)
        .filter(
            Q(search=SearchQuery(q, config="simple", search_type="websearch"))
            | Q(body__icontains=q)
            | Q(attachment_name__icontains=q)
        )
        .select_related("author", "conversation")
        .order_by("-created_at")[:limit]
    )
    return [
        {
            **message_row(m),
            "conversation_id": m.conversation_id,
            "conversation": title_for(m.conversation, user),
        }
        for m in rows
    ]


def mark_read(conversation: Conversation, user, *, now=None) -> None:
    Member.objects.filter(conversation=conversation, user=user).update(
        last_read_at=now or timezone.now()
    )


# --- Demo replies -------------------------------------------------------------------------------

REPLIES = {
    "question": [
        "Good question, let me check and get back to you within the hour.",
        "I'll look into it and update here.",
        "Checking with my team now.",
    ],
    "request": [
        "On it.",
        "Sure, I'll take care of it today.",
        "Noted. I'll update the task when it's done.",
        "Will do. Expect an update by end of day.",
    ],
    "thanks": ["Happy to help!", "Anytime.", "👍"],
    "hello": ["Hi! How can I help?", "Hello! What do you need?", "Good to hear from you."],
    "other": ["Noted, thanks.", "Got it.", "Makes sense, thanks for the update.", "Understood."],
}


def _kind_of(body: str) -> str:
    text = body.lower()
    if any(w in text for w in ("thank", "thanks", "great job", "well done")):
        return "thanks"
    if text.rstrip().endswith("?") or text.startswith(
        ("can ", "could ", "what", "when", "why", "how")
    ):
        return "question"
    if any(w in text for w in ("please", "pls", "need you", "can you", "make sure", "by today")):
        return "request"
    if re.match(r"^(hi|hello|hey|good morning|vanakkam|namaste)\b", text):
        return "hello"
    return "other"


def _is_demo_offline(user, now) -> bool:
    return user.last_login is None or now - user.last_login > ACTIVE_WINDOW


def demo_replies(conversation_id: int, message_id: int, *, now=None) -> int:
    """Pre-set replies from demo employees who aren't signed in. In a direct message the other
    person answers. Elsewhere: the people @mentioned or named answer (two at most for @all);
    when nobody is named, one member of the conversation answers."""
    from apps.accounts.models import User

    now = now or timezone.now()
    message = Message.objects.select_related("author", "conversation").filter(pk=message_id).first()
    if message is None or message.automated or message.author is None:
        return 0
    conversation = message.conversation
    if conversation.kind == ConversationKind.DIRECT:
        responders = [u for u in _member_ids(conversation) if u != message.author_id]
    else:
        rng_pick = random.Random(message.pk * 7)
        everyone = bool({h.lower() for h in MENTION.findall(message.body)} & EVERYONE)
        others = sorted(
            u.pk
            for u in User.objects.filter(pk__in=_member_ids(conversation), is_active=True).exclude(
                pk=message.author_id
            )
            if _is_demo_offline(u, now)
        )
        if message.mentions and not everyone:
            responders = message.mentions
        else:  # nobody in particular (or everyone): someone answers
            responders = rng_pick.sample(others, min(2 if everyone else 1, len(others)))
    rng = random.Random(message.pk)
    sent = 0
    addressed = (
        f"@{message.author.first_name} " if conversation.kind != ConversationKind.DIRECT else ""
    )
    for user in User.objects.filter(pk__in=responders, is_active=True):
        if not _is_demo_offline(user, now):
            continue  # a real person is signed in: they'll reply themselves
        reply = Message.objects.create(
            conversation=conversation,
            author=user,
            body=addressed + rng.choice(REPLIES[_kind_of(message.body)]),
            automated=True,
            created_at=now + timedelta(seconds=1),
        )
        Conversation.objects.filter(pk=conversation.pk).update(last_message_at=reply.created_at)
        _deliver(conversation, reply)
        sent += 1
    return sent


# --- Reading ----------------------------------------------------------------------------------


def title_for(conversation: Conversation, user) -> str:
    if conversation.kind == ConversationKind.CHANNEL:
        return f"#{conversation.name}"
    if conversation.kind == ConversationKind.DIRECT:
        other = conversation.members.exclude(user=user).select_related("user").first()
        return other.user.get_full_name() if other else "Direct message"
    return conversation.name


def message_row(m: Message) -> dict:
    quoted = m.reply_to if m.reply_to_id else None
    return {
        "id": m.pk,
        "author_id": m.author_id,
        "author": m.author.get_full_name() if m.author_id else None,
        "body": "" if m.deleted_at else m.body,
        "deleted": m.deleted_at is not None,
        "edited": m.edited_at is not None,
        "pinned": m.pinned_at is not None,
        "reactions": {e: ids for e, ids in (m.reactions or {}).items() if ids},
        "reply_to": {
            "id": quoted.pk,
            "author": quoted.author.get_full_name() if quoted.author_id else "Ride Pulse",
            "body": "Message deleted" if quoted.deleted_at else quoted.body[:120],
        }
        if quoted
        else None,
        "mentions": m.mentions,
        "automated": m.automated,
        "system": m.author_id is None,
        "created_at": m.created_at.isoformat(),
        "file": {
            "name": m.attachment_name,
            "size": m.attachment_size,
            "image": _ext(m.attachment_name) in IMAGES,
            "url": f"/api/v1/chat/{m.conversation_id}/file/{m.pk}/",
        }
        if m.attachment
        else None,
    }


def inbox(user) -> list[dict]:
    """The person's conversations (channels first, then the newest activity), with unread
    counts."""
    _require_staff(user)
    last = Message.objects.filter(conversation=OuterRef("conversation")).order_by("-created_at")
    memberships = (
        Member.objects.filter(user=user)
        .select_related("conversation")
        .annotate(
            last_body=Subquery(last.values("body")[:1]),
            last_author=Subquery(last.values("author__first_name")[:1]),
        )
    )
    unread = _unread_counts(user)
    rows = []
    for member in memberships:
        c = member.conversation
        rows.append(
            {
                "id": c.pk,
                "kind": c.kind,
                "title": title_for(c, user),
                "topic": c.topic,
                "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
                "last_body": (member.last_body or "")[:120],
                "last_author": member.last_author,
                "unread": unread.get(c.pk, 0),
            }
        )
    channels = sorted((r for r in rows if r["kind"] == "CHANNEL"), key=lambda r: r["title"])
    others = sorted(
        (r for r in rows if r["kind"] != "CHANNEL"),
        key=lambda r: r["last_message_at"] or "",
        reverse=True,
    )
    return channels + others


def _unread_counts(user) -> dict[int, int]:
    """Messages from others after the person last read each conversation (one query; the
    membership condition and its read time come from the same join)."""
    rows = (
        Message.objects.filter(
            Q(conversation__members__last_read_at__isnull=True)
            | Q(created_at__gt=F("conversation__members__last_read_at")),
            conversation__members__user=user,
        )
        .exclude(author=user)
        .values("conversation_id")
        .annotate(n=Count("pk"))
    )
    return {r["conversation_id"]: r["n"] for r in rows}


def total_unread(user) -> int:
    return sum(_unread_counts(user).values())


# --- Reactions, pins, edits, tasks, presence -----------------------------------------------------

REACTIONS = ["👍", "❤️", "😂", "🎉", "🙏", "👀", "✅"]
EDIT_WINDOW = timedelta(minutes=5)


def _update(message: Message) -> None:
    payload = message_row(message)
    payload["conversation_id"] = message.conversation_id
    for user_id in _member_ids(message.conversation):
        broadcast.user_event(user_id, "chat.update", payload)


def _own_message(message: Message, user) -> None:
    if not Member.objects.filter(conversation_id=message.conversation_id, user=user).exists():
        raise ActionNotPermitted("You're not in this conversation.")


@transaction.atomic
def react(message: Message, user, emoji: str) -> Message:
    """Toggle a reaction."""
    _own_message(message, user)
    if emoji not in REACTIONS:
        raise BusinessRuleViolation("Pick one of the reactions.", field="emoji")
    message = Message.objects.select_for_update().get(pk=message.pk)
    ids = set(message.reactions.get(emoji, []))
    ids ^= {user.pk}
    message.reactions = {**message.reactions, emoji: sorted(ids)}
    message.save(update_fields=["reactions"])
    _update(message)
    return message


def pin(message: Message, user, *, pinned: bool, now=None) -> Message:
    _own_message(message, user)
    if message.deleted_at:
        raise BusinessRuleViolation("A deleted message can't be pinned.")
    message.pinned_at = (now or timezone.now()) if pinned else None
    message.pinned_by = user if pinned else None
    message.save(update_fields=["pinned_at", "pinned_by"])
    if pinned:
        _system(
            message.conversation,
            f"📌 {user.get_full_name()} pinned a message: {message.body[:80]}",
            message.pinned_at,
        )
    _update(message)
    return message


def _editable(message: Message, user, now) -> None:
    if message.author_id != user.pk or message.automated:
        raise ActionNotPermitted("You can only change your own messages.")
    if message.deleted_at:
        raise BusinessRuleViolation("This message was deleted.")
    if now - message.created_at > EDIT_WINDOW:
        raise BusinessRuleViolation("Messages can be changed for 5 minutes after sending.")


def edit(message: Message, user, body: str, *, now=None) -> Message:
    now = now or timezone.now()
    _editable(message, user, now)
    body = body.strip()
    if not body:
        raise BusinessRuleViolation("Write something, or delete the message.", field="body")
    message.body, message.edited_at = body[:MAX_BODY], now
    message.save(update_fields=["body", "edited_at"])
    _update(message)
    return message


def delete(message: Message, user, *, now=None) -> Message:
    now = now or timezone.now()
    _editable(message, user, now)
    message.deleted_at, message.pinned_at = now, None
    message.save(update_fields=["deleted_at", "pinned_at"])
    _update(message)
    return message


def to_task(message: Message, user, *, assignee_id: int, days: int = 2, now=None):
    """Turn a message into a task for someone in your team (or yourself)."""
    from apps.workspace.services import create_tasks

    _own_message(message, user)
    now = now or timezone.now()
    title = (message.body.strip().splitlines() or ["Follow up"])[0][:150]
    tasks = create_tasks(
        manager=user,
        title=title,
        due_at=now + timedelta(days=max(1, min(int(days), 30))),
        assignee_ids=[assignee_id],
        description=f"From team chat ({title_for(message.conversation, user)}), "
        f"{message.author.get_full_name() if message.author_id else 'Ride Pulse'} wrote: "
        f"{message.body[:500]}",
        now=now,
    )
    _system(
        message.conversation,
        f"✅ {user.get_full_name()} turned a message into a task: {title}",
        now,
    )
    return tasks[0]


def presence(user_ids, *, now=None) -> dict[int, str]:
    """Each person's status right now: in a meeting, on leave, online or away."""
    from apps.accounts.models import User
    from apps.workspace.models import LeaveRequest, Meeting

    now = now or timezone.now()
    today = timezone.localdate(now)
    ids = list(user_ids)
    leave = set(
        LeaveRequest.objects.filter(
            user_id__in=ids, starts_on__lte=today, ends_on__gte=today, status="APPROVED"
        ).values_list("user_id", flat=True)
    )
    meeting = set()
    for m in Meeting.objects.filter(
        starts_at__lte=now, starts_at__gte=now - timedelta(hours=3)
    ).prefetch_related("attendees"):
        if m.starts_at + timedelta(minutes=m.duration_minutes) > now:
            meeting |= {a.user_id for a in m.attendees.all()} | {m.organizer_id}
    online = set(
        User.objects.filter(pk__in=ids, last_login__gte=now - ACTIVE_WINDOW).values_list(
            "pk", flat=True
        )
    )
    return {
        u: "on leave"
        if u in leave
        else "in a meeting"
        if u in meeting
        else "online"
        if u in online
        else "away"
        for u in ids
    }
