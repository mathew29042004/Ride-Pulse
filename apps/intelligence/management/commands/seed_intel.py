"""Add the demo fraud scenarios and the first morning briefing to an existing demo database."""

from django.core.management.base import BaseCommand

from apps.simulation.guard import require_demo_mode


class Command(BaseCommand):
    help = "Plant demo fraud patterns and write yesterday's briefing (skips if cases exist)."

    def handle(self, *args, **options):
        require_demo_mode("seed_intel")
        from apps.intelligence import demo

        self.stdout.write(str(demo.seed(log=self.stdout.write)))
