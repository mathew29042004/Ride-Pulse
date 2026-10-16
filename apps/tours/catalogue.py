"""The tour catalogue: famous places reachable from every city Ride Pulse serves.

Each package starts and ends at the rider's pickup in the departure city. Stops are visited in
order; ``minutes`` is the time at each place. Coordinates are approximate (to ~100 m), enough to
price the route and to follow progress on the map.
"""

# (name, category, days, start "HH:MM", tagline, [(stop, lat, lng, minutes, note), ...])
Stop = tuple[str, float, float, int, str]
Package = tuple[str, str, int, str, str, list[Stop]]

HERITAGE, PILGRIMAGE, NATURE, BEACH, HILLS, CITY = (
    "HERITAGE",
    "PILGRIMAGE",
    "NATURE",
    "BEACH",
    "HILLS",
    "CITY",
)

CATALOGUE: dict[str, list[Package]] = {
    "anantapur": [
        (
            "Lepakshi & Penukonda",
            HERITAGE,
            1,
            "07:00",
            "Vijayanagara murals and a hill fort",
            [
                ("Penukonda Fort", 14.083, 77.595, 75, "Summer capital of the Vijayanagara kings"),
                (
                    "Lepakshi Veerabhadra Temple",
                    13.806,
                    77.607,
                    120,
                    "Hanging pillar and ceiling murals",
                ),
                ("Lepakshi Nandi", 13.809, 77.604, 30, "One of India's largest monolithic Nandis"),
            ],
        ),
        (
            "Puttaparthi day trip",
            PILGRIMAGE,
            1,
            "06:30",
            "Prasanthi Nilayam and the Chaitanya Jyoti",
            [
                ("Prasanthi Nilayam", 14.165, 77.811, 150, "Ashram; darshan timings apply"),
                ("Chaitanya Jyoti Museum", 14.161, 77.816, 60, "Museum on the hillside"),
            ],
        ),
    ],
    "belagavi": [
        (
            "Gokak & Godchinamalaki falls",
            NATURE,
            1,
            "07:30",
            "Two waterfalls on the Ghataprabha",
            [
                ("Gokak Falls", 16.197, 74.776, 90, "Best July to October; hanging bridge"),
                ("Godchinamalaki Falls", 16.110, 74.765, 75, "A short walk through the woods"),
            ],
        ),
        (
            "Dandeli jungle day",
            NATURE,
            1,
            "06:00",
            "Kali river and the Western Ghats forest",
            [
                ("Syntheri Rocks", 15.233, 74.666, 60, "Monolith over the Kaneri stream"),
                (
                    "Dandeli Kali river",
                    15.248,
                    74.618,
                    150,
                    "Rafting and coracle rides (paid on site)",
                ),
            ],
        ),
    ],
    "bengaluru": [
        (
            "Mysuru royal day trip",
            HERITAGE,
            1,
            "06:30",
            "Srirangapatna, the Palace, Chamundi Hills",
            [
                (
                    "Srirangapatna (Tipu's fort)",
                    12.414,
                    76.693,
                    60,
                    "Daria Daulat and Ranganathaswamy",
                ),
                ("Mysuru Palace", 12.305, 76.655, 120, "Lit up on Sunday evenings"),
                ("Chamundi Hills", 12.272, 76.672, 60, "Temple and city view"),
                ("Brindavan Gardens", 12.421, 76.573, 75, "Musical fountain after dark"),
            ],
        ),
        (
            "Nandi Hills sunrise",
            HILLS,
            1,
            "04:30",
            "Clouds below you at dawn",
            [
                ("Nandi Hills viewpoint", 13.370, 77.683, 120, "Gates open at 6 am"),
                ("Bhoga Nandeeshwara Temple", 13.381, 77.698, 45, "9th-century Nolamba temple"),
            ],
        ),
        (
            "Bengaluru city highlights",
            CITY,
            1,
            "09:00",
            "Gardens, palaces and the old fort",
            [
                ("Lalbagh Botanical Garden", 12.950, 77.585, 75, "Glasshouse and the rock"),
                ("Tipu Sultan's Summer Palace", 12.959, 77.574, 40, "Teak palace, 1791"),
                ("Bangalore Palace", 12.998, 77.592, 75, "Tudor-style palace with audio guide"),
                ("Cubbon Park & Vidhana Soudha", 12.976, 77.593, 45, "Walk the park"),
                ("ISKCON Temple", 13.010, 77.551, 45, "Hilltop temple"),
            ],
        ),
    ],
    "chennai": [
        (
            "Mahabalipuram heritage",
            HERITAGE,
            1,
            "07:00",
            "UNESCO shore temples on the ECR",
            [
                ("DakshinaChitra", 12.825, 80.243, 75, "Living museum of South Indian homes"),
                ("Arjuna's Penance", 12.617, 80.191, 40, "The great open-air relief"),
                ("Five Rathas", 12.608, 80.190, 45, "Monolithic chariot temples"),
                ("Shore Temple", 12.617, 80.199, 60, "8th-century temple on the sea"),
            ],
        ),
        (
            "Puducherry & Auroville",
            CITY,
            1,
            "06:00",
            "French quarter, promenade and Matrimandir",
            [
                (
                    "Auroville Matrimandir viewpoint",
                    12.007,
                    79.810,
                    90,
                    "Book inner chamber visits ahead",
                ),
                ("Puducherry Promenade", 11.933, 79.836, 60, "Rock beach and the Gandhi statue"),
                ("White Town & Aurobindo Ashram", 11.936, 79.834, 90, "Walk the French quarter"),
            ],
        ),
        (
            "Kanchipuram temples & silk",
            PILGRIMAGE,
            1,
            "07:00",
            "The city of a thousand temples",
            [
                ("Ekambareswarar Temple", 12.847, 79.700, 60, "3,500-year-old mango tree"),
                ("Kailasanathar Temple", 12.843, 79.690, 45, "Pallava sandstone temple"),
                ("Kamakshi Amman Temple", 12.840, 79.703, 45, "One of the Shakti Peethas"),
                ("Silk weavers' street", 12.837, 79.704, 60, "Watch a loom at work"),
            ],
        ),
        (
            "Chennai city heritage",
            CITY,
            1,
            "09:00",
            "Mylapore, Marina and Fort St George",
            [
                ("Kapaleeshwarar Temple", 13.034, 80.270, 45, "Dravidian gopuram in Mylapore"),
                ("San Thome Basilica", 13.034, 80.278, 30, "Built over St Thomas's tomb"),
                ("Marina Beach & Lighthouse", 13.040, 80.280, 60, "Lighthouse viewing gallery"),
                ("Fort St George Museum", 13.080, 80.287, 60, "First British fortress in India"),
                ("Government Museum", 13.070, 80.257, 75, "Chola bronzes gallery"),
            ],
        ),
    ],
    "coimbatore": [
        (
            "Ooty hill day",
            HILLS,
            1,
            "06:00",
            "Up the Nilgiris hairpins to the Queen of Hills",
            [
                ("Doddabetta Peak", 11.401, 76.737, 45, "Highest point of the Nilgiris"),
                ("Government Botanical Garden", 11.418, 76.711, 90, "Fossil tree and flower beds"),
                ("Ooty Lake", 11.405, 76.694, 60, "Boating"),
                ("Tea Factory & Museum", 11.397, 76.725, 45, "Taste fresh Nilgiri tea"),
            ],
        ),
        (
            "Isha Adiyogi & Kovai Kutralam",
            PILGRIMAGE,
            1,
            "08:00",
            "The 112-foot Adiyogi and a forest waterfall",
            [
                (
                    "Kovai Kutralam Falls",
                    10.937,
                    76.689,
                    120,
                    "Forest permit at the gate; closed Tuesdays",
                ),
                ("Isha Yoga Centre & Adiyogi", 10.972, 76.740, 150, "Evening light show"),
            ],
        ),
    ],
    "davanagere": [
        (
            "Chitradurga stone fort",
            HERITAGE,
            1,
            "07:30",
            "Seven rings of walls on granite hills",
            [
                ("Chitradurga Fort (Kallina Kote)", 14.221, 76.399, 150, "Wear walking shoes"),
                ("Chandravalli caves", 14.211, 76.388, 45, "Ancient settlement and caves"),
                ("Jogimatti viewpoint", 14.162, 76.398, 45, "Windmills and forest view"),
            ],
        ),
        (
            "Jog Falls",
            NATURE,
            1,
            "05:30",
            "India's second-highest plunge waterfall",
            [
                ("Jog Falls viewpoint", 14.229, 74.812, 150, "Steps to the base (1,400)"),
                ("Linganamakki Dam view", 14.180, 74.850, 30, "Reservoir that feeds the falls"),
            ],
        ),
    ],
    "erode": [
        (
            "Bhavani Kooduthurai & Kodiveri",
            NATURE,
            1,
            "08:00",
            "A river confluence and a dam on the Bhavani",
            [
                (
                    "Sangameswarar Temple, Bhavani",
                    11.448,
                    77.683,
                    60,
                    "Where the Bhavani meets the Kaveri",
                ),
                ("Kodiveri Dam", 11.478, 77.297, 90, "Picnic spot with a waterfall weir"),
                ("Bhavanisagar Dam & park", 11.473, 77.111, 75, "One of the largest earthen dams"),
            ],
        ),
    ],
    "guntur": [
        (
            "Amaravati & Undavalli",
            HERITAGE,
            1,
            "07:30",
            "Buddhist Amaravati and rock-cut caves",
            [
                ("Amareswara Temple", 16.573, 80.358, 45, "Pancharama shrine on the Krishna"),
                ("Amaravati Archaeological Museum", 16.574, 80.361, 60, "Stupa sculptures"),
                ("Undavalli Caves", 16.496, 80.580, 60, "4-storey rock-cut temple, 7th century"),
            ],
        ),
        (
            "Kondaveedu Fort trek",
            NATURE,
            1,
            "06:00",
            "Reddy kings' hill fort",
            [
                ("Kondaveedu Fort", 16.255, 80.256, 180, "Ghat road and a 2 km walk"),
            ],
        ),
    ],
    "hubballi-dharwad": [
        (
            "Hampi in a day",
            HERITAGE,
            1,
            "05:30",
            "Vijayanagara's capital among the boulders",
            [
                ("Virupaksha Temple", 15.335, 76.460, 60, "Still a living temple"),
                ("Hampi Bazaar & Hemakuta Hill", 15.334, 76.459, 45, "Sunset point"),
                ("Lotus Mahal & Elephant Stables", 15.320, 76.473, 60, "Royal enclosure"),
                ("Vittala Temple (stone chariot)", 15.342, 76.475, 90, "Musical pillars"),
            ],
        ),
        (
            "Badami, Aihole, Pattadakal",
            HERITAGE,
            1,
            "06:00",
            "The cradle of temple architecture",
            [
                ("Badami Cave Temples", 15.918, 75.677, 90, "Four cave temples over Agastya lake"),
                ("Pattadakal Group", 15.949, 75.816, 75, "UNESCO site"),
                ("Aihole (Durga Temple)", 16.019, 75.882, 75, "Apsidal Durga temple"),
            ],
        ),
    ],
    "kakinada": [
        (
            "Annavaram & Draksharamam",
            PILGRIMAGE,
            1,
            "06:30",
            "Hilltop Satyanarayana and a Pancharama shrine",
            [
                ("Annavaram Satyanarayana Temple", 17.281, 82.402, 120, "Ratnagiri hill"),
                (
                    "Draksharamam Bhimeswara Temple",
                    16.792,
                    82.063,
                    75,
                    "One of the Pancharama Kshetras",
                ),
            ],
        ),
        (
            "Coringa mangroves & Uppada",
            NATURE,
            1,
            "07:00",
            "Boardwalk through mangroves and a fishing coast",
            [
                (
                    "Coringa Wildlife Sanctuary",
                    16.750,
                    82.230,
                    120,
                    "Boardwalk; spot otters and birds",
                ),
                ("Uppada Beach", 17.090, 82.330, 60, "Famous for Uppada silk"),
            ],
        ),
    ],
    "kalaburagi": [
        (
            "Bidar heritage",
            HERITAGE,
            1,
            "07:00",
            "Bahmani fort and Bidriware craft",
            [
                ("Bidar Fort", 17.923, 77.528, 120, "Rangin Mahal tile work"),
                ("Mahmud Gawan Madrasa", 17.917, 77.521, 45, "15th-century university"),
                ("Bahmani Tombs, Ashtur", 17.932, 77.555, 45, "Domed royal tombs"),
            ],
        ),
        (
            "Kalaburagi city & Sannati",
            PILGRIMAGE,
            1,
            "08:00",
            "Sufi shrine, fort and an ancient stupa site",
            [
                ("Khwaja Bande Nawaz Dargah", 17.344, 76.846, 45, "Revered Sufi shrine"),
                ("Gulbarga Fort & Jama Masjid", 17.336, 76.833, 60, "Mosque without a courtyard"),
                ("Sharana Basaveshwara Temple", 17.329, 76.836, 30, "Lingayat temple"),
                ("Sannati & Kanaganahalli stupa", 16.856, 76.925, 90, "Ashokan-era Buddhist site"),
            ],
        ),
    ],
    "kannur": [
        (
            "Bekal Fort & beaches",
            BEACH,
            1,
            "07:00",
            "Kerala's largest fort on the sea",
            [
                ("Bekal Fort", 12.393, 75.033, 90, "Keyhole-shaped fort"),
                ("Bekal Beach Park", 12.389, 75.035, 45, ""),
            ],
        ),
        (
            "Kannur forts & Theyyam country",
            CITY,
            1,
            "08:00",
            "Portuguese fort, a drive-in beach and a temple of Theyyam",
            [
                ("St Angelo Fort", 11.855, 75.370, 60, "1505 Portuguese fort"),
                ("Payyambalam Beach", 11.879, 75.364, 45, ""),
                ("Muzhappilangad Drive-in Beach", 11.797, 75.443, 60, "Drive along the sand"),
                ("Parassinikadavu Muthappan Temple", 11.982, 75.401, 60, "Daily Theyyam"),
            ],
        ),
    ],
    "kochi": [
        (
            "Fort Kochi heritage",
            CITY,
            1,
            "09:00",
            "Chinese nets, the Dutch Palace and Jew Town",
            [
                ("Chinese Fishing Nets", 9.968, 76.243, 30, "Best at sunset"),
                ("St Francis Church", 9.966, 76.242, 30, "Vasco da Gama's first burial place"),
                ("Mattancherry (Dutch) Palace", 9.958, 76.259, 60, "Ramayana murals"),
                (
                    "Paradesi Synagogue & Jew Town",
                    9.957,
                    76.259,
                    60,
                    "Closed Fridays and Saturdays",
                ),
            ],
        ),
        (
            "Munnar tea country",
            HILLS,
            2,
            "06:00",
            "Tea estates, Eravikulam and Mattupetty",
            [
                ("Cheeyappara Waterfalls", 10.031, 76.858, 20, "Roadside falls on the way up"),
                ("Tea Museum", 10.096, 77.068, 60, "Kanan Devan tea history"),
                ("Eravikulam National Park", 10.192, 77.066, 150, "Nilgiri tahr; book online"),
                ("Mattupetty Dam", 10.106, 77.124, 60, "Boating"),
                ("Echo Point", 10.116, 77.152, 30, ""),
            ],
        ),
        (
            "Alleppey backwaters",
            NATURE,
            1,
            "07:30",
            "Lake Vembanad, canals and the beach",
            [
                ("Punnamada Lake jetty", 9.511, 76.354, 180, "Shikara ride (paid on site)"),
                ("Alappuzha Beach", 9.493, 76.317, 60, "Old pier and lighthouse"),
            ],
        ),
    ],
    "kollam": [
        (
            "Jatayu & Varkala",
            NATURE,
            1,
            "07:30",
            "The giant Jatayu sculpture and Varkala cliffs",
            [
                ("Jatayu Earth's Center", 8.866, 76.869, 150, "Cable car to the rock"),
                ("Varkala Cliff", 8.735, 76.703, 120, "Cliff-top walk and beach"),
            ],
        ),
        (
            "Ashtamudi & Thangassery",
            BEACH,
            1,
            "08:30",
            "Backwaters, a lighthouse and old forts",
            [
                ("Thangassery Lighthouse", 8.880, 76.567, 45, "Climb for the view"),
                (
                    "Ashtamudi Lake boat jetty",
                    8.950,
                    76.590,
                    120,
                    "Backwater cruise (paid on site)",
                ),
                ("Kollam Beach", 8.874, 76.596, 45, ""),
            ],
        ),
    ],
    "kozhikode": [
        (
            "Wayanad highlights",
            HILLS,
            2,
            "06:00",
            "Caves, lakes and dams in the Wayanad hills",
            [
                ("Lakkidi View Point", 11.519, 76.023, 20, "Top of the Thamarassery ghat"),
                ("Pookode Lake", 11.541, 76.026, 60, "Freshwater lake"),
                ("Banasura Sagar Dam", 11.668, 75.954, 75, "India's largest earth dam"),
                ("Edakkal Caves", 11.625, 76.235, 120, "Neolithic carvings; a steep climb"),
            ],
        ),
        (
            "Kozhikode coast & Thusharagiri",
            BEACH,
            1,
            "08:00",
            "Where Vasco da Gama landed, and a three-tier waterfall",
            [
                ("Kappad Beach", 11.384, 75.719, 45, "Vasco da Gama's landing, 1498"),
                ("Thusharagiri Falls", 11.469, 76.051, 120, "Three-tier waterfall"),
                ("Kozhikode Beach", 11.258, 75.770, 45, "Sunset and street food"),
            ],
        ),
    ],
    "kurnool": [
        (
            "Belum Caves & Yaganti",
            NATURE,
            1,
            "07:00",
            "India's second-longest caves",
            [
                ("Belum Caves", 15.103, 78.111, 120, "3.2 km of caves; 1.5 km open"),
                ("Yaganti Uma Maheswara Temple", 15.351, 78.140, 60, "Growing Nandi"),
            ],
        ),
        (
            "Srisailam Jyotirlinga",
            PILGRIMAGE,
            2,
            "05:30",
            "Mallikarjuna and the Nallamala forest",
            [
                ("Mahanandi Temple", 15.473, 78.613, 45, "Nine Nandi shrines"),
                (
                    "Srisailam Mallikarjuna Temple",
                    16.074,
                    78.868,
                    180,
                    "Jyotirlinga and Shakti Peetha",
                ),
                ("Srisailam Dam viewpoint", 16.088, 78.896, 30, ""),
            ],
        ),
    ],
    "madurai": [
        (
            "Madurai temple city",
            PILGRIMAGE,
            1,
            "07:00",
            "Meenakshi Amman and the Nayak palace",
            [
                ("Meenakshi Amman Temple", 9.919, 78.119, 120, "No phones inside; dress code"),
                ("Thirumalai Nayakkar Mahal", 9.915, 78.124, 60, "Evening sound and light show"),
                ("Gandhi Memorial Museum", 9.929, 78.139, 60, "Blood-stained dhoti of 1948"),
            ],
        ),
        (
            "Rameswaram & Dhanushkodi",
            PILGRIMAGE,
            2,
            "05:00",
            "Pamban bridge, the long corridor and the land's end",
            [
                ("Pamban Bridge viewpoint", 9.282, 79.202, 20, "Sea bridge to the island"),
                ("Ramanathaswamy Temple", 9.288, 79.317, 150, "World's longest temple corridor"),
                ("APJ Abdul Kalam Memorial", 9.279, 79.244, 45, ""),
                ("Dhanushkodi", 9.152, 79.442, 90, "Ghost town at India's tip"),
            ],
        ),
        (
            "Kodaikanal hills",
            HILLS,
            1,
            "05:30",
            "Princess of Hill Stations",
            [
                ("Silver Cascade Falls", 10.250, 77.512, 15, "On the ghat road"),
                ("Kodaikanal Lake", 10.234, 77.489, 75, "Boating and cycling"),
                ("Coaker's Walk", 10.231, 77.494, 45, "Valley views"),
                ("Pillar Rocks", 10.215, 77.474, 30, ""),
            ],
        ),
    ],
    "mangaluru": [
        (
            "Udupi & Malpe",
            PILGRIMAGE,
            1,
            "07:30",
            "Krishna Matha, Malpe beach and St Mary's island",
            [
                (
                    "Udupi Sri Krishna Matha",
                    13.341,
                    74.752,
                    75,
                    "See Krishna through the Kanakana Kindi",
                ),
                ("Malpe Beach", 13.350, 74.704, 60, "Ferries to St Mary's Island (paid)"),
            ],
        ),
        (
            "Murudeshwar & Kollur",
            PILGRIMAGE,
            1,
            "05:30",
            "The giant Shiva by the sea and Mookambika",
            [
                ("Kollur Mookambika Temple", 13.864, 74.814, 90, "In the Kodachadri foothills"),
                (
                    "Murudeshwar Temple & Shiva statue",
                    14.094,
                    74.484,
                    120,
                    "20-storey gopuram with a lift",
                ),
            ],
        ),
        (
            "Mangaluru city & beaches",
            CITY,
            1,
            "09:00",
            "Temples, a church of frescoes and Panambur",
            [
                ("Kudroli Gokarnanath Temple", 12.881, 74.840, 45, ""),
                ("St Aloysius Chapel", 12.874, 74.846, 30, "Painted ceiling"),
                ("Kadri Manjunath Temple", 12.887, 74.856, 45, ""),
                ("Panambur Beach", 12.940, 74.800, 75, "Sunset"),
            ],
        ),
    ],
    "mysuru": [
        (
            "Mysuru city classic",
            CITY,
            1,
            "09:00",
            "Palace, Chamundi Hills and Brindavan",
            [
                ("Mysuru Palace", 12.305, 76.655, 120, "Lit up on Sunday evenings"),
                ("Jaganmohan Palace Art Gallery", 12.306, 76.648, 45, "Raja Ravi Varma paintings"),
                ("Chamundi Hills", 12.272, 76.672, 60, "The big Nandi on the steps"),
                ("Brindavan Gardens", 12.421, 76.573, 75, "Musical fountain after dark"),
            ],
        ),
        (
            "Coorg (Kodagu) escape",
            HILLS,
            2,
            "06:00",
            "Golden Temple, Dubare elephants and Abbey Falls",
            [
                ("Namdroling Golden Temple, Bylakuppe", 12.430, 75.966, 60, "Tibetan monastery"),
                ("Dubare Elephant Camp", 12.367, 75.902, 90, "Mornings only"),
                ("Raja's Seat, Madikeri", 12.418, 75.736, 45, "Sunset point"),
                ("Abbey Falls", 12.457, 75.718, 60, "Through coffee estates"),
            ],
        ),
    ],
    "nellore": [
        (
            "Udayagiri hill fort",
            HERITAGE,
            1,
            "06:30",
            "A 1,000-metre hill fort of the Vijayanagara era",
            [
                ("Udayagiri Fort", 14.876, 79.312, 180, "Steep trek; carry water"),
            ],
        ),
        (
            "Nellore temples & Mypadu beach",
            BEACH,
            1,
            "08:00",
            "Ranganatha temple and a quiet beach",
            [
                ("Talpagiri Ranganatha Temple", 14.453, 79.978, 45, ""),
                ("Penchalakona Lakshmi Narasimha", 14.338, 79.400, 75, ""),
                ("Mypadu Beach", 14.512, 80.164, 75, ""),
            ],
        ),
    ],
    "rajamahendravaram": [
        (
            "Papikondalu river gorge",
            NATURE,
            1,
            "06:00",
            "Boat through the Godavari gorge",
            [
                ("Pattiseema Veerabhadra Temple", 17.236, 81.648, 45, "On a river island"),
                (
                    "Gandi Pochamma boat point",
                    17.448,
                    81.656,
                    240,
                    "Papikondalu cruise (paid on site)",
                ),
            ],
        ),
        (
            "Maredumilli forest",
            NATURE,
            1,
            "07:00",
            "Waterfalls and bamboo chicken in the Eastern Ghats",
            [
                ("Dowleswaram Barrage", 16.946, 81.787, 20, "Sir Arthur Cotton's barrage"),
                ("Jalatarangini Falls", 17.583, 81.700, 75, ""),
                ("Maredumilli Vana Vihari", 17.600, 81.710, 90, "Nature trail"),
            ],
        ),
    ],
    "salem": [
        (
            "Yercaud hills",
            HILLS,
            1,
            "07:00",
            "Jewel of the South in the Shevaroys",
            [
                ("Yercaud Lake", 11.778, 78.209, 60, "Boating"),
                ("Lady's Seat", 11.778, 78.200, 30, "Views over the plains"),
                ("Pagoda Point", 11.790, 78.210, 30, ""),
                ("Shevaroy Temple", 11.802, 78.238, 45, "Highest point"),
            ],
        ),
        (
            "Hogenakkal & Mettur",
            NATURE,
            1,
            "06:30",
            "Coracle rides at the 'smoking rocks' of the Kaveri",
            [
                ("Mettur Dam & park", 11.799, 77.807, 60, ""),
                ("Hogenakkal Falls", 12.119, 77.778, 150, "Coracle ride (paid on site)"),
            ],
        ),
    ],
    "thanjavur": [
        (
            "Great Living Chola Temples",
            HERITAGE,
            1,
            "07:00",
            "Three UNESCO Chola temples in a day",
            [
                ("Brihadeeswarar Temple", 10.783, 79.132, 90, "1,000-year-old Big Temple"),
                (
                    "Thanjavur Palace & Saraswathi Mahal",
                    10.792,
                    79.137,
                    60,
                    "Library of palm-leaf manuscripts",
                ),
                ("Airavatesvara Temple, Darasuram", 10.950, 79.356, 60, "Stone chariot steps"),
                ("Gangaikonda Cholapuram", 11.206, 79.449, 60, "Rajendra Chola's temple"),
            ],
        ),
        (
            "Velankanni & Nagore",
            PILGRIMAGE,
            1,
            "06:30",
            "The basilica and the dargah on the coast",
            [
                ("Velankanni Basilica", 10.683, 79.849, 90, ""),
                ("Nagore Dargah", 10.818, 79.838, 45, ""),
            ],
        ),
    ],
    "thiruvananthapuram": [
        (
            "Kanyakumari land's end",
            PILGRIMAGE,
            1,
            "05:00",
            "Three seas, the Vivekananda Rock and a wooden palace",
            [
                ("Padmanabhapuram Palace", 8.250, 77.326, 75, "Closed Mondays"),
                ("Vivekananda Rock Memorial", 8.078, 77.555, 120, "Ferry from the shore"),
                ("Kanyakumari sunset point", 8.080, 77.538, 45, ""),
            ],
        ),
        (
            "Trivandrum & Kovalam",
            BEACH,
            1,
            "08:30",
            "The golden temple, museums and Kovalam's beaches",
            [
                (
                    "Sree Padmanabhaswamy Temple",
                    8.483,
                    76.944,
                    60,
                    "Strict dress code; Hindus only inside",
                ),
                ("Napier Museum & Zoo", 8.509, 76.955, 75, ""),
                ("Kovalam Lighthouse Beach", 8.400, 76.978, 90, ""),
                ("Poovar estuary", 8.317, 77.069, 60, "Golden sand island"),
            ],
        ),
    ],
    "thoothukudi": [
        (
            "Tiruchendur & Manapad",
            PILGRIMAGE,
            1,
            "06:00",
            "A seashore Murugan temple and a cliff-top church",
            [
                ("Tiruchendur Murugan Temple", 8.496, 78.125, 120, "One of the six abodes"),
                ("Manapad Holy Cross Church", 8.376, 78.063, 45, "On a sand cliff"),
            ],
        ),
        (
            "Panchalankurichi & Kayathar",
            HERITAGE,
            1,
            "08:00",
            "Veerapandiya Kattabomman's fort",
            [
                ("Panchalankurichi Fort", 8.893, 77.935, 60, "Rebuilt memorial fort"),
                ("Kattabomman Memorial, Kayathar", 8.946, 77.768, 30, ""),
            ],
        ),
    ],
    "thrissur": [
        (
            "Athirappilly & Vazhachal",
            NATURE,
            1,
            "07:30",
            "Kerala's biggest waterfall",
            [
                ("Athirappilly Falls", 10.285, 76.570, 120, "Walk to the base"),
                ("Vazhachal Falls", 10.298, 76.637, 45, ""),
            ],
        ),
        (
            "Guruvayur & Thrissur temples",
            PILGRIMAGE,
            1,
            "05:30",
            "Guruvayurappan and the Pooram temple",
            [
                (
                    "Guruvayur Sri Krishna Temple",
                    10.594,
                    76.040,
                    120,
                    "Dress code; Hindus only inside",
                ),
                ("Punnathur Kotta elephant yard", 10.609, 76.035, 45, ""),
                ("Vadakkunnathan Temple", 10.525, 76.214, 60, "Home of Thrissur Pooram"),
            ],
        ),
    ],
    "tiruchirappalli": [
        (
            "Trichy temples & Rock Fort",
            PILGRIMAGE,
            1,
            "07:00",
            "Srirangam, Jambukeswarar and 437 steps",
            [
                (
                    "Srirangam Ranganathaswamy Temple",
                    10.862,
                    78.690,
                    120,
                    "World's largest functioning temple",
                ),
                ("Jambukeswarar Temple", 10.853, 78.705, 45, "Water element temple"),
                ("Rock Fort Ucchi Pillayar", 10.828, 78.697, 75, "437 steps up"),
                ("Kallanai (Grand Anicut)", 10.833, 78.818, 45, "2,000-year-old dam"),
            ],
        ),
    ],
    "tirunelveli": [
        (
            "Courtallam falls",
            NATURE,
            1,
            "07:00",
            "The 'spa of the South'",
            [
                ("Courtallam Main Falls", 8.932, 77.276, 90, "Best June to September"),
                ("Five Falls (Aintharuvi)", 8.913, 77.264, 60, ""),
                ("Papanasam temple & falls", 8.711, 77.372, 60, ""),
            ],
        ),
        (
            "Nellaiappar & Krishnapuram",
            HERITAGE,
            1,
            "08:30",
            "Musical pillars and Nayak sculpture",
            [
                ("Nellaiappar Temple", 8.729, 77.687, 60, "Musical pillars"),
                ("Krishnapuram Venkatachalapathy Temple", 8.722, 77.780, 45, "Nayak-era sculpture"),
            ],
        ),
    ],
    "tirupati": [
        (
            "Tirumala darshan & Kalahasti",
            PILGRIMAGE,
            1,
            "04:00",
            "Balaji and the Vayu linga temple",
            [
                ("Tirumala Venkateswara Temple", 13.683, 79.347, 240, "Book darshan tickets ahead"),
                ("Sri Kalahasteeswara Temple", 13.749, 79.698, 90, "Rahu-Ketu pooja"),
            ],
        ),
        (
            "Talakona & Chandragiri",
            NATURE,
            1,
            "07:00",
            "Andhra's highest waterfall and a royal fort",
            [
                ("Chandragiri Fort & Raja Mahal", 13.585, 79.311, 75, "Museum in the palace"),
                ("Talakona Waterfalls", 13.808, 79.217, 120, "Forest trek to the falls"),
            ],
        ),
    ],
    "tiruppur": [
        (
            "Thirumoorthy hills",
            NATURE,
            1,
            "07:30",
            "A temple, a dam and a waterfall at the Anamalai foot",
            [
                ("Avinashilingeswarar Temple", 11.193, 77.268, 45, ""),
                ("Thirumoorthy Temple & Dam", 10.459, 77.169, 90, ""),
                ("Panchalingam Falls", 10.456, 77.162, 60, "Short walk up"),
            ],
        ),
    ],
    "vellore": [
        (
            "Vellore fort & Golden Temple",
            HERITAGE,
            1,
            "09:00",
            "A moated fort and the gold-covered Sripuram",
            [
                ("Vellore Fort & Jalakandeswarar", 12.921, 79.129, 90, "Moat and museum"),
                ("Sripuram Golden Temple", 12.875, 79.090, 120, "Evening is best"),
            ],
        ),
        (
            "Yelagiri hills",
            HILLS,
            1,
            "07:00",
            "Fourteen hairpins to a quiet hill station",
            [
                ("Punganur Lake", 12.583, 78.640, 60, "Boating"),
                ("Swamimalai Hill trek", 12.590, 78.630, 90, ""),
                ("Jalagamparai Falls", 12.555, 78.646, 60, ""),
            ],
        ),
        (
            "Tiruvannamalai Arunachala",
            PILGRIMAGE,
            1,
            "06:00",
            "The fire temple and Ramana's ashram",
            [
                ("Arunachaleswarar Temple", 12.231, 79.068, 120, ""),
                ("Sri Ramanasramam", 12.222, 79.061, 60, ""),
            ],
        ),
    ],
    "vijayawada": [
        (
            "Vijayawada river & hills",
            CITY,
            1,
            "08:00",
            "Kanaka Durga, Undavalli caves and Bhavani Island",
            [
                ("Kanaka Durga Temple", 16.518, 80.605, 75, "On Indrakeeladri hill"),
                ("Prakasam Barrage", 16.507, 80.605, 20, ""),
                ("Undavalli Caves", 16.496, 80.580, 60, ""),
                ("Bhavani Island", 16.522, 80.590, 90, "Boat from the ghat"),
            ],
        ),
        (
            "Kondapalli fort & toys",
            HERITAGE,
            1,
            "08:00",
            "A hill fort and the wooden toy village",
            [
                ("Kondapalli Fort", 16.618, 80.540, 90, ""),
                ("Kondapalli toy makers' colony", 16.620, 80.548, 45, "Hand-carved toys"),
            ],
        ),
    ],
    "visakhapatnam": [
        (
            "Araku Valley & Borra Caves",
            HILLS,
            1,
            "05:30",
            "Coffee country, tribal museum and limestone caves",
            [
                ("Borra Caves", 18.280, 83.039, 75, "Million-year-old limestone caves"),
                ("Ananthagiri coffee plantations", 18.250, 82.980, 30, ""),
                ("Araku Tribal Museum", 18.327, 82.876, 60, ""),
                ("Padmapuram Gardens", 18.335, 82.871, 45, ""),
            ],
        ),
        (
            "Vizag city & coast",
            BEACH,
            1,
            "09:00",
            "RK Beach, a submarine museum and Kailasagiri",
            [
                ("Simhachalam Temple", 17.766, 83.250, 60, ""),
                ("INS Kursura Submarine Museum", 17.713, 83.326, 45, ""),
                ("RK Beach", 17.714, 83.323, 30, ""),
                ("Kailasagiri", 17.749, 83.342, 60, "Ropeway"),
                ("Rushikonda Beach", 17.782, 83.385, 60, ""),
            ],
        ),
    ],
}


def load(City, TourPackage, TourStop) -> int:
    """Create any missing packages (idempotent: an existing slug is left as ops edited it)."""
    from datetime import time

    from django.utils.text import slugify

    cities = {c.slug: c for c in City.objects.filter(slug__in=CATALOGUE)}
    created = 0
    for city_slug, packages in CATALOGUE.items():
        city = cities.get(city_slug)
        if city is None:
            continue
        for name, category, days, start, tagline, stops in packages:
            slug = slugify(f"{city_slug} {name}")[:80]
            package, made = TourPackage.objects.get_or_create(
                slug=slug,
                defaults={
                    "city": city,
                    "name": name,
                    "tagline": tagline,
                    "category": category,
                    "days": days,
                    "start_time": time(*map(int, start.split(":"))),
                },
            )
            if not made:
                continue
            created += 1
            TourStop.objects.bulk_create(
                TourStop(
                    package=package, order=i, name=s[0], lat=s[1], lng=s[2], minutes=s[3], note=s[4]
                )
                for i, s in enumerate(stops, start=1)
            )
    return created
