"""Trust and compliance: consent and data rights (India's DPDP Act), appeals, insurance claims,
support satisfaction (CSAT), saved replies and the help centre."""

from django.conf import settings
from django.db import models
from django.db.models import Q

# --- Consent and data rights -----------------------------------------------------------------


class ConsentPurpose(models.TextChoices):
    """Optional uses of personal data, each switched on only by the person (and as easy to
    switch off). Running the service itself (trips, payments, safety) needs no consent toggle."""

    MARKETING = "MARKETING", "Offers and promotions"
    CONTACT_SHARING = "CONTACT_SHARING", "Share my live trips with my trusted contacts"


class ConsentRecord(models.Model):
    """Append-only: every grant and withdrawal, with the notice version the person saw."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="consents"
    )
    purpose = models.CharField(max_length=16, choices=ConsentPurpose.choices)
    granted = models.BooleanField()
    notice_version = models.CharField(max_length=12)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return f"{self.user_id} {self.purpose} {'yes' if self.granted else 'no'}"


class RequestKind(models.TextChoices):
    EXPORT = "EXPORT", "Copy of my data"
    ERASURE = "ERASURE", "Delete my account"
    CORRECTION = "CORRECTION", "Correct my data"
    GRIEVANCE = "GRIEVANCE", "Privacy complaint"


class RequestStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    WAITING = "WAITING", "Cooling-off (can be cancelled)"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    COMPLETED = "COMPLETED", "Completed"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


class DataRequest(models.Model):
    number = models.CharField(max_length=20, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="data_requests"
    )
    # Kept so the request stays traceable after an erasure blanks the account.
    user_label = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=RequestKind.choices)
    status = models.CharField(
        max_length=12, choices=RequestStatus.choices, default=RequestStatus.RECEIVED
    )
    details = models.TextField(blank=True)
    due_at = models.DateTimeField()  # the response deadline
    execute_after = models.DateTimeField(null=True, blank=True)  # erasure cooling-off ends
    export_file = models.FileField(upload_to="data-exports/%Y/%m/", blank=True)
    export_expires_at = models.DateTimeField(null=True, blank=True)
    outcome = models.TextField(blank=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "kind"],
                condition=Q(status__in=["RECEIVED", "WAITING", "IN_PROGRESS"]),
                name="one_open_request_per_kind",
            )
        ]

    def __str__(self) -> str:
        return f"{self.number} {self.kind}"


# --- Appeals ---------------------------------------------------------------------------------


class AppealSubject(models.TextChoices):
    DRIVER_SUSPENSION = "DRIVER_SUSPENSION", "Driver account suspended"
    RIDER_BLOCK = "RIDER_BLOCK", "Rider account blocked"
    FRAUD_DECISION = "FRAUD_DECISION", "Fraud decision"


class AppealStatus(models.TextChoices):
    OPEN = "OPEN", "Waiting for review"
    UPHELD = "UPHELD", "Appeal accepted: decision reversed"
    DENIED = "DENIED", "Appeal rejected: decision stands"


class Appeal(models.Model):
    """A second look at a decision against someone, by a different reviewer."""

    number = models.CharField(max_length=20, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="appeals"
    )
    subject = models.CharField(max_length=20, choices=AppealSubject.choices)
    original_reason = models.CharField(max_length=255)
    original_decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    fraud_case = models.ForeignKey(
        "intelligence.FraudCase", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    statement = models.TextField()
    status = models.CharField(max_length=8, choices=AppealStatus.choices, default=AppealStatus.OPEN)
    due_at = models.DateTimeField()
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "subject"], condition=Q(status="OPEN"), name="one_open_appeal"
            )
        ]

    def __str__(self) -> str:
        return f"{self.number} {self.subject}"


# --- Insurance claims ------------------------------------------------------------------------


class ClaimKind(models.TextChoices):
    ACCIDENT = "ACCIDENT", "Accident"
    INJURY = "INJURY", "Injury"
    PROPERTY = "PROPERTY", "Damaged belongings"


class ClaimStatus(models.TextChoices):
    SUBMITTED = "SUBMITTED", "Submitted"
    UNDER_REVIEW = "UNDER_REVIEW", "With the insurer"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    PAID = "PAID", "Paid"


class InsuranceClaim(models.Model):
    """Per-trip accident cover (like the cover Indian ride apps include with every ride)."""

    number = models.CharField(max_length=20, unique=True)
    trip = models.ForeignKey("rides.Trip", on_delete=models.PROTECT, related_name="claims")
    claimant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="claims"
    )
    kind = models.CharField(max_length=10, choices=ClaimKind.choices)
    description = models.TextField()
    happened_at = models.DateTimeField()
    amount_claimed = models.DecimalField(max_digits=10, decimal_places=2)
    amount_approved = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=ClaimStatus.choices, default=ClaimStatus.SUBMITTED
    )
    insurer_reference = models.CharField(max_length=40, blank=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.number} {self.kind}"


class ClaimDocument(models.Model):
    claim = models.ForeignKey(InsuranceClaim, on_delete=models.CASCADE, related_name="documents")
    file = models.FileField(upload_to="claims/%Y/%m/")
    label = models.CharField(max_length=80, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.claim_id} {self.label}"


# --- Support quality -------------------------------------------------------------------------


class TicketRating(models.Model):
    """CSAT: how the person rated the help they got, once the ticket was resolved."""

    ticket = models.OneToOneField(
        "support.SupportTicket", on_delete=models.CASCADE, related_name="rating"
    )
    score = models.PositiveSmallIntegerField()  # 1-5
    comment = models.CharField(max_length=500, blank=True)
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(score__gte=1, score__lte=5), name="csat_score_1_to_5"
            )
        ]

    def __str__(self) -> str:
        return f"{self.ticket_id}: {self.score}"


class Macro(models.Model):
    """A saved reply for agents. {name}, {ticket} and {trip} are filled in when used."""

    title = models.CharField(max_length=80)
    body = models.TextField()
    category = models.CharField(max_length=16, blank=True)  # a TicketCategory, or any
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    uses = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-uses", "title"]

    def __str__(self) -> str:
        return self.title


class Audience(models.TextChoices):
    RIDER = "RIDER", "Riders"
    DRIVER = "DRIVER", "Drivers"
    ALL = "ALL", "Everyone"
    STAFF = "STAFF", "Staff handbook (internal)"


class HelpArticle(models.Model):
    slug = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=140)
    body = models.TextField()
    category = models.CharField(max_length=40)
    audience = models.CharField(max_length=6, choices=Audience.choices, default=Audience.ALL)
    keywords = models.CharField(max_length=255, blank=True)
    views = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "title"]

    def __str__(self) -> str:
        return self.title


class HelpVote(models.Model):
    """'Was this helpful?' One per person and article; a helpful vote with no ticket from that
    person in the next hour counts as a question solved without support (a deflection)."""

    article = models.ForeignKey(HelpArticle, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    helpful = models.BooleanField()
    created_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["article", "user"], name="one_help_vote_each")
        ]

    def __str__(self) -> str:
        return f"{self.article_id} {self.user_id} {self.helpful}"
