import secrets

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from medicafe_v1.access.models import Membership, Organization, User


class Command(BaseCommand):
    help = "Create two isolated synthetic organizations and operators."

    def add_arguments(self, parser):
        parser.add_argument("--alpha-password")
        parser.add_argument("--beta-password")

    @transaction.atomic
    def handle(self, *args, **options):
        credentials = []
        for label, supplied in (("alpha", options["alpha_password"]), ("beta", options["beta_password"])):
            organization, _ = Organization.objects.get_or_create(name=f"Synthetic Clinic {label.title()}")
            user, created = User.objects.get_or_create(username=f"synthetic-{label}")
            if created:
                password = supplied or secrets.token_urlsafe(18)
                user.set_password(password)
                user.save(update_fields=["password"])
                credentials.append((user.username, password, supplied is None))
            elif supplied:
                raise CommandError(f"Refusing to replace the existing {label} operator password")
            Membership.objects.get_or_create(organization=organization, user=user, defaults={"is_active": True})
        for username, password, generated in credentials:
            if generated:
                self.stdout.write(f"Generated one-time local credential for {username}: {password}")
            else:
                self.stdout.write(f"Created {username} with the supplied password")
        self.stdout.write(self.style.SUCCESS("Synthetic organizations and isolated memberships are ready."))

