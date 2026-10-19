"""The company portal, in two halves.

**Public website** (no sign-in): about Ride Pulse with live numbers, the leadership team, careers
(open roles with an application form) and a contact form. Applications reach the HR managers;
contact messages reach the administrators.

**Employee intranet** (every staff member): messages from the commander to the whole company,
staff announcements, birthdays and work anniversaries this week, new joiners, departments with
their heads and headcount, upcoming holidays, the people directory, open roles to refer friends
to, and quick links. HR reviews applications from here; the commander posts company messages.
"""

from datetime import date, timedelta

from django.conf import settings
from django.db import models, transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation, InvalidStateTransition


class JobOpening(models.Model):
    title = models.CharField(max_length=120)
    department = models.CharField(max_length=12)
    city = models.ForeignKey(
        "geo.City", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    kind = models.CharField(max_length=12, default="Full-time")
    role = models.CharField(max_length=24, default="SUPPORT_AGENT")  # the role a hire gets
    summary = models.CharField(max_length=300)
    description = models.TextField()
    is_open = models.BooleanField(default=True)
    posted_at = models.DateTimeField()

    class Meta:
        app_label = "workspace"
        ordering = ["-posted_at"]

    def __str__(self) -> str:
        return self.title


class JobApplication(models.Model):
    STATUSES = [
        ("NEW", "New"),
        ("SHORTLISTED", "Shortlisted"),
        ("INTERVIEW", "Interview"),
        ("HIRED", "Hired"),
        ("REJECTED", "Not this time"),
    ]
    job = models.ForeignKey(JobOpening, on_delete=models.CASCADE, related_name="applications")
    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    profile_url = models.URLField(blank=True)
    note = models.TextField(max_length=2000, blank=True)
    referred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=12, choices=STATUSES, default="NEW")
    applied_at = models.DateTimeField()
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        app_label = "workspace"
        ordering = ["-applied_at"]
        constraints = [
            models.UniqueConstraint(fields=["job", "email"], name="one_application_per_job")
        ]

    def __str__(self) -> str:
        return f"{self.name} → {self.job_id}"


class LeaderMessage(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    title = models.CharField(max_length=160)
    body = models.TextField(max_length=6000)
    posted_at = models.DateTimeField(db_index=True)

    class Meta:
        app_label = "workspace"
        ordering = ["-posted_at"]

    def __str__(self) -> str:
        return self.title


class ContactMessage(models.Model):
    TOPICS = [
        ("GENERAL", "General"),
        ("PARTNERSHIP", "Partnerships"),
        ("PRESS", "Press"),
        ("CORPORATE", "Business travel"),
    ]
    name = models.CharField(max_length=120)
    email = models.EmailField()
    topic = models.CharField(max_length=12, choices=TOPICS, default="GENERAL")
    message = models.TextField(max_length=3000)
    created_at = models.DateTimeField()
    handled = models.BooleanField(default=False)

    class Meta:
        app_label = "workspace"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.topic}: {self.name}"


# India's national holidays plus each state's main festivals (2026), for the intranet calendar.
HOLIDAYS = [
    (date(2026, 1, 1), "New Year's Day", ""),
    (date(2026, 1, 15), "Pongal", "Tamil Nadu"),
    (date(2026, 1, 15), "Makara Sankranti", "Karnataka"),
    (date(2026, 1, 15), "Sankranti", "Andhra Pradesh"),
    (date(2026, 1, 26), "Republic Day", ""),
    (date(2026, 3, 19), "Ugadi", "Karnataka"),
    (date(2026, 3, 19), "Ugadi", "Andhra Pradesh"),
    (date(2026, 4, 14), "Tamil New Year", "Tamil Nadu"),
    (date(2026, 4, 15), "Vishu", "Kerala"),
    (date(2026, 5, 1), "May Day", ""),
    (date(2026, 8, 15), "Independence Day", ""),
    (date(2026, 8, 26), "Onam", "Kerala"),
    (date(2026, 10, 2), "Gandhi Jayanti", ""),
    (date(2026, 10, 20), "Ayudha Pooja", "Tamil Nadu"),
    (date(2026, 10, 21), "Vijayadashami", ""),
    (date(2026, 11, 1), "Karnataka Rajyotsava", "Karnataka"),
    (date(2026, 11, 1), "Kerala Piravi", "Kerala"),
    (date(2026, 11, 8), "Deepavali", ""),
    (date(2026, 12, 25), "Christmas", ""),
]


# --- Public website ------------------------------------------------------------------------------


def about() -> dict:
    from apps.accounts.models import Department, Role, StaffProfile
    from apps.drivers.models import DriverProfile
    from apps.geo.models import City
    from apps.riders.models import RiderProfile
    from apps.rides.models import Trip, TripStatus

    leaders = (
        StaffProfile.objects.filter(
            user__role__in=[Role.COMMANDER, Role.CHIEF_OF_STAFF, Role.REGIONAL_MANAGER],
            user__is_active=True,
        )
        .select_related("user")
        .order_by("employee_id")
    )
    order = {Role.COMMANDER: 0, Role.CHIEF_OF_STAFF: 1, Role.REGIONAL_MANAGER: 2}
    cities = City.objects.filter(is_active=True)
    return {
        "numbers": {
            "cities": cities.count(),
            "states": cities.values("state").distinct().count(),
            "drivers": DriverProfile.objects.filter(onboarding_status="APPROVED").count(),
            "riders": RiderProfile.objects.count(),
            "trips": Trip.objects.filter(status=TripStatus.COMPLETED).count(),
            "employees": StaffProfile.objects.filter(user__is_active=True).count(),
        },
        "cities": sorted(cities.values_list("name", flat=True)),
        "leaders": [
            {"name": p.user.get_full_name(), "title": p.title}
            for p in sorted(leaders, key=lambda p: order.get(p.user.role, 9))
        ],
        "departments": [label for _, label in Department.choices],
        "open_roles": JobOpening.objects.filter(is_open=True).count(),
    }


def job_row(j: JobOpening, *, full: bool = False) -> dict:
    from apps.accounts.models import Department

    row = {
        "id": j.pk,
        "title": j.title,
        "department": Department(j.department).label,
        "city": j.city.name if j.city else "Remote / any city",
        "kind": j.kind,
        "summary": j.summary,
        "posted_at": j.posted_at.isoformat(),
    }
    if full:
        row["description"] = j.description
    return row


def open_jobs():
    return JobOpening.objects.filter(is_open=True).select_related("city")


def apply(
    job: JobOpening,
    *,
    name: str,
    email: str,
    phone: str,
    profile_url: str = "",
    note: str = "",
    referred_by=None,
    now=None,
) -> JobApplication:
    from apps.accounts.models import User
    from apps.notifications.services import notify

    if not job.is_open:
        raise InvalidStateTransition("This role is no longer open.")
    digits = "".join(c for c in phone if c.isdigit())[-10:]
    if len(name.strip()) < 2 or len(digits) != 10:
        raise BusinessRuleViolation("Give your name and a 10-digit mobile number.")
    if JobApplication.objects.filter(job=job, email__iexact=email).exists():
        raise BusinessRuleViolation("You've already applied for this role.", field="email")
    a = JobApplication.objects.create(
        job=job,
        name=name.strip()[:120],
        email=email.lower(),
        phone=digits,
        profile_url=profile_url,
        note=note.strip()[:2000],
        referred_by=referred_by,
        applied_at=now or timezone.now(),
    )
    for hr in User.objects.filter(role="HR_MANAGER", is_active=True)[:10]:
        notify(
            hr,
            f"New application: {job.title}",
            f"{a.name}" + (f", referred by {referred_by.get_full_name()}" if referred_by else ""),
            link="/ops/company",
        )
    return a


def contact(*, name: str, email: str, topic: str, message: str, now=None) -> ContactMessage:
    from apps.accounts.models import User
    from apps.notifications.services import notify

    if len(message.strip()) < 10:
        raise BusinessRuleViolation("Tell us a little more.", field="message")
    m = ContactMessage.objects.create(
        name=name.strip()[:120],
        email=email,
        topic=topic if topic in dict(ContactMessage.TOPICS) else "GENERAL",
        message=message.strip()[:3000],
        created_at=now or timezone.now(),
    )
    for admin in User.objects.filter(role="ADMIN", is_active=True)[:5]:
        notify(admin, f"Website enquiry ({m.get_topic_display()})", f"{m.name}: {m.message[:150]}")
    return m


# --- Employee intranet ---------------------------------------------------------------------------


def _upcoming(today: date, days: int = 7) -> list[dict]:
    from apps.accounts.models import StaffProfile

    out = []
    for p in StaffProfile.objects.filter(user__is_active=True).select_related("user"):
        for when, what in (
            (p.date_of_birth, "Birthday"),
            (p.joined_on, "Work anniversary"),
        ):
            if not when:
                continue
            try:
                this_year = when.replace(year=today.year)
            except ValueError:  # 29 February
                this_year = date(today.year, 3, 1)
            delta = (this_year - today).days
            if 0 <= delta <= days and not (what == "Work anniversary" and when.year == today.year):
                years = today.year - when.year
                out.append(
                    {
                        "name": p.user.get_full_name(),
                        "title": p.title,
                        "what": what if what == "Birthday" else f"{years} years at Ride Pulse",
                        "date": this_year.isoformat(),
                        "today": delta == 0,
                    }
                )
    return sorted(out, key=lambda r: r["date"])[:12]


def intranet(user, *, now=None) -> dict:
    from apps.accounts.models import Department, StaffProfile
    from apps.announcements.models import Announcement

    now = now or timezone.now()
    today = timezone.localdate(now)
    state = getattr(getattr(user, "staff_profile", None), "state", "")
    heads = {}
    for p in StaffProfile.objects.filter(
        user__role__in=[
            "COMMANDER",
            "REGIONAL_MANAGER",
            "FINANCE_MANAGER",
            "HR_MANAGER",
            "SAFETY_OFFICER",
            "COMPLIANCE_OFFICER",
            "ASSOC_SUPPORT",
            "ASSOC_MAINTENANCE",
            "ASSOC_INTERCITY",
            "ASSOC_PARCELS",
            "ASSOC_RIDES",
        ]
    ).select_related("user"):
        heads.setdefault(p.department, p.user.get_full_name())
    counts = dict(
        StaffProfile.objects.filter(user__is_active=True)
        .values_list("department")
        .annotate(n=Count("id"))
    )
    announcements = Announcement.objects.filter(audience="STAFF").order_by("-published_at")[:5]
    return {
        "me": {
            "name": user.get_full_name(),
            "first_name": user.first_name,
            "title": getattr(getattr(user, "staff_profile", None), "title", ""),
        },
        "leader_messages": [
            {
                "id": m.pk,
                "title": m.title,
                "body": m.body,
                "author": m.author.get_full_name(),
                "posted_at": m.posted_at.isoformat(),
            }
            for m in LeaderMessage.objects.select_related("author")[:3]
        ],
        "announcements": [
            {
                "id": a.pk,
                "title": (a.text.get("en") or {}).get("title", ""),
                "body": (a.text.get("en") or {}).get("body", ""),
                "created_at": a.published_at.isoformat(),
            }
            for a in announcements
        ],
        "celebrations": _upcoming(today),
        "new_joiners": [
            {"name": p.user.get_full_name(), "title": p.title, "joined_on": p.joined_on.isoformat()}
            for p in StaffProfile.objects.filter(joined_on__gte=today - timedelta(days=45))
            .select_related("user")
            .order_by("-joined_on")[:8]
        ],
        "departments": [
            {"key": k, "name": label, "people": counts.get(k, 0), "head": heads.get(k, "")}
            for k, label in Department.choices
        ],
        "holidays": [
            {"date": d.isoformat(), "name": n, "state": s or "All India"}
            for d, n, s in HOLIDAYS
            if d >= today and (not s or s == state or not state)
        ][:6],
        "jobs": [job_row(j) for j in open_jobs()[:6]],
        "headcount": sum(counts.values()),
    }


def directory(q: str = "", department: str = "") -> list[dict]:
    from apps.accounts.models import StaffProfile

    rows = StaffProfile.objects.filter(user__is_active=True).select_related(
        "user", "city", "reports_to__user"
    )
    if department:
        rows = rows.filter(department=department)
    if q.strip():
        q = q.strip()
        parts = q.split()
        match = (
            Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(title__icontains=q)
            | Q(user__email__icontains=q)
            | Q(employee_id__iexact=q)
        )
        if len(parts) > 1:
            match |= Q(user__first_name__icontains=parts[0], user__last_name__icontains=parts[-1])
        rows = rows.filter(match)
    return [
        {
            "id": p.user_id,
            "name": p.user.get_full_name(),
            "title": p.title,
            "department": p.get_department_display(),
            "city": p.city.name if p.city else p.state or "Head office",
            "email": p.user.email,
            "phone": p.user.phone,
            "employee_id": p.employee_id,
            "manager": p.reports_to.user.get_full_name() if p.reports_to else "",
        }
        for p in rows.order_by("user__first_name")[:60]
    ]


def post_message(user, *, title: str, body: str, now=None) -> LeaderMessage:
    from apps.accounts.models import User
    from apps.notifications.services import notify

    if len(title.strip()) < 3 or len(body.strip()) < 20:
        raise BusinessRuleViolation("Give it a title and a message (20+ characters).")
    m = LeaderMessage.objects.create(
        author=user,
        title=title.strip()[:160],
        body=body.strip()[:6000],
        posted_at=now or timezone.now(),
    )
    for u in User.objects.filter(is_active=True, staff_profile__isnull=False).exclude(pk=user.pk)[
        :600
    ]:
        notify(u, f"From {user.get_full_name()}: {m.title}", m.body[:200], link="/ops/company")
    return m


def applications() -> list[dict]:
    return [
        {
            "id": a.pk,
            "job": a.job.title,
            "name": a.name,
            "email": a.email,
            "phone": a.phone,
            "profile_url": a.profile_url,
            "note": a.note,
            "referred_by": a.referred_by.get_full_name() if a.referred_by else "",
            "status": a.status,
            "status_label": a.get_status_display(),
            "applied_at": a.applied_at.isoformat(),
        }
        for a in JobApplication.objects.select_related("job", "referred_by")[:80]
    ]


def _manager_for(job: JobOpening):
    """Who a new hire reports to: the city's operations manager, else the state's regional
    manager, else the HR manager making the hire."""
    from apps.accounts.models import Role, StaffProfile

    if job.city_id:
        boss = (
            StaffProfile.objects.filter(city_id=job.city_id, user__role=Role.OPS_MANAGER).first()
            or StaffProfile.objects.filter(
                state=job.city.state, user__role=Role.REGIONAL_MANAGER
            ).first()
        )
        if boss:
            return boss
    return None


@transaction.atomic
def onboard(a: JobApplication, *, hr, now=None):
    """Hired: their account, staff profile, salary and first-week tasks are set up, they join
    their team channels, and #general welcomes them. They set a password from the sign-in page
    ("forgot password") with the email they applied with."""
    from apps.accounts.models import Role, StaffProfile, User
    from apps.chat.services import sync_channels
    from apps.workspace.payroll import SALARY_BANDS, SalaryStructure
    from apps.workspace.services import create_tasks

    now = now or timezone.now()
    if User.objects.filter(email__iexact=a.email).exists():
        raise BusinessRuleViolation(
            "Someone already has an account with this email; hire them by moving their role."
        )
    job = a.job
    role = job.role if job.role in Role.values else Role.SUPPORT_AGENT
    first, _, last = a.name.partition(" ")
    user = User.objects.create_user(a.email, None, first_name=first, last_name=last, role=role)
    manager = _manager_for(job) or getattr(hr, "staff_profile", None)
    n = StaffProfile.objects.count() + 1
    while StaffProfile.objects.filter(employee_id=f"RP{n:05d}").exists():
        n += 1
    profile = StaffProfile.objects.create(
        user=user,
        employee_id=f"RP{n:05d}",
        title=job.title,
        department=job.department,
        city=job.city,
        state=job.city.state if job.city else "",
        reports_to=manager,
        joined_on=timezone.localdate(now),
    )
    low, _high = SALARY_BANDS.get(role, (25_000, 35_000))
    SalaryStructure.objects.create(
        user=user, monthly_gross=low, bank_account_last4="0000", effective_from=profile.joined_on
    )
    if manager:
        for i, title in enumerate(
            [
                "Set your password and turn on two-step sign-in",
                "Read the staff handbook",
                f"Meet your manager, {manager.user.first_name}",
                "Shadow a colleague for a full shift",
            ]
        ):
            create_tasks(
                manager=manager.user,
                title=title,
                due_at=now + timedelta(days=2 + i * 2),
                assignee_ids=[user.pk],
                description="Your first week at Ride Pulse.",
                now=now,
            )
    sync_channels()
    from apps.chat.models import Conversation, Message
    from apps.chat.services import _deliver

    general = Conversation.objects.filter(kind="CHANNEL", slug="general").first()
    if general:
        m = Message.objects.create(
            conversation=general,
            body=f"👋 Please welcome {user.get_full_name()}, our new {job.title}"
            + (f" in {job.city.name}" if job.city else "")
            + "!",
            created_at=now,
        )
        Conversation.objects.filter(pk=general.pk).update(last_message_at=now)
        _deliver(general, m)
    job.is_open = False
    job.save(update_fields=["is_open"])
    return profile


def set_status(a: JobApplication, *, user, status: str) -> JobApplication:
    from apps.notifications.services import notify

    if status not in dict(JobApplication.STATUSES):
        raise BusinessRuleViolation("Unknown status.", field="status")
    if status == "HIRED" and a.status != "HIRED":
        onboard(a, hr=user)
    a.status, a.reviewed_by = status, user
    a.save(update_fields=["status", "reviewed_by"])
    if a.referred_by and status in ("INTERVIEW", "HIRED"):
        notify(
            a.referred_by,
            f"Your referral {a.name}: {a.get_status_display().lower()}",
            f"For {a.job.title}. Thank you for referring them!",
        )
    return a


# The role a hire gets, by department (a manager title gets the manager role below).
HIRE_ROLE = {
    "OPERATIONS": "DISPATCH_CONTROLLER",
    "SUPPORT": "SUPPORT_AGENT",
    "MAINTENANCE": "FLEET_EXECUTIVE",
    "FINANCE": "FINANCE_MANAGER",
    "PEOPLE": "HR_MANAGER",
    "SAFETY": "SAFETY_OFFICER",
    "TECH": "SUPPORT_AGENT",
}


def seed_demo(*, log=print) -> dict:
    """Open roles across the company and a first message from the commander."""
    from apps.accounts.models import User
    from apps.geo.models import City

    if JobOpening.objects.exists():
        return {"jobs": 0}
    now = timezone.now()
    city = {c.slug: c for c in City.objects.all()}
    roles = [
        (
            "Senior Backend Engineer (Django)",
            "TECH",
            None,
            "Build dispatch, pricing and payments for millions of rides.",
        ),
        (
            "City Operations Manager",
            "OPERATIONS",
            "kochi",
            "Run Kochi day to day: supply, quality and the local team.",
        ),
        (
            "Dispatch Controller (night shift)",
            "OPERATIONS",
            "chennai",
            "Keep every rider moving overnight: watch the live map and act.",
        ),
        (
            "Customer Support Associate (Tamil, English)",
            "SUPPORT",
            "chennai",
            "Help riders and drivers by chat and phone, kindly and quickly.",
        ),
        (
            "Fleet Executive",
            "MAINTENANCE",
            "bengaluru",
            "Onboard drivers, check documents and keep vehicles road-worthy.",
        ),
        (
            "Finance Analyst",
            "FINANCE",
            "chennai",
            "Payouts, GST and the city P&L, month after month.",
        ),
        (
            "HR Business Partner",
            "PEOPLE",
            "bengaluru",
            "Hire, grow and look after our teams in Karnataka.",
        ),
        (
            "Trust & Safety Officer",
            "SAFETY",
            "hyderabad",
            "Answer every SOS fast and keep riders and drivers safe.",
        ),
        (
            "Product Design Intern",
            "TECH",
            None,
            "Design the rider and driver apps with us for six months.",
        ),
    ]
    for i, (title, dept, slug, summary) in enumerate(roles):
        JobOpening.objects.create(
            title=title,
            department=dept,
            city=city.get(slug) if slug else None,
            kind="Internship" if "Intern" in title else "Full-time",
            role="OPS_MANAGER"
            if "Operations Manager" in title
            else HIRE_ROLE.get(dept, "SUPPORT_AGENT"),
            summary=summary,
            description=f"{summary}\n\nWhat you'll do\n• Own outcomes, not tasks\n• Work closely "
            "with drivers, riders and the city teams\n• Use data every day\n\nWhat we look for\n• "
            "Clear communication in English and a South Indian language\n• Ownership and kindness"
            "\n\nWhy Ride Pulse\n• Health cover for you and your family\n• Learning budget\n• "
            "Free rides to and from work",
            posted_at=now - timedelta(days=i * 2),
        )
    commander = User.objects.filter(role="COMMANDER").first()
    if commander:
        LeaderMessage.objects.create(
            author=commander,
            title="Welcome to the new Ride Pulse",
            body="Team, we start fresh today. Every ride is a promise: a fair fare, a safe trip and a "
            "driver who earns well. Thank you for keeping that promise in 33 cities. My door, and "
            "the chief of staff's, is always open: tell us what's working and what isn't.",
            posted_at=now,
        )
    log(f"  company portal: {len(roles)} open roles")
    return {"jobs": len(roles)}
