from django.core.management.base import BaseCommand

from medicafe_v1.archival.worker import run_archive_worker_once


class Command(BaseCommand):
    help = "Run one bounded synthetic archive work decision"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", required=True)
        parser.add_argument("--worker-id")
        parser.add_argument("--lease-seconds", type=int, default=10)

    def handle(self, *args, **options):
        if not 1 <= options["lease_seconds"] <= 300:
            self.stderr.write("archive_lease_seconds_invalid")
            return
        result = run_archive_worker_once(
            worker_id=options["worker_id"], lease_seconds=options["lease_seconds"]
        )
        self.stdout.write(result.reason_code)
