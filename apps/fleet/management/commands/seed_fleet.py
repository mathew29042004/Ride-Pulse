"""Add the driver-business demo data to an existing demo database."""

from django.core.management.base import BaseCommand

from apps.simulation.guard import require_demo_mode


class Command(BaseCommand):
    help = "Fleet owners, chargers, EVs, vehicle papers, PAN cards, quests and statements."

    def handle(self, *args, **options):
        require_demo_mode("seed_fleet")
        from apps.fleet import demo

        self.stdout.write(str(demo.seed(log=self.stdout.write)))
