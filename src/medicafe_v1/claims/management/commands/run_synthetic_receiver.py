import os

from django.core.management.base import BaseCommand, CommandError

from medicafe_v1.synthetic_receiver import serve_receiver


class Command(BaseCommand):
    help = "Run the separate loopback-only synthetic F3 receiver."

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8765)
        parser.add_argument(
            "--schema",
            default=os.environ.get("MEDICAFE_RECEIVER_SCHEMA", "synthetic_receiver"),
        )

    def handle(self, *args, **options):
        if not 1 <= options["port"] <= 65535:
            raise CommandError("port must be between 1 and 65535")
        try:
            serve_receiver(
                host=options["host"], port=options["port"], schema=options["schema"]
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
