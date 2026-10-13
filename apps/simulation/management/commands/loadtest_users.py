"""Create riders for load testing (each Locust user signs in as its own rider, so per-user
rate limits behave as they would in production)."""

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.riders.services import register_rider


class Command(BaseCommand):
    help = "Create load-test riders loadtest+N@ridepulse.dev (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=50)
        parser.add_argument("--password", default="loadtest-pass-2026")

    def handle(self, *args, count, password, **options):
        created = 0
        for n in range(count):
            email = f"loadtest+{n}@ridepulse.dev"
            if User.objects.filter(email=email).exists():
                continue
            register_rider(email=email, password=password, first_name="Load", last_name=f"Test {n}")
            created += 1
        self.stdout.write(f"{created} riders created ({count} available).")
