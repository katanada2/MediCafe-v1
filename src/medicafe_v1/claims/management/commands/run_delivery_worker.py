from django.core.management.base import BaseCommand, CommandError as DjangoCommandError

from medicafe_v1.claims.delivery_worker import run_delivery_worker_once


class Command(BaseCommand):
    help = "Run the bounded synthetic delivery worker."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", required=True)
        parser.add_argument("--worker-id")
        parser.add_argument("--lease-seconds", type=int, default=10)

    def handle(self, *args, **options):
        if not 1 <= options["lease_seconds"] <= 300:
            raise DjangoCommandError("lease_seconds must be between 1 and 300")
        result = run_delivery_worker_once(
            worker_id=options["worker_id"], lease_seconds=options["lease_seconds"]
        )
        self.stdout.write(result.reason_code)
