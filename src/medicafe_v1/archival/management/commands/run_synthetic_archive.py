import os

from django.core.management.base import BaseCommand, CommandError

from medicafe_v1.synthetic_archive import run_archive_server


class Command(BaseCommand):
    help = "Run the separate loopback-only synthetic archive target"

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8875)
        parser.add_argument(
            "--schema", default=os.environ.get("MEDICAFE_ARCHIVE_SCHEMA", "synthetic_archive")
        )

    def handle(self, *args, **options):
        if not 1 <= options["port"] <= 65535:
            raise CommandError("archive port must be in 1..65535")
        try:
            run_archive_server(
                host=options["host"], port=options["port"], schema=options["schema"]
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
