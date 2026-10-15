"""Add the product-feature demo data (weather, events, accessibility, teens, companies)."""

from django.core.management.base import BaseCommand

from apps.simulation.guard import require_demo_mode


class Command(BaseCommand):
    help = "Weather, events, accessibility, teen accounts and companies for the demo."

    def handle(self, *args, **options):
        require_demo_mode("seed_product")
        from apps.simulation import product_demo

        self.stdout.write(str(product_demo.seed(log=self.stdout.write)))
