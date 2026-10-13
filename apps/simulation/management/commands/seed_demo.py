import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.simulation.seed import DEMO_PASSWORD, Seeder, demo_already_seeded


class Command(BaseCommand):
    help = "Create demo accounts and a few weeks of realistic trip history."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=21, help="Days of history (default 21)")
        parser.add_argument(
            "--trips-per-day", type=int, default=50, help="Average trips per day (default 50)"
        )
        parser.add_argument(
            "--riders", type=int, default=150, help="Number of riders (default 150)"
        )
        parser.add_argument("--seed", type=int, default=42, help="Random seed for repeatable data")
        parser.add_argument("--reset", action="store_true", help="Wipe ALL data first, then reseed")

    def handle(self, *args, **options):
        if options["reset"]:
            self.stdout.write(self.style.WARNING("Flushing the database…"))
            call_command("flush", interactive=False, verbosity=0)
            reload_reference_data()
        elif demo_already_seeded():
            raise CommandError("Demo data already exists. Use --reset to wipe and reseed.")
        started = time.monotonic()
        # No outer transaction on purpose: every service call commits on its own. Wrapping
        # thousands of trips in one transaction would pile up savepoints (subtransactions),
        # which slows PostgreSQL to a crawl. If seeding fails, rerun with --reset.
        stats = Seeder(
            days=options["days"],
            trips_per_day=options["trips_per_day"],
            riders=options["riders"],
            seed=options["seed"],
            log=self.stdout.write,
        ).run()
        self.stdout.write(self.style.SUCCESS(f"Done in {time.monotonic() - started:.0f}s: {stats}"))
        self.stdout.write(
            f"Demo logins (password {DEMO_PASSWORD}): "
            "admin@ / ops@ / support@ / rider@ / driver@ridepulse.dev"
        )


def reload_reference_data():
    """flush removes rows loaded by data migrations; put the reference data back."""
    from apps.geo.city_data import load_cities, load_landmarks
    from apps.geo.models import City, Landmark, Zone
    from apps.pricing.fare_data import load_fares
    from apps.pricing.models import FareRule, RideType

    load_cities(City, Zone)
    load_landmarks(City, Landmark)
    load_fares(City, RideType, FareRule)
