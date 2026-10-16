"""Hourly weather history for every city (feeds the ETA and demand models)."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Backfill hourly weather (Open-Meteo archive, or the seasonal simulation offline)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=60)
        parser.add_argument(
            "--offline", action="store_true", help="Simulate; don't call the archive"
        )

    def handle(self, *args, **options):
        from apps.intelligence import context

        self.stdout.write(str(context.backfill(days=options["days"], live=not options["offline"])))
