"""Driver Academy courses: short lessons and a quiz each. Passing (80%) is recorded; the
induction course is what lets a new driver go online (and is refreshed yearly); the
accessibility course makes a driver "assist trained" for riders who need help boarding."""

# slug: (title, minutes, required, effect, [lessons], [(question, [options], correct index)])
COURSES = {
    "induction": (
        "Induction: driving with Ride Pulse",
        25,
        True,
        "induction",
        [
            (
                "Before every ride",
                "Do the daily vehicle check in the app (brakes, tyres, lights, "
                "seat belts). Never drive a car with a failed safety item: report it and it goes to "
                "the workshop. Keep your licence, RC, insurance and permit valid; the app warns you "
                "30 days before they expire.",
            ),
            (
                "Starting a trip safely",
                "Always match the car and the rider: ask for the 4-digit "
                "Ride PIN before starting. Never start a trip without it, and never let someone "
                "else drive your vehicle on Ride Pulse.",
            ),
            (
                "Fares and the law",
                "The app sets the fare. Never ask for extra cash. Surge is "
                "capped by your state's rules and cancellation fees are limited by law. You keep "
                "at least 80% of the fare; tips and boosts are 100% yours.",
            ),
            (
                "Rest and safety",
                "After 6 hours of driving the app gives you a 20-minute break, "
                "and you can drive at most 12 hours in a day. Tired driving is the biggest risk on "
                "the road. Use SOS in the app if you or your rider are in danger.",
            ),
        ],
        [
            (
                "When can you start a trip?",
                [
                    "As soon as the rider sits",
                    "After the rider tells you the Ride PIN",
                    "When the app shows the route",
                ],
                1,
            ),
            (
                "Your daily check finds weak brakes. What do you do?",
                [
                    "Drive carefully",
                    "Report it: the car goes off the road until repaired",
                    "Finish today's trips first",
                ],
                1,
            ),
            (
                "A rider offers extra cash for a shorter route. You…",
                ["Take it", "Follow the app's fare and route", "Ask for UPI instead"],
                1,
            ),
            ("How many hours can you drive in a day?", ["12", "16", "No limit"], 0),
            ("What share of the fare do you keep at least?", ["60%", "80%", "100%"], 1),
        ],
    ),
    "womens-safety": (
        "Women's safety and respectful conduct",
        15,
        False,
        "",
        [
            (
                "Respect, always",
                "Greet politely and keep conversation professional. No personal "
                "questions, no comments on appearance, and never ask for a phone number: calls go "
                "through the app's masked numbers.",
            ),
            (
                "Night rides",
                "At night, riders may have Night Safe mode on: trusted contacts "
                "follow the trip and you can't end it away from the drop without the rider "
                "agreeing. Follow the app's route; if you must deviate, tell the rider why.",
            ),
            (
                "If something goes wrong",
                "Stop in a well-lit public place, use SOS, and wait for "
                "the safety team. Riders may share their live location with family (Guardian "
                "mode); that protects you too.",
            ),
        ],
        [
            (
                "A rider asks you to stop somewhere off the route at night. You…",
                [
                    "Refuse rudely",
                    "Confirm it with the rider, then tell them the app's route changes",
                    "Stop without saying anything",
                ],
                1,
            ),
            (
                "How do you call a rider?",
                ["From your own phone", "Through the app's masked call", "Ask for their number"],
                1,
            ),
            (
                "Night Safe mode means…",
                ["Trusted contacts follow the trip", "Fares are higher", "Riders can't cancel"],
                0,
            ),
        ],
    ),
    "first-aid": (
        "First aid on the road",
        15,
        False,
        "",
        [
            (
                "At an accident",
                "Make the scene safe: hazard lights on, park well away. Call 112 "
                "(ambulance 108). Don't move an injured person unless they're in immediate danger.",
            ),
            (
                "Bleeding and breathing",
                "Press firmly on a bleeding wound with a clean cloth. If "
                "someone isn't breathing normally, the 108 operator will guide you through CPR.",
            ),
            (
                "Your first-aid kit",
                "Keep it stocked: bandages, antiseptic, gloves, a torch. It's "
                "part of the daily check.",
            ),
        ],
        [
            ("The emergency number for an ambulance in India is…", ["100", "108", "101"], 1),
            (
                "Someone is bleeding heavily. First you…",
                ["Give water", "Press firmly on the wound", "Move them to your car"],
                1,
            ),
            (
                "Should you move an injured person?",
                ["Only if they're in immediate danger", "Always", "Never call for help first"],
                0,
            ),
        ],
    ),
    "ev-driving": (
        "Electric vehicles: driving and charging",
        10,
        False,
        "",
        [
            (
                "Range",
                "The app only offers trips your battery can finish with a reserve to reach "
                "a charger. Keep the battery level updated in the app.",
            ),
            (
                "Charging",
                "Use the chargers shown in the app. Charge to about 80% for daily "
                "driving; fast charging to 100% wears the battery.",
            ),
            (
                "Smooth driving",
                "Gentle acceleration and regenerative braking add range and earn "
                "eco points for your riders.",
            ),
        ],
        [
            (
                "Why does the app skip some long trips?",
                [
                    "Your battery couldn't finish them with a reserve",
                    "They pay less",
                    "It's random",
                ],
                0,
            ),
            ("For daily driving, charge to about…", ["50%", "80%", "100% every time"], 1),
        ],
    ),
    "accessibility": (
        "Helping riders with disabilities",
        15,
        False,
        "assist",
        [
            (
                "Ask first",
                "Ask how you can help before helping. Some riders need an arm to hold, "
                "some need their wheelchair folded into the boot, some need nothing.",
            ),
            (
                "Wheelchairs and aids",
                "Learn to fold the common wheelchair types. Guide dogs and "
                "mobility aids always ride free and are never a reason to refuse a trip.",
            ),
            (
                "Low vision and hearing",
                "Announce yourself and your car's number. For riders who "
                "are deaf or hard of hearing, use the in-app chat; the app tells you in advance.",
            ),
        ],
        [
            (
                "Before helping a rider in a wheelchair, you…",
                ["Ask how they'd like help", "Lift them straight away", "Wait in the car"],
                0,
            ),
            (
                "A rider with a guide dog books your car. You…",
                ["Refuse", "Take the trip: guide dogs ride free", "Charge extra"],
                1,
            ),
            ("A rider who is deaf: how do you communicate?", ["Shout", "In-app chat", "Don't"], 1),
        ],
    ),
}
