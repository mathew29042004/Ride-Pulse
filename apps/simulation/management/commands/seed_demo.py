import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.simulation.guard import require_demo_mode
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
        require_demo_mode("seed_demo")
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
        from apps.simulation.network import NetworkBuilder

        stats.update(NetworkBuilder(seed=options["seed"], log=self.stdout.write).run())
        from apps.reliability import command

        stats.update(command.seed_commander(log=self.stdout.write))
        from apps.reliability import briefing

        stats.update(briefing.seed_chief_of_staff(log=self.stdout.write))
        from apps.workspace import demo as workspace_demo

        stats.update(workspace_demo.seed(seed=options["seed"], log=self.stdout.write))
        from apps.reliability import incident_demo

        stats.update(incident_demo.seed(log=self.stdout.write))
        stats.update(incident_demo.seed_weather(log=self.stdout.write))
        from apps.drivers import loans

        stats.update(loans.seed_demo(log=self.stdout.write))
        from apps.rides import counters

        stats.update(counters.seed_demo(log=self.stdout.write))
        from apps.pricing import fuel

        stats.update(fuel.seed_demo(log=self.stdout.write))
        from apps.drivers import speed

        stats.update(speed.seed_demo(log=self.stdout.write))
        stats.update(speed.seed_vehicle_options(log=self.stdout.write))
        from apps.riders import commute

        stats.update(commute.seed_demo(log=self.stdout.write))
        from apps.workspace import attendance

        stats.update(attendance.seed_demo(log=self.stdout.write))
        stats.update(attendance.seed_work_sites(log=self.stdout.write))
        from apps.workspace import expenses as expense_claims

        stats.update(expense_claims.seed_demo(log=self.stdout.write))
        from apps.workspace import payroll

        stats.update(payroll.seed_demo(log=self.stdout.write))
        from apps.workspace import appraisals

        stats.update(appraisals.seed_demo(log=self.stdout.write))
        from apps.announcements import demo as announcements_demo

        stats.update(announcements_demo.seed(log=self.stdout.write))
        from apps.workspace import roster_demo

        stats.update(roster_demo.seed(log=self.stdout.write))
        from apps.compliance import demo as compliance_demo

        stats.update(compliance_demo.seed(log=self.stdout.write))
        from apps.chat import demo as chat_demo

        stats.update(chat_demo.seed(log=self.stdout.write))
        from apps.fleet import demo as fleet_demo

        stats.update(fleet_demo.seed(log=self.stdout.write))
        from apps.simulation import product_demo

        stats.update(product_demo.seed(log=self.stdout.write))
        from apps.trust import demo as trust_demo

        stats.update(trust_demo.seed(log=self.stdout.write))
        from apps.trust import grievance_demo

        stats.update(grievance_demo.seed(log=self.stdout.write))
        from apps.reliability import demo as reliability_demo

        stats.update(reliability_demo.seed(log=self.stdout.write))
        from apps.intelligence import demo as intelligence_demo

        stats.update(intelligence_demo.seed(log=self.stdout.write))
        from apps.tours import demo as tours_demo

        stats.update(tours_demo.seed(log=self.stdout.write))
        from apps.experiments import demo as experiments_demo

        stats.update(experiments_demo.seed(log=self.stdout.write))
        self.stdout.write(self.style.SUCCESS(f"Done in {time.monotonic() - started:.0f}s: {stats}"))
        self.stdout.write(
            f"Demo logins (password {DEMO_PASSWORD}): "
            "admin@ / ops@ / support@ / rider@ / driver@ridepulse.dev"
        )


def reload_reference_data():
    """flush removes rows loaded by data migrations; put the reference data back."""
    from apps.geo.city_data import load_cities, load_landmarks
    from apps.geo.models import City, Landmark, Zone
    from apps.pricing.fare_data import apply_service_hours, apply_services, load_fares
    from apps.pricing.models import FareRule, RideType

    load_cities(City, Zone)
    load_landmarks(City, Landmark)
    load_fares(City, RideType, FareRule)
    apply_service_hours(RideType)
    apply_services(RideType)
    from importlib import import_module

    from django.apps import apps

    import_module("apps.experiments.migrations.0002_default_flags").add_flags(apps, None)
    from apps.tours.catalogue import load as load_tours
    from apps.tours.models import TourPackage, TourStop

    load_tours(City, TourPackage, TourStop)
    from apps.trust.handbook import load as load_handbook
    from apps.trust.models import HelpArticle

    load_handbook(HelpArticle)
