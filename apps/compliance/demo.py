"""Demo compliance: almost every approved driver police-verified and trained, a few still pending
or due a refresher (so the dashboard has something to fix), never the demo driver."""

import random
from datetime import timedelta

from django.utils import timezone

from apps.drivers.models import DriverProfile, OnboardingStatus


def seed(*, seed: int = 51, log=print) -> dict:
    rng = random.Random(seed)
    today = timezone.localdate()
    pending = refresher = 0
    approved = DriverProfile.objects.filter(onboarding_status=OnboardingStatus.APPROVED)
    for driver in approved.filter(police_verified_on__isnull=True).select_related("user"):
        demo = driver.user.email.endswith("@ridepulse.dev")
        roll = rng.random()
        if not demo and roll < 0.03:
            pending += 1  # police verification still in progress
            continue
        DriverProfile.objects.filter(pk=driver.pk).update(
            police_verified_on=today - timedelta(days=rng.randint(30, 700)),
            police_verification_ref=f"PV{rng.randint(10**7, 10**8 - 1)}",
            induction_trained_on=today
            - timedelta(
                days=rng.randint(380, 420) if not demo and roll < 0.07 else rng.randint(5, 340)
            ),
        )
        refresher += not demo and roll < 0.07
    if pending or refresher:
        log(
            f"Compliance: {pending} drivers awaiting police verification, "
            f"{refresher} due a refresher"
        )
    return {
        "verification_pending": pending,
        "refresher_due": refresher,
        "course_results": academy_seed(),
    }


def academy_seed(*, seed: int = 52) -> int:
    """Course results that match the drivers' training records, plus some optional courses."""
    from datetime import datetime, time

    from apps.drivers.academy import CourseResult

    if CourseResult.objects.exists():
        return 0
    rng = random.Random(seed)
    rows = []
    for pk, trained, assist in DriverProfile.objects.filter(
        induction_trained_on__isnull=False
    ).values_list("pk", "induction_trained_on", "assist_trained"):
        at = timezone.make_aware(datetime.combine(trained, time(11)))
        rows.append(
            CourseResult(
                driver_id=pk,
                course="induction",
                score=rng.choice([80, 100, 100]),
                passed=True,
                taken_at=at,
            )
        )
        for course, share in (("womens-safety", 0.45), ("first-aid", 0.3), ("ev-driving", 0.12)):
            if rng.random() < share:
                rows.append(
                    CourseResult(driver_id=pk, course=course, score=100, passed=True, taken_at=at)
                )
        if assist:
            rows.append(
                CourseResult(
                    driver_id=pk, course="accessibility", score=100, passed=True, taken_at=at
                )
            )
    CourseResult.objects.bulk_create(rows, batch_size=2000)
    return len(rows)
