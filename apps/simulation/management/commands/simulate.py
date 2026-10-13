from django.core.management.base import BaseCommand, CommandError

from apps.geo.models import City
from apps.simulation.simulator import Simulator


class Command(BaseCommand):
    help = "Run bot drivers and riders in real time (and the dispatch/surge jobs) until stopped."

    def add_arguments(self, parser):
        parser.add_argument(
            "--cities", default="chennai,bengaluru,coimbatore", help="Comma-separated city slugs"
        )
        parser.add_argument("--drivers", type=int, default=30, help="Bot drivers online per city")
        parser.add_argument(
            "--request-every",
            type=float,
            default=25,
            help="Avg seconds between bot requests per city",
        )
        parser.add_argument(
            "--speed", type=float, default=4, help="How much faster than real traffic bots drive"
        )
        parser.add_argument(
            "--tick", type=float, default=2, help="Seconds between simulation steps"
        )
        parser.add_argument(
            "--duration", type=float, default=None, help="Stop after this many seconds"
        )
        parser.add_argument("--quiet", action="store_true", help="Only print errors")

    def handle(self, *args, **options):
        slugs = [s.strip() for s in options["cities"].split(",") if s.strip()]
        if not City.objects.filter(slug__in=slugs).exists():
            raise CommandError(f"No such cities: {slugs}")
        log = (lambda *_: None) if options["quiet"] else self.stdout.write
        self.stdout.write(
            self.style.SUCCESS(f"Simulating {', '.join(slugs)}. Press Ctrl+C to stop.")
        )
        simulator = Simulator(
            city_slugs=slugs,
            drivers_per_city=options["drivers"],
            request_interval=options["request_every"],
            speedup=options["speed"],
            tick_seconds=options["tick"],
            log=log,
        )
        try:
            simulator.run(duration=options["duration"])
        except KeyboardInterrupt:
            self.stdout.write("\nStopping; sending bot drivers offline…")
        self.stdout.write(self.style.SUCCESS(f"Simulation stats: {simulator.stats}"))
