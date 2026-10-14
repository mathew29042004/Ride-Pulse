import time

from django.core.management.base import BaseCommand

from apps.simulation.guard import require_demo_mode
from apps.simulation.network import NetworkBuilder


class Command(BaseCommand):
    help = (
        "Add drivers and riders in every city and create the staff organisation (regional "
        "managers, associate managers, city teams). Safe to run again: it only tops up."
    )

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=7)

    def handle(self, *args, **options):
        require_demo_mode("grow_network")
        started = time.monotonic()
        stats = NetworkBuilder(seed=options["seed"], log=self.stdout.write).run()
        self.stdout.write(self.style.SUCCESS(f"Done in {time.monotonic() - started:.0f}s: {stats}"))
