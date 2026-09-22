"""Feature-level assertions for the F1 parse producer/consumer boundary.

The helper intentionally checks persisted relationships rather than treating a
boolean or a non-empty artifact path as completion evidence.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from medicafe_v1.sources.models import Observation, ParseAttempt, ParseResult


def assert_delivery_boundary(testcase: SimpleTestCase, *, intent, expected_state: str,
                             expected_possible_attempts: int,
                             expected_valid_observations: int):
    """Assert F3 target, authorization, attempts, outcomes, and evidence agree."""
    from medicafe_v1.claims.queries import delivery_effect_state

    intent.refresh_from_db()
    testcase.assertEqual(intent.delivery_key, intent.id)
    testcase.assertEqual(intent.claim_revision_id, intent.claim_approval.claim_revision_id)
    testcase.assertEqual(intent.envelope_digest, intent.claim_revision.envelope_digest)
    testcase.assertEqual(intent.byte_length, len(bytes(intent.claim_revision.envelope_bytes)))
    testcase.assertEqual(intent.initial_authorization_receipt.result_delivery_intent_id, intent.id)
    testcase.assertEqual(intent.initial_authorization_receipt.accepted_by_id, intent.authorized_by_id)
    attempts = list(intent.attempts.order_by("ordinal"))
    testcase.assertEqual(sum(item.possible_dispatch for item in attempts), expected_possible_attempts)
    testcase.assertTrue(all(item.intent_id == intent.id for item in attempts))
    testcase.assertTrue(all(item.payload_digest == intent.envelope_digest for item in attempts))
    valid = list(intent.observations.filter(binding_valid=True))
    testcase.assertEqual(len(valid), expected_valid_observations)
    testcase.assertTrue(all(item.intent_id == intent.id for item in valid))
    testcase.assertTrue(all(item.lookup_key == intent.delivery_key for item in valid))
    testcase.assertEqual(delivery_effect_state(intent), expected_state)
    return intent


def assert_parse_boundary(testcase: SimpleTestCase, *, delivery, parser_version: str,
                          expected_observations: int, expected_attempts: int,
                          expected_successes: int | None = None) -> ParseResult:
    """Assert target identity, terminal attempts, canonical result and rows agree."""

    results = list(ParseResult.objects.filter(
        organization_id=delivery.organization_id,
        delivery_id=delivery.id,
        parser_version=parser_version,
    ))
    testcase.assertLessEqual(len(results), 1)
    if expected_successes is not None:
        testcase.assertEqual(len(results), 1 if expected_successes else 0)
    attempts = list(ParseAttempt.objects.filter(
        organization_id=delivery.organization_id,
        delivery_id=delivery.id,
        parser_version=parser_version,
    ))
    testcase.assertEqual(len(attempts), expected_attempts)
    testcase.assertTrue(all(attempt.ended_at >= attempt.started_at for attempt in attempts))
    if expected_successes is not None:
        testcase.assertEqual(sum(attempt.succeeded for attempt in attempts), expected_successes)
    if not results:
        testcase.assertEqual(Observation.objects.filter(
            organization_id=delivery.organization_id,
            parse_result__delivery_id=delivery.id,
            parse_result__parser_version=parser_version,
        ).count(), 0)
        return None
    result = results[0]
    testcase.assertEqual(result.delivery_id, delivery.id)
    observations = Observation.objects.filter(
        organization_id=delivery.organization_id, parse_result=result,
    )
    testcase.assertEqual(observations.count(), expected_observations)
    testcase.assertTrue(all(observation.parse_result_id == result.id for observation in observations))
    testcase.assertTrue(all(observation.organization_id == delivery.organization_id for observation in observations))
    return result
