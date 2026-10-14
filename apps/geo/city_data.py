"""Launch cities and their zones (approximate neighbourhood centres)."""

# name, slug, state, lat, lng, radius km, fare multiplier
CITIES = [
    ("Chennai", "chennai", "Tamil Nadu", 13.0500, 80.2300, 30.0, "1.00"),
    ("Bengaluru", "bengaluru", "Karnataka", 12.9716, 77.6200, 35.0, "1.10"),
    ("Coimbatore", "coimbatore", "Tamil Nadu", 11.0168, 76.9800, 18.0, "0.85"),
]

# city slug -> [(code, name, lat, lng, radius km, is airport, demand weight)]
ZONES = {
    "chennai": [
        ("t-nagar", "T. Nagar", 13.0418, 80.2341, 2.0, False, 1.6),
        ("anna-nagar", "Anna Nagar", 13.0850, 80.2101, 2.5, False, 1.2),
        ("egmore", "Egmore & Central", 13.0732, 80.2609, 2.0, False, 1.4),
        ("mylapore", "Mylapore", 13.0368, 80.2676, 2.0, False, 1.0),
        ("adyar", "Adyar", 13.0012, 80.2565, 2.5, False, 1.1),
        ("guindy", "Guindy", 13.0067, 80.2206, 2.0, False, 1.0),
        ("velachery", "Velachery", 12.9815, 80.2180, 2.5, False, 1.1),
        ("omr-sholinganallur", "OMR Sholinganallur", 12.9010, 80.2279, 3.0, False, 1.5),
        ("porur", "Porur", 13.0382, 80.1565, 2.5, False, 0.8),
        ("tambaram", "Tambaram", 12.9249, 80.1000, 3.0, False, 0.7),
        ("chennai-airport", "Chennai Airport", 12.9941, 80.1709, 2.0, True, 1.3),
    ],
    "bengaluru": [
        ("mg-road", "MG Road", 12.9756, 77.6050, 2.0, False, 1.4),
        ("indiranagar", "Indiranagar", 12.9784, 77.6408, 2.0, False, 1.3),
        ("koramangala", "Koramangala", 12.9352, 77.6245, 2.5, False, 1.6),
        ("hsr-layout", "HSR Layout", 12.9116, 77.6474, 2.5, False, 1.1),
        ("jayanagar", "Jayanagar", 12.9250, 77.5938, 2.5, False, 0.9),
        ("electronic-city", "Electronic City", 12.8452, 77.6602, 3.0, False, 1.3),
        ("marathahalli", "Marathahalli", 12.9569, 77.7011, 2.5, False, 1.1),
        ("whitefield", "Whitefield", 12.9698, 77.7500, 3.0, False, 1.4),
        ("hebbal", "Hebbal", 13.0358, 77.5970, 2.5, False, 0.9),
        ("kempegowda-airport", "Kempegowda Airport", 13.1986, 77.7066, 3.0, True, 1.2),
    ],
    "coimbatore": [
        ("gandhipuram", "Gandhipuram", 11.0183, 76.9725, 2.0, False, 1.5),
        ("rs-puram", "RS Puram", 11.0089, 76.9497, 2.0, False, 1.1),
        ("saibaba-colony", "Saibaba Colony", 11.0247, 76.9440, 2.0, False, 0.9),
        ("ukkadam", "Ukkadam", 10.9906, 76.9612, 2.0, False, 0.8),
        ("peelamedu", "Peelamedu", 11.0260, 77.0060, 2.5, False, 1.2),
        ("singanallur", "Singanallur", 10.9990, 77.0320, 2.5, False, 0.8),
        ("saravanampatti", "Saravanampatti", 11.0789, 77.0007, 3.0, False, 1.1),
        ("coimbatore-airport", "Coimbatore Airport", 11.0300, 77.0434, 2.0, True, 0.6),
    ],
}

# city slug -> [(name, category, address, lat, lng)]
LANDMARKS = {
    "chennai": [
        ("Chennai Central Railway Station", "TRANSIT", "Park Town", 13.0827, 80.2757),
        ("Chennai Egmore Station", "TRANSIT", "Egmore", 13.0784, 80.2610),
        ("Koyambedu Bus Terminus", "TRANSIT", "Koyambedu", 13.0694, 80.1948),
        ("Chennai Airport (Domestic Terminal)", "AIRPORT", "Meenambakkam", 12.9900, 80.1693),
        ("Marina Beach", "LANDMARK", "Kamarajar Salai", 13.0500, 80.2824),
        ("Elliot's Beach", "LANDMARK", "Besant Nagar", 12.9988, 80.2718),
        ("Pondy Bazaar", "MALL", "T. Nagar", 13.0410, 80.2337),
        ("Express Avenue Mall", "MALL", "Royapettah", 13.0587, 80.2641),
        ("Phoenix Marketcity", "MALL", "Velachery", 12.9915, 80.2170),
        ("VR Chennai", "MALL", "Anna Nagar", 13.0802, 80.1990),
        ("Tidel Park", "TECH_PARK", "Taramani", 12.9893, 80.2484),
        ("IIT Madras", "EDUCATION", "Guindy", 12.9916, 80.2336),
        ("Apollo Hospitals", "HOSPITAL", "Greams Road", 13.0607, 80.2518),
    ],
    "bengaluru": [
        ("Kempegowda International Airport", "AIRPORT", "Devanahalli", 13.1989, 77.7068),
        ("KSR Bengaluru City Railway Station", "TRANSIT", "Majestic", 12.9781, 77.5697),
        ("MG Road Metro Station", "TRANSIT", "MG Road", 12.9755, 77.6066),
        ("Cubbon Park", "LANDMARK", "Kasturba Road", 12.9763, 77.5929),
        ("Lalbagh Botanical Garden", "LANDMARK", "Mavalli", 12.9507, 77.5848),
        ("UB City", "MALL", "Vittal Mallya Road", 12.9716, 77.5960),
        ("Nexus Koramangala", "MALL", "Koramangala", 12.9345, 77.6113),
        ("Phoenix Marketcity", "MALL", "Whitefield Road", 12.9967, 77.6963),
        ("Orion Mall", "MALL", "Rajajinagar", 13.0110, 77.5550),
        ("Manyata Tech Park", "TECH_PARK", "Nagawara", 13.0475, 77.6214),
        ("ITPL", "TECH_PARK", "Whitefield", 12.9857, 77.7360),
        ("Infosys Campus", "TECH_PARK", "Electronic City", 12.8507, 77.6620),
        ("100 Feet Road", "LANDMARK", "Indiranagar", 12.9719, 77.6412),
    ],
    "coimbatore": [
        ("Coimbatore Junction", "TRANSIT", "Railway Station Road", 10.9960, 76.9670),
        ("Gandhipuram Central Bus Stand", "TRANSIT", "Gandhipuram", 11.0175, 76.9682),
        ("Coimbatore International Airport", "AIRPORT", "Peelamedu", 11.0300, 77.0434),
        ("Brookefields Mall", "MALL", "Krishnaswamy Road", 11.0090, 76.9600),
        ("Prozone Mall", "MALL", "Saravanampatti", 11.0550, 76.9940),
        ("Race Course", "LANDMARK", "Race Course Road", 11.0005, 76.9780),
        ("PSG College of Technology", "EDUCATION", "Peelamedu", 11.0246, 77.0028),
        ("TIDEL Park Coimbatore", "TECH_PARK", "Civil Aerodrome Post", 11.0262, 77.0256),
        ("KG Hospital", "HOSPITAL", "Arts College Road", 10.9993, 76.9654),
    ],
}


# The South India expansion (Tamil Nadu, Kerala, Karnataka, Andhra Pradesh).
from .city_data_south import CITIES as _SOUTH_CITIES  # noqa: E402
from .city_data_south import LANDMARKS as _SOUTH_LANDMARKS  # noqa: E402
from .city_data_south import ZONES as _SOUTH_ZONES  # noqa: E402

CITIES = CITIES + _SOUTH_CITIES
ZONES = {**ZONES, **_SOUTH_ZONES}
LANDMARKS = {**LANDMARKS, **_SOUTH_LANDMARKS}


def load_landmarks(City, Landmark) -> None:
    for slug, places in LANDMARKS.items():
        city = City.objects.get(slug=slug)
        for name, category, address, lat, lng in places:
            Landmark.objects.update_or_create(
                city=city,
                name=name,
                defaults={"category": category, "address": address, "lat": lat, "lng": lng},
            )


def load_cities(City, Zone) -> None:
    """Idempotent loader that takes model classes, so data migrations can call it."""
    for name, slug, state, lat, lng, radius, multiplier in CITIES:
        city, _ = City.objects.update_or_create(
            slug=slug,
            defaults={
                "name": name,
                "state": state,
                "center_lat": lat,
                "center_lng": lng,
                "radius_km": radius,
                "fare_multiplier": multiplier,
            },
        )
        for code, zone_name, zlat, zlng, zradius, airport, weight in ZONES[slug]:
            Zone.objects.update_or_create(
                city=city,
                code=code,
                defaults={
                    "name": zone_name,
                    "center_lat": zlat,
                    "center_lng": zlng,
                    "radius_km": zradius,
                    "is_airport": airport,
                    "demand_weight": weight,
                },
            )
