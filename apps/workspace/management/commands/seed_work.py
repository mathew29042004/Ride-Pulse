"""Add the demo workspace (tasks and stand-ups) to an existing demo database."""

from django.core.management.base import BaseCommand

from apps.simulation.guard import require_demo_mode


class Command(BaseCommand):
    help = "Give the demo staff a week of tasks and daily stand-ups (skips if tasks exist)."

    def handle(self, *args, **options):
        require_demo_mode("seed_work")
        from apps.workspace import demo

        self.stdout.write(str(demo.seed(log=self.stdout.write)))
