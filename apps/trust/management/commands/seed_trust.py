"""Add trust and compliance demo data to an existing demo database."""

from django.core.management.base import BaseCommand

from apps.simulation.guard import require_demo_mode


class Command(BaseCommand):
    help = "Help articles, saved replies, CSAT, consents, privacy requests, appeals and claims."

    def handle(self, *args, **options):
        require_demo_mode("seed_trust")
        from apps.trust import demo

        self.stdout.write(str(demo.seed(log=self.stdout.write)))
