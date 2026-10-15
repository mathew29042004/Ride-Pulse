"""Demo data for trust and compliance: help articles, saved replies, CSAT on past tickets,
marketing consents, and a few privacy requests, appeals and insurance claims in each state."""

import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.notifications import services as notifications
from apps.realtime import broadcast

from . import appeals, claims, privacy
from .models import (
    Audience,
    ClaimKind,
    ConsentPurpose,
    ConsentRecord,
    HelpArticle,
    Macro,
    RequestKind,
    TicketRating,
)

User = get_user_model()

ARTICLES = [
    (
        "fare-higher-than-estimate",
        "Why was my fare higher than the estimate?",
        "Fares",
        Audience.RIDER,
        "fare estimate price higher surge",
        "Your upfront price is fixed when you book. It can change only if you add a stop, change the drop, or the trip takes a much longer route than planned (for example a road closure). Waiting beyond the free minutes at pickup is charged per minute. Open the trip and tap 'Fare breakdown' to see every line. If something looks wrong, tap 'Get help' on the trip and we'll review it.",
    ),
    (
        "cancellation-fee",
        "When is a cancellation fee charged?",
        "Fares",
        Audience.RIDER,
        "cancel cancellation fee charge",
        "Cancelling is free for 2 minutes after a driver accepts. After that, or once the driver has arrived, a small fee goes to the driver for their time. If the driver was late or going the wrong way, you aren't charged.",
    ),
    (
        "lost-item",
        "I left something in the car",
        "Trips",
        Audience.RIDER,
        "lost item forgot bag phone",
        "Open the trip in Activity and tap 'Report a lost item' (up to 7 days after the ride). We pass the message to your driver without sharing phone numbers, and you can arrange to collect it.",
    ),
    (
        "ride-pin",
        "What is the Ride PIN?",
        "Safety",
        Audience.RIDER,
        "pin otp start code",
        "Your driver needs your 4-digit Ride PIN to start the trip, so you always get into the right car. You can set your own PIN in Account > Safety.",
    ),
    (
        "sos",
        "How does SOS work?",
        "Safety",
        Audience.ALL,
        "sos emergency help police ambulance",
        "Tap SOS on the trip screen. Our safety team gets your live location and calls you right away. For a medical emergency, choose 'Send an ambulance'. In a life-threatening emergency also call 112 (ambulance 108).",
    ),
    (
        "share-trip",
        "Sharing my trip with family",
        "Safety",
        Audience.RIDER,
        "share trip contacts track family",
        "Add up to three trusted contacts in Account. They get your live trip link by SMS. You can switch sharing off any time in Privacy.",
    ),
    (
        "refund-time",
        "How long do refunds take?",
        "Payments",
        Audience.RIDER,
        "refund money back wallet days",
        "Refunds go to your Ride Pulse wallet instantly once approved. Wallet money can pay for your next rides.",
    ),
    (
        "upi-failed",
        "My UPI payment failed but money was debited",
        "Payments",
        Audience.RIDER,
        "upi failed debited double charge",
        "Banks usually reverse a failed UPI debit within 3-5 working days. If the ride shows as paid twice, raise a ticket from the trip and we'll refund the extra charge.",
    ),
    (
        "delete-account",
        "Deleting my account and my data",
        "Privacy",
        Audience.ALL,
        "delete account data privacy download",
        "Go to Privacy. You can download a copy of your data or ask us to delete your account. Deletion happens after 7 days (you can cancel until then). Trip and payment records are kept without your name because tax law requires it.",
    ),
    (
        "accessibility",
        "Wheelchair and assisted rides",
        "Accessibility",
        Audience.RIDER,
        "wheelchair accessible assist blind deaf",
        "Save your needs in Account > Accessibility. Wheelchair users are only sent wheelchair-accessible cars. If you need help boarding, drivers trained in assistance come first and you get 5 extra minutes of free waiting.",
    ),
    (
        "teen-account",
        "Setting up a teen account",
        "Family",
        Audience.RIDER,
        "teen child family parent",
        "In Account > Teen accounts, invite your 13-17 year old by their phone number. You pay, follow every ride live, and set a curfew and a monthly limit.",
    ),
    (
        "insurance",
        "Am I insured during a ride?",
        "Safety",
        Audience.ALL,
        "insurance accident injury claim",
        "Every ride includes accident cover. If something happens, file a claim in the app within 7 days with photos; approved amounts go to your wallet.",
    ),
    (
        "payout-when",
        "When do I get paid?",
        "Earnings",
        Audience.DRIVER,
        "payout bank money weekly monday",
        "Your earnings are paid to your bank every Monday for the previous week, once your balance is over ₹100. Your weekly statement shows every deduction, including TDS.",
    ),
    (
        "tds",
        "What is the TDS on my statement?",
        "Earnings",
        Audience.DRIVER,
        "tds tax pan deduction",
        "Ride Pulse withholds income tax (TDS) on your gross fares under section 194-O: 0.1% if your PAN is on file, 5% if not. It appears in your Form 26AS and you can claim it when you file your return. Upload your PAN in Documents.",
    ),
    (
        "low-rating",
        "Why did my rating drop?",
        "Account",
        Audience.DRIVER,
        "rating stars low drop",
        "Your rating is the average of your last 100 rated trips. Tips: confirm the pickup by chat, keep the car clean, and follow the app's route.",
    ),
    (
        "suspended",
        "My account was suspended",
        "Account",
        Audience.DRIVER,
        "suspended blocked appeal deactivated",
        "You'll see the reason in the app. If you think it's wrong, open Appeals and explain what happened. A different reviewer decides within 3 days.",
    ),
    (
        "ev-charging",
        "Driving an electric vehicle",
        "Vehicle",
        Audience.DRIVER,
        "ev electric battery charge charger",
        "Keep your battery level updated in the app. You only get trips your battery can finish with a reserve. Below 20% we show the nearest chargers.",
    ),
    (
        "airport-queue",
        "How the airport queue works",
        "Trips",
        Audience.DRIVER,
        "airport queue wait line",
        "Drive into the airport zone and you join the line automatically. Airport pickups go to drivers in order. Leaving the zone for more than 5 minutes drops you out.",
    ),
    (
        "documents-expiry",
        "My insurance or permit is expiring",
        "Vehicle",
        Audience.DRIVER,
        "insurance permit fitness expiry renew",
        "We remind you 30 days before. Renew and upload the new document. An expired insurance stops you going online.",
    ),
    (
        "day-pass",
        "What is the zero-commission day pass?",
        "Earnings",
        Audience.DRIVER,
        "day pass commission zero",
        "Pay a small fee once and keep 100% of every fare until midnight. Riders pay the same price.",
    ),
]
MACROS = [
    (
        "Fare reviewed: refund issued",
        "Hi {name}, we've reviewed {trip} and refunded the difference to your wallet. Sorry for the trouble!",
        "FARE_DISPUTE",
    ),
    (
        "Fare reviewed: charged correctly",
        "Hi {name}, we checked {trip}: the route and time match the fare charged. The fare breakdown on the trip shows each line.",
        "FARE_DISPUTE",
    ),
    (
        "Lost item: driver contacted",
        "Hi {name}, we've passed your message about {trip} to the driver and will update this ticket ({ticket}) as soon as they reply.",
        "LOST_ITEM",
    ),
    (
        "Driver behaviour: action taken",
        "Hi {name}, thank you for telling us. We've spoken to the driver from {trip} and taken action. You won't be matched with them again.",
        "DRIVER_BEHAVIOUR",
    ),
    (
        "Double charge: refund",
        "Hi {name}, we can see two debits for {trip}. The extra one has been refunded to your wallet.",
        "PAYMENT",
    ),
    (
        "UPI pending: bank reversal",
        "Hi {name}, the second UPI debit for {trip} is pending at your bank, which usually reverses it within 3-5 working days.",
        "PAYMENT",
    ),
    (
        "Asking for details",
        "Hi {name}, could you tell us a little more (the time and what happened)? It'll help us sort {ticket} quickly.",
        "",
    ),
    (
        "Closing: no reply",
        "Hi {name}, we haven't heard back so we're closing {ticket}. Reply any time to reopen it.",
        "",
    ),
    (
        "Safety: we're on it",
        "Hi {name}, our safety team is looking into {trip} as a priority and will call you shortly.",
        "SAFETY",
    ),
    (
        "App issue: please update",
        "Hi {name}, please update the Ride Pulse app and try again. If it still happens, send us a screenshot here.",
        "APP_ISSUE",
    ),
]
COMMENTS = {
    5: ["Quick and helpful, thanks!", "Refund came straight away", "Great support"],
    4: ["Sorted, took a while though", "Good"],
    3: ["Okay", "Took two replies to understand"],
    2: ["Slow response", "Didn't fully fix it"],
    1: ["No real help", "Still waiting for my money"],
}


def seed(*, seed: int = 21, log=print) -> dict:
    if HelpArticle.objects.exists():
        return {"trust": 0}
    rng = random.Random(seed)
    now = timezone.now()
    log("Trust and compliance: help centre, saved replies, CSAT, consents, requests…")
    stats = {}
    with notifications.muted(), broadcast.muted():
        for slug, title, category, audience, keywords, body in ARTICLES:
            HelpArticle.objects.create(
                slug=slug,
                title=title,
                category=category,
                audience=audience,
                keywords=keywords,
                body=body,
                views=rng.randint(40, 4000),
            )
        stats["articles"] = len(ARTICLES)
        Macro.objects.bulk_create(
            [Macro(title=t, body=b, category=c, uses=rng.randint(0, 300)) for t, b, c in MACROS]
        )
        stats["macros"] = len(MACROS)
        stats["ratings"] = _ratings(rng)
        stats["opted_in"] = _consents(rng, now)
        stats.update(_cases(rng, now))
    log(f"  {stats}")
    return stats


def _ratings(rng: random.Random) -> int:
    from apps.support.models import SupportTicket

    rows = []
    for ticket in SupportTicket.objects.filter(
        status__in=["RESOLVED", "CLOSED"], resolved_at__isnull=False
    ).exclude(rating__isnull=False):
        if not ticket.raised_by.is_end_user or rng.random() > 0.65:
            continue
        score = rng.choices([5, 4, 3, 2, 1], weights=[45, 25, 12, 10, 8])[0]
        rows.append(
            TicketRating(
                ticket=ticket,
                score=score,
                comment=rng.choice(COMMENTS[score]) if rng.random() < 0.5 else "",
                agent=ticket.assigned_to,
                created_at=ticket.resolved_at + timedelta(hours=rng.uniform(0.5, 30)),
            )
        )
    TicketRating.objects.bulk_create(rows)
    return len(rows)


def _consents(rng: random.Random, now) -> int:
    riders = User.objects.filter(role="RIDER", is_active=True).values_list("pk", flat=True)
    rows = [
        ConsentRecord(
            user_id=pk,
            purpose=ConsentPurpose.MARKETING,
            granted=True,
            notice_version=privacy.NOTICE_VERSION,
            created_at=now - timedelta(days=rng.randint(1, 60)),
        )
        for pk in riders
        if rng.random() < 0.35
    ]
    ConsentRecord.objects.bulk_create(rows)
    return len(rows)


def _cases(rng: random.Random, now) -> dict:
    from apps.drivers.models import Availability, DriverProfile, OnboardingStatus
    from apps.drivers.services import suspend_driver
    from apps.riders.models import RiderProfile
    from apps.riders.services import set_blocked
    from apps.rides.models import Trip, TripStatus

    admin = User.objects.filter(role="ADMIN").first()
    riders = list(
        RiderProfile.objects.filter(user__email__endswith="@example.com").select_related("user")[
            :300
        ]
    )
    rng.shuffle(riders)
    made = {"requests": 0, "appeals": 0, "claims": 0}
    # Privacy requests: a finished export, a correction and a grievance to answer, an erasure
    # in its cooling-off week.
    for rider, kind, details in [
        (riders[0], RequestKind.EXPORT, ""),
        (
            riders[1],
            RequestKind.CORRECTION,
            "My name is spelt wrong on my invoices, it should be Karthik.",
        ),
        (
            riders[2],
            RequestKind.GRIEVANCE,
            "I keep getting offer notifications even though I opted out last month.",
        ),
        (riders[3], RequestKind.ERASURE, ""),
    ]:
        try:
            privacy.submit(rider.user, kind, details=details)
            made["requests"] += 1
        except Exception:
            continue
    # Appeals: a blocked rider and a suspended driver ask for a second look.
    blocked = riders[4]
    set_blocked(blocked, True, reason="Repeated no-shows after drivers arrived", actor=admin)
    appeals.submit(
        blocked.user,
        "RIDER_BLOCK",
        statement="I missed two rides because my phone died and the app didn't cancel for me. I always pay my fees.",
    )
    made["appeals"] += 1
    driver = (
        DriverProfile.objects.filter(
            onboarding_status=OnboardingStatus.APPROVED, availability=Availability.OFFLINE
        )
        .exclude(user__email="driver@ridepulse.dev")
        .order_by("?")
        .first()
    )
    if driver:
        suspend_driver(driver, reason="Three riders reported the AC was refused", actor=admin)
        appeals.submit(
            driver.user,
            "DRIVER_SUSPENSION",
            statement="My AC compressor failed that week and I told riders before starting. It's fixed now, receipt attached in chat.",
        )
        made["appeals"] += 1
    # Claims on recent rides.
    recent = list(
        Trip.objects.filter(status=TripStatus.COMPLETED, completed_at__gte=now - timedelta(days=5))
        .select_related("rider__user", "driver__user")
        .order_by("?")[:5]
    )
    stories = [
        (
            ClaimKind.PROPERTY,
            "My phone fell when the auto braked hard and the screen cracked.",
            "6500",
        ),
        (
            ClaimKind.INJURY,
            "A bike hit the car door as I was getting out and my knee was hurt; I went to a clinic.",
            "8200",
        ),
        (
            ClaimKind.ACCIDENT,
            "Another car rear-ended us at the signal. Damage to the boot and the driver's neck hurts.",
            "42000",
        ),
        (
            ClaimKind.PROPERTY,
            "My laptop bag was crushed in the boot by another passenger's suitcase.",
            "3000",
        ),
        (
            ClaimKind.INJURY,
            "I slipped while getting out because the car stopped on a slope. Sprained ankle.",
            "4500",
        ),
    ]
    for trip, (kind, text, amount) in zip(recent, stories, strict=False):
        claimant = trip.driver.user if kind == ClaimKind.ACCIDENT else trip.rider.user
        claim = claims.file_claim(
            trip, user=claimant, kind=kind, description=text, amount=Decimal(amount), now=now
        )
        if rng.random() < 0.5:
            claims.start_review(claim, reviewer=admin)
        made["claims"] += 1
    return made
