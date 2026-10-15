"""Check the API against its committed contract, or refresh the snapshot (--update)."""

from django.core.management.base import BaseCommand, CommandError

from apps.reliability import contract


class Command(BaseCommand):
    help = "Fail on breaking API changes against docs/api/openapi.json (or --update it)."

    def add_arguments(self, parser):
        parser.add_argument("--update", action="store_true", help="Write a new snapshot")

    def handle(self, *args, **options):
        if options["update"] or not contract.SNAPSHOT.exists():
            path = contract.save()
            self.stdout.write(self.style.SUCCESS(f"Wrote {path}"))
            return
        problems = contract.breaking_changes(contract.load(), contract.generate())
        if problems:
            raise CommandError("Breaking API changes:\n  " + "\n  ".join(problems))
        self.stdout.write(self.style.SUCCESS("No breaking API changes."))
