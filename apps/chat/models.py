"""Team chat for staff: channels, direct messages, groups, and a thread on every task and
meeting."""

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db import models
from django.db.models import Q


class ConversationKind(models.TextChoices):
    CHANNEL = "CHANNEL", "Channel"
    DIRECT = "DIRECT", "Direct message"
    GROUP = "GROUP", "Group"
    TASK = "TASK", "Task thread"
    MEETING = "MEETING", "Meeting thread"
    TICKET = "TICKET", "Ticket thread"
    INCIDENT = "INCIDENT", "Incident war room"


class Conversation(models.Model):
    kind = models.CharField(max_length=8, choices=ConversationKind.choices)
    name = models.CharField(max_length=80, blank=True)
    slug = models.SlugField(max_length=60, blank=True)  # channels: "general", "support", …
    topic = models.CharField(max_length=200, blank=True)
    # One direct conversation per pair: "<smaller user id>:<larger user id>".
    direct_key = models.CharField(max_length=40, blank=True)
    task = models.OneToOneField(
        "workspace.WorkTask", null=True, blank=True, on_delete=models.CASCADE, related_name="chat"
    )
    meeting = models.OneToOneField(
        "workspace.Meeting", null=True, blank=True, on_delete=models.CASCADE, related_name="chat"
    )
    # The war room for a platform incident: the people who fix it, its updates and live numbers.
    incident = models.OneToOneField(
        "reliability.Incident",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="war_room",
    )
    # Staff discussing a support ticket (riders and drivers never see this thread).
    ticket = models.OneToOneField(
        "support.SupportTicket",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="team_chat",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField()
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["slug"], condition=Q(kind="CHANNEL"), name="chat_channel_slug_unique"
            ),
            models.UniqueConstraint(
                fields=["direct_key"], condition=Q(kind="DIRECT"), name="chat_one_direct_per_pair"
            ),
        ]

    def __str__(self) -> str:
        return self.name or f"{self.kind} {self.pk}"


class Member(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_memberships"
    )
    joined_at = models.DateTimeField()
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["conversation", "user"], name="chat_member_once")
        ]

    def __str__(self) -> str:
        return f"{self.user_id} in {self.conversation_id}"


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = models.TextField(max_length=4000, blank=True)
    # A shared file (images show inline; everything else downloads). Members only.
    attachment = models.FileField(upload_to="chat/%Y/%m/", blank=True)
    attachment_name = models.CharField(max_length=120, blank=True)
    attachment_size = models.PositiveIntegerField(default=0)
    mentions = ArrayField(models.IntegerField(), default=list, blank=True)
    # A pre-set reply from a demo employee nobody is signed in as (never from a real person).
    automated = models.BooleanField(default=False)
    created_at = models.DateTimeField()
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    reply_to = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # {"👍": [user ids], ...}
    reactions = models.JSONField(default=dict, blank=True)
    pinned_at = models.DateTimeField(null=True, blank=True)
    pinned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [
            models.Index(fields=["conversation", "created_at"], name="chat_msg_conv_time"),
            GinIndex(
                SearchVector("body", config="simple"), name="chat_msg_search"
            ),  # message search
        ]

    def __str__(self) -> str:
        return f"{self.conversation_id}: {self.body[:30]}"
