"""Shared PostgreSQL-only setup for the synthetic F1 acceptance suite."""

from __future__ import annotations

import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path

from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings

from medicafe_v1.access.models import Membership, Organization, User
from medicafe_v1.records.models import Encounter, Patient, PatientAlias
from medicafe_v1.sources.artifacts import LocalArtifactStore
from medicafe_v1.sources.commands import admit_delivery, parse_delivery
from medicafe_v1.sources.models import Delivery, Observation

from tests.fixtures.synthetic_inputs import CSV_MEDIA_TYPE, csv_bytes


class PostgresOnlyMixin:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if connection.vendor != "postgresql":
            raise unittest.SkipTest("F1 acceptance tests require PostgreSQL; SQLite is not supported")


class SyntheticF1Mixin:
    """Per-test organization, users and temporary private artifact root."""

    def setUp(self):
        super().setUp()
        self._artifact_tmp = tempfile.TemporaryDirectory(prefix="medicafe-f1-artifacts-")
        self._artifact_settings = override_settings(ARTIFACT_ROOT=Path(self._artifact_tmp.name))
        self._artifact_settings.enable()
        self.store = LocalArtifactStore(self._artifact_tmp.name)
        self.alpha = Organization.objects.create(name=f"Synthetic Clinic Alpha {uuid.uuid4().hex[:8]}")
        self.beta = Organization.objects.create(name=f"Synthetic Clinic Beta {uuid.uuid4().hex[:8]}")
        self.alpha_user = User.objects.create_user(
            username=f"synthetic-alpha-{uuid.uuid4().hex[:8]}", password="synthetic-test-password"
        )
        self.beta_user = User.objects.create_user(
            username=f"synthetic-beta-{uuid.uuid4().hex[:8]}", password="synthetic-test-password"
        )
        Membership.objects.create(organization=self.alpha, user=self.alpha_user)
        Membership.objects.create(organization=self.beta, user=self.beta_user)

    def tearDown(self):
        self._artifact_settings.disable()
        self._artifact_tmp.cleanup()
        super().tearDown()

    def admit(self, *, actor=None, organization=None, content=None, source_key=None,
              source_namespace="synthetic-demo", media_type=CSV_MEDIA_TYPE, supersedes_id=None):
        actor = actor or self.alpha_user
        organization = organization or self.alpha
        return admit_delivery(
            actor=actor,
            organization_id=organization.id,
            source_namespace=source_namespace,
            source_key=source_key or str(uuid.uuid4()),
            content=content if content is not None else csv_bytes(),
            media_type=media_type,
            supersedes_id=supersedes_id,
            artifact_store=self.store,
        )

    def parse(self, delivery_id, *, actor=None, organization=None, parser_version=None):
        actor = actor or self.alpha_user
        organization = organization or self.alpha
        kwargs = {
            "actor": actor,
            "organization_id": organization.id,
            "delivery_id": delivery_id,
            "artifact_store": self.store,
        }
        if parser_version is not None:
            kwargs["parser_version"] = parser_version
        return parse_delivery(**kwargs)

    def delivery(self, delivery_id):
        return Delivery.objects.get(id=delivery_id)

    def first_observation(self, delivery_id):
        return Observation.objects.get(parse_result__delivery_id=delivery_id, row_ordinal=1)

    def create_patient_encounter(self, *, organization=None, display_name="Synthetic Existing Patient",
                                 service_date="2026-01-15"):
        organization = organization or self.alpha
        patient = Patient.objects.create(organization=organization, display_name=display_name)
        encounter = Encounter.objects.create(
            organization=organization, patient=patient,
            service_date=date.fromisoformat(service_date) if isinstance(service_date, str) else service_date,
        )
        return patient, encounter


class F1TestCase(PostgresOnlyMixin, SyntheticF1Mixin, TestCase):
    pass


class F1TransactionTestCase(PostgresOnlyMixin, SyntheticF1Mixin, TransactionTestCase):
    reset_sequences = True
