"""The internal staff handbook: step-by-step procedures (SOPs) matching how Ride Pulse works.
Loaded by a data migration; ops can edit them in the admin."""

# slug: (title, category, keywords, body)
SOPS = {
    "sop-sos": (
        "Handling an SOS",
        "Safety",
        "sos emergency danger police ambulance safety desk",
        "1. Acknowledge the alert on the Safety desk within 1 minute (the timer is on the card).\n"
        "2. Call the rider first, then the driver, using the masked numbers on the incident.\n"
        "3. If anyone is hurt or in danger, call 112 (ambulance 108) and give the trip's live location.\n"
        "4. Check whether the rider's Guardian mode is sharing their location with family; if so, the family "
        "can see the same live page.\n"
        "5. Stay on the incident until the rider confirms they're safe, then resolve it with a short note.\n"
        "6. If the driver behaved badly, suspend them pending review and open a fraud/conduct case.",
    ),
    "sop-ride-check": (
        "Unanswered Ride Checks",
        "Safety",
        "ride check long stop off route signal lost",
        "A Ride Check that nobody answers becomes an SOS automatically. Treat it like one: call the rider, "
        "then the driver. Most are a phone in a pocket; still, never close one without speaking to the rider "
        "or seeing the trip complete safely.",
    ),
    "sop-fare-refund": (
        "Fare disputes and refunds",
        "Refunds",
        "refund fare dispute overcharge route longer",
        "1. Open the trip: compare the actual route with the estimate (the map shows both).\n"
        "2. If the route was much longer without the rider asking, refund the difference to the wallet.\n"
        "3. Toll and parking lines are passed through to the driver; refund them only if they weren't paid.\n"
        "4. Refunds above ₹500 need a team lead (two-person rule).\n"
        "5. Use the saved reply 'Refund issued' so the rider sees the amount and the reason.",
    ),
    "sop-lost-item": (
        "Lost and found",
        "Lost & found",
        "lost item phone wallet bag keys hub",
        "Valuables (phones, wallets, keys, documents) are urgent. If the driver hasn't answered in 12 hours "
        "they get a reminder; call them if it's a valuable. Once found, offer the rider delivery by bike "
        "parcel. Items not collected in 7 days go to the city hub; mark them collected when the rider "
        "shows ID. After 30 days at the hub they're donated (the rider is told).",
    ),
    "sop-fraud": (
        "Reviewing a fraud case",
        "Fraud",
        "fraud gps spoofing collusion route padding",
        "1. Read the evidence on the case (GPS jumps, repeated rider-driver pairs, padded routes).\n"
        "2. Look at the trips side by side; one odd trip is usually a GPS glitch, a pattern is not.\n"
        "3. Confirmed: suspend the driver, reverse the affected fares to the riders, and note what you saw.\n"
        "4. The driver can appeal; appeals are decided by a different person (two-person rule).",
    ),
    "sop-driver-onboarding": (
        "Onboarding a new driver",
        "Drivers",
        "onboarding documents police verification induction training",
        "1. Review the four documents in Verification (licence, RC, insurance, permit).\n"
        "2. Record the police verification certificate number in Compliance (required by the Aggregator "
        "Guidelines before the first ride).\n"
        "3. The driver completes the Induction course in the Driver Academy (80% to pass).\n"
        "4. Only then can they go online. Check the vehicle is under 8 years old.",
    ),
    "sop-vehicle-off-road": (
        "A car is off the road",
        "Drivers",
        "breakdown off road workshop vehicle health repair",
        "A failed safety item or a breakdown takes the car off the road. Call the driver to check they're "
        "safe; if a rider was on board, the trip was ended at no charge and a ticket opened: call the rider "
        "too. Help book a workshop. When the repair is logged (with parts and cost), the car comes back on "
        "the road automatically.",
    ),
    "sop-surge-complaint": (
        "Complaints about surge",
        "Refunds",
        "surge price high expensive cap",
        "Surge is capped by state law (2x in most states); the app enforces it, so a fare can't exceed it. "
        "Explain the cap and the busy-period reason. If a rider was charged above the cap (shouldn't "
        "happen), refund the difference and report it to the pricing team.",
    ),
    "sop-tour-no-driver": (
        "A tour with no driver",
        "Tours",
        "tour driver unassigned fallback",
        "Tours are assigned the day before. If Tours shows 'Unassigned' within 24 hours, press Find driver. "
        "If none is free, call the traveller to offer a different car type or a date change. 15 minutes "
        "before departure an unassigned tour goes to normal dispatch automatically.",
    ),
    "sop-leave": (
        "Leave and shift cover",
        "People",
        "leave shift roster cover sick",
        "Request leave in Roster & leave; your manager approves it. Approval takes you off your shifts and "
        "finds cover automatically; if a shift can't be covered it shows red, and the manager arranges "
        "someone. For sudden sick leave, also message your team channel.",
    ),
}


def load(HelpArticle) -> int:
    created = 0
    for slug, (title, category, keywords, body) in SOPS.items():
        _, made = HelpArticle.objects.get_or_create(
            slug=slug,
            defaults={
                "title": title,
                "category": category,
                "keywords": keywords,
                "body": body,
                "audience": "STAFF",
            },
        )
        created += made
    return created
