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
    return {"verification_pending": pending, "refresher_due": refresher}
