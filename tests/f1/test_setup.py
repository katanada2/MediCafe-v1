from __future__ import annotations

from io import StringIO

from django.core.management import call_command

from medicafe_v1.access.models import Membership, Organization, User

from tests.f1.base import F1TestCase


class SeedSetupTests(F1TestCase):
    def test_seed_demo_creates_two_isolated_synthetic_operators(self):
        output = StringIO()
        call_command(
            "seed_demo",
            alpha_password="synthetic-alpha-password",
            beta_password="synthetic-beta-password",
            stdout=output,
        )

        alpha = Organization.objects.get(name="Synthetic Clinic Alpha")
        beta = Organization.objects.get(name="Synthetic Clinic Beta")
        alpha_user = User.objects.get(username="synthetic-alpha")
        beta_user = User.objects.get(username="synthetic-beta")
        self.assertTrue(alpha_user.check_password("synthetic-alpha-password"))
        self.assertTrue(beta_user.check_password("synthetic-beta-password"))
        self.assertEqual(Membership.objects.filter(organization=alpha, user=alpha_user, is_active=True).count(), 1)
        self.assertEqual(Membership.objects.filter(organization=beta, user=beta_user, is_active=True).count(), 1)
        self.assertEqual(Membership.objects.filter(user=alpha_user).count(), 1)
        self.assertEqual(Membership.objects.filter(user=beta_user).count(), 1)
        self.assertNotIn("synthetic-alpha-password", output.getvalue())
        self.assertNotIn("synthetic-beta-password", output.getvalue())
