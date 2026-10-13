"""Default ride types and fare cards (rupees). City fare multipliers scale the metered parts."""

from decimal import ROUND_HALF_UP, Decimal

# code, name, description, seats, sort order
RIDE_TYPES = [
    ("BIKE", "Bike", "Beat the traffic on a bike taxi", 1, 1),
    ("AUTO", "Auto", "Affordable auto-rickshaw rides", 3, 2),
    ("MINI", "Mini", "Comfy hatchbacks at everyday prices", 4, 3),
    ("SEDAN", "Prime Sedan", "Spacious sedans with top-rated drivers", 4, 4),
    ("SUV", "Prime SUV", "Six-seaters for groups and luggage", 6, 5),
]

# code: base, per km, per min, minimum, booking fee, cancel fee, free wait, wait/min, airport
FARE_CARDS = {
    "BIKE": ("20", "6", "0.50", "30", "5", "15", 3, "1", "0"),
    "AUTO": ("30", "13", "1", "40", "8", "25", 3, "1.50", "0"),
    "MINI": ("50", "12", "1.50", "80", "12", "50", 3, "2", "100"),
    "SEDAN": ("60", "15", "2", "100", "15", "60", 3, "2.50", "120"),
    "SUV": ("80", "20", "2.50", "150", "20", "75", 3, "3", "150"),
}


def _scaled(value: str, multiplier: Decimal) -> Decimal:
    return (Decimal(value) * multiplier).quantize(Decimal("0.5"), rounding=ROUND_HALF_UP)


def load_fares(City, RideType, FareRule) -> None:
    for code, name, description, seats, order in RIDE_TYPES:
        RideType.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "description": description,
                "seats": seats,
                "sort_order": order,
            },
        )
    for city in City.objects.all():
        multiplier = Decimal(city.fare_multiplier)
        for code, card in FARE_CARDS.items():
            base, per_km, per_min, minimum, booking, cancel, free_wait, wait, airport = card
            FareRule.objects.update_or_create(
                city=city,
                ride_type=RideType.objects.get(code=code),
                defaults={
                    "base_fare": _scaled(base, multiplier),
                    "per_km": _scaled(per_km, multiplier),
                    "per_minute": _scaled(per_min, multiplier),
                    "minimum_fare": _scaled(minimum, multiplier),
                    "booking_fee": Decimal(booking),
                    "cancellation_fee": Decimal(cancel),
                    "free_wait_minutes": free_wait,
                    "wait_per_minute": Decimal(wait),
                    "airport_fee": Decimal(airport),
                },
            )
