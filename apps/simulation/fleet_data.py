"""Reference data for generating a believable fleet."""

# ride type -> [(make, model, seats)]
VEHICLES = {
    "BIKE": [
        ("Honda", "Shine 125", 1),
        ("Hero", "Splendor Plus", 1),
        ("Bajaj", "Pulsar 150", 1),
        ("TVS", "Apache RTR 160", 1),
    ],
    "AUTO": [("Bajaj", "RE Compact", 3), ("Piaggio", "Ape City", 3), ("TVS", "King Deluxe", 3)],
    "MINI": [
        ("Maruti Suzuki", "Swift", 4),
        ("Hyundai", "i20", 4),
        ("Tata", "Tiago", 4),
        ("Maruti Suzuki", "WagonR", 4),
    ],
    "SEDAN": [
        ("Maruti Suzuki", "Dzire", 4),
        ("Honda", "Amaze", 4),
        ("Hyundai", "Aura", 4),
        ("Toyota", "Etios", 4),
    ],
    "SUV": [
        ("Maruti Suzuki", "Ertiga", 6),
        ("Toyota", "Innova Crysta", 6),
        ("Kia", "Carens", 6),
        ("Mahindra", "XUV700", 6),
    ],
}

COLORS = ["White", "Silver", "Grey", "Black", "Blue", "Red", "Pearl White", "Maroon"]

# city slug -> RTO prefixes used for registration numbers
RTO_CODES = {
    "chennai": ["TN01", "TN02", "TN07", "TN09", "TN10", "TN22"],
    "bengaluru": ["KA01", "KA03", "KA05", "KA51", "KA53"],
    "coimbatore": ["TN37", "TN38", "TN66"],
}

RIDE_TYPE_WEIGHTS = {"BIKE": 0.18, "AUTO": 0.24, "MINI": 0.32, "SEDAN": 0.16, "SUV": 0.10}
CITY_WEIGHTS = {"chennai": 0.45, "bengaluru": 0.40, "coimbatore": 0.15}
PAYMENT_WEIGHTS = {"UPI": 0.45, "CASH": 0.30, "CARD": 0.10, "WALLET": 0.15}

# Relative ride requests by local hour: morning and evening commute peaks.
HOURLY_DEMAND = [
    0.15,
    0.08,
    0.05,
    0.05,
    0.08,
    0.2,
    0.45,
    0.85,
    1.35,
    1.45,
    1.0,
    0.8,
    0.85,
    0.9,
    0.8,
    0.85,
    1.0,
    1.35,
    1.55,
    1.5,
    1.2,
    0.95,
    0.65,
    0.35,
]

RIDER_TAGS = ["Great driving", "Clean car", "Polite", "On time", "Safe", "Good music"]
LOW_TAGS = ["Rash driving", "Late pickup", "Took a longer route", "Rude"]
