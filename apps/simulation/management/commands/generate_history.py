import time

from django.core.management.base import BaseCommand, CommandError

from apps.simulation.history import HistoryGenerator, LiveSimulatorRunning


class Command(BaseCommand):
    help = (
        "Back-fill realistic trip and parcel history in every city (for analytics and the data "
        "platform). Stop the live simulator first."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=60, help="Days of history (default 60)")
        parser.add_argument("--trips-per-day", type=int, default=300)
        parser.add_argument("--seed", type=int, default=11)
        parser.add_argument(
            "--force-offline",
            action="store_true",
            help="Take online drivers offline first (instead of refusing)",
        )

    def handle(self, *args, **options):
        started = time.monotonic()
        generator = HistoryGenerator(
            days=options["days"],
            trips_per_day=options["trips_per_day"],
            seed=options["seed"],
            log=self.stdout.write,
        )
        try:
            stats = generator.run(force_offline=options["force_offline"])
        except LiveSimulatorRunning as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Done in {time.monotonic() - started:.0f}s: {stats}"))
