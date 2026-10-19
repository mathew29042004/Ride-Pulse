"""Demo grievances over three months: mostly resolved on time, a few late or escalated."""

from datetime import timedelta

from django.utils import timezone

from .grievances import ACK_WITHIN, RESOLVE_WITHIN, Grievance, GrievanceStatus, _appellate

DEMO = [
    (
        "FARE",
        "Charged more than the estimate",
        "The fare was ₹180 more than shown when I booked. "
        "The driver took a longer road even though I asked him to follow the map.",
        "The route was 5.8 km longer than the best road. We've refunded ₹176 to your wallet and "
        "coached the driver on following the app's route.",
    ),
    (
        "CONDUCT",
        "Driver was rude about the AC",
        "I asked for the AC and the driver shouted at me and "
        "drove very fast for the rest of the trip. I felt unsafe.",
        "We spoke to the driver and checked the trip's speed data, which confirms harsh driving. He "
        "has a warning and must retake the safety course before his next trip.",
    ),
    (
        "ACCOUNT",
        "My driver account was suspended",
        "My account was suspended after a rider's "
        "complaint but I have the dashcam video showing I did nothing wrong. I have lost 4 days of income.",
        "We reviewed your dashcam video with the trip data and the complaint wasn't supported. Your "
        "account is active again and we've paid ₹2,400 for the days lost.",
    ),
    (
        "EARNINGS",
        "Incentive not paid",
        "I completed 12 trips on Sunday for the 12-trip bonus but "
        "the bonus was not added to my earnings.",
        "Two trips were cancelled by riders after you arrived, so they didn't count. We've changed "
        "the rule: rider cancellations after arrival now count, and paid your ₹300 bonus.",
    ),
    (
        "SAFETY",
        "Dropped at the wrong place at night",
        "The driver ended the trip 800 m before my "
        "home at 11 pm on a dark road, saying he could not go further.",
        "Night Safe should have stopped this. We found the driver ended it while you were confirming; "
        "we've fixed that gap, suspended the driver for a week and refunded the fare.",
    ),
    (
        "SERVICE",
        "Cancellation fee charged unfairly",
        "I cancelled because the driver wasn't moving "
        "towards me for 10 minutes and I was still charged a cancellation fee.",
        "The driver's GPS shows him stationary for 9 minutes. The fee has been refunded and drivers "
        "who don't move after accepting no longer earn a cancellation fee.",
    ),
]


def seed(*, seed: int = 81, log=print) -> dict:
    """Grievances over 3 months: most resolved on time, a few late or escalated, a few open."""
    import random

    from apps.accounts.models import Role, User
    from apps.core.sequences import next_reference

    if Grievance.objects.exists():
        return {"grievances": 0}
    rng = random.Random(seed)
    now = timezone.now()
    riders = list(User.objects.filter(role=Role.RIDER, is_active=True).order_by("?")[:40])
    drivers = list(User.objects.filter(role=Role.DRIVER, is_active=True).order_by("?")[:20])
    officer = User.objects.filter(role=Role.ADMIN).first()
    appellate = _appellate()
    made = 0
    for i in range(36):
        category, subject, description, resolution = DEMO[i % len(DEMO)]
        person = rng.choice(drivers if category in ("ACCOUNT", "EARNINGS") else riders)
        created = now - timedelta(days=rng.uniform(0.2, 88))
        g = Grievance(
            number=next_reference("GRV", year=timezone.localtime(created).year),
            raised_by=person,
            category=category,
            subject=subject,
            description=description,
            created_at=created,
            ack_due=created + ACK_WITHIN,
            resolve_due=created + RESOLVE_WITHIN,
        )
        age = now - created
        if age > timedelta(days=3):
            g.acknowledged_at = created + timedelta(hours=rng.choice([2, 5, 20, 30, 40, 60]))
            g.handled_by = officer
            g.status = GrievanceStatus.ACKNOWLEDGED
            if age > timedelta(days=9):
                g.resolved_at = created + timedelta(days=rng.choice([3, 6, 9, 12, 14, 18]))
                g.resolution = resolution
                g.status = GrievanceStatus.RESOLVED
                g.satisfied = rng.random() < 0.8 or None
                if g.satisfied:
                    g.status = GrievanceStatus.CLOSED
                elif rng.random() < 0.5:
                    g.status, g.escalated_at = (
                        GrievanceStatus.ESCALATED,
                        g.resolved_at + timedelta(days=2),
                    )
                    g.escalation_reason = "The refund doesn't cover what I lost"
                    g.appellate_officer, g.satisfied = appellate, False
        g.save()
        made += 1
    log(f"  grievances: {made}")
    return {"grievances": made}
