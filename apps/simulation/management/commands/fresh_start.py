"""Wipe everything that has *happened* on the platform and start fresh, keeping its set-up.

Kept: people and their accounts (users, staff and the org chart, drivers, riders, fleet owners,
trusted contacts, payment profiles), cities, zones and landmarks, vehicles and driver documents,
ride types, fare rules, fuel prices and promo codes, tour packages, quests, counters, charging
stations, slow zones, help articles and macros, team channels and their members, salary set-up,
feature flags, experiments and webhook endpoints.

Erased: trips and everything about them, payments, the ledger (wallets back to ₹0), payouts,
loans, team chat messages, direct and group chats, tasks, meetings, check-ins, shifts, leave,
attendance, payslips, expense claims, appraisals, notifications, announcements, the audit trail,
support tickets, grievances, NPS, alerts, orders, incidents, the chief's inbox, fraud cases,
surge history, location history and the event outbox. Ratings and trip counts reset; every
driver is offline; everyone signs in again.

    python manage.py fresh_start --yes
"""

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

KEEP = {
    "accounts.User",
    "accounts.StaffProfile",
    "accounts.TwoFactor",
    "geo.City",
    "geo.Zone",
    "geo.Landmark",
    "drivers.DriverProfile",
    "drivers.Vehicle",
    "drivers.DriverDocument",
    "drivers.SlowZone",
    "riders.RiderProfile",
    "riders.PaymentProfile",
    "riders.ProfileMember",
    "riders.SavedPlace",
    "riders.TeenLink",
    "riders.TrustedContact",
    "riders.CommutePlan",
    "riders.CommuteEnrolment",
    "pricing.RideType",
    "pricing.FareRule",
    "pricing.FareFuelBasis",
    "pricing.FuelPrice",
    "pricing.PromoCode",
    "fleet.FleetOwner",
    "fleet.FleetMembership",
    "fleet.ChargingStation",
    "fleet.Quest",
    "tours.TourPackage",
    "tours.TourStop",
    "rides.Counter",
    "trust.HelpArticle",
    "trust.Macro",
    "trust.ConsentRecord",
    "experiments.Experiment",
    "experiments.FeatureFlag",
    "reliability.WebhookEndpoint",
    "payments.Wallet",
    "workspace.SalaryStructure",
    "chat.Conversation",  # channels only; other conversations are erased below
    "chat.Member",
}


class Command(BaseCommand):
    help = "Erase all activity (chats, trips, money, HR records, audit...) and keep the set-up."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Don't ask for confirmation")

    def handle(self, *args, **options):
        from apps.simulation.guard import require_demo_mode

        require_demo_mode("fresh_start")
        if not options["yes"]:
            raise CommandError("This erases all activity. Run again with --yes to go ahead.")
        erase = [
            m
            for m in apps.get_models()
            if not m._meta.proxy
            and m._meta.managed
            and m._meta.label not in KEEP
            and (m.__module__.startswith("apps.") or m._meta.app_label == "token_blacklist")
        ]
        tables = sorted({m._meta.db_table for m in erase})
        kept_tables = {apps.get_model(label)._meta.db_table for label in KEEP}
        with transaction.atomic():
            from apps.chat.models import Conversation

            dropped = Conversation.objects.exclude(kind="CHANNEL").delete()[0]
            Conversation.objects.update(last_message_at=None)
            with connection.cursor() as cur:
                # A kept table that points at an erased one (team channels can link to a task,
                # meeting or ticket) would be emptied by TRUNCATE ... CASCADE, so those links are
                # dropped for the moment and put back afterwards (all in this transaction).
                cur.execute(
                    """
                    SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid)
                    FROM pg_constraint c
                    WHERE c.contype = 'f'
                      AND c.conrelid::regclass::text = ANY(%s)
                      AND c.confrelid::regclass::text = ANY(%s)
                    """,
                    [sorted(kept_tables), tables],
                )
                links = cur.fetchall()
                cur.execute("SET CONSTRAINTS ALL IMMEDIATE")  # settle the deletes above
                for table, name, _ in links:
                    cur.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"')
                cur.execute(
                    "TRUNCATE "
                    + ", ".join(connection.ops.quote_name(t) for t in tables)
                    + " RESTART IDENTITY CASCADE"
                )
                for table, name, definition in links:
                    cur.execute(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {definition}')
            from apps.drivers.models import DriverProfile
            from apps.riders.models import RiderProfile

            DriverProfile.objects.update(
                availability="OFFLINE",
                rating="5.00",
                rating_count=0,
                acceptance_rate=100,
                completed_trips=0,
                cancelled_trips=0,
                safety_score=None,
                going_home_until=None,
                going_home_uses=0,
                break_until=None,
                break_warned_at=None,
            )
            RiderProfile.objects.update(
                rating="5.00", rating_count=0, completed_trips=0, eco_points=0, co2_saved_g=0
            )
        from django.core.cache import cache

        cache.clear()
        self.stdout.write(
            self.style.SUCCESS(
                f"Fresh start: erased {len(tables)} kinds of activity and {dropped} chats; "
                "people, cities, vehicles, prices and settings kept."
            )
        )
