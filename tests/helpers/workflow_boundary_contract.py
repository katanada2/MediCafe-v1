"""Feature-level assertions for the F1 parse producer/consumer boundary.

The helper intentionally checks persisted relationships rather than treating a
boolean or a non-empty artifact path as completion evidence.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from medicafe_v1.sources.models import Observation, ParseAttempt, ParseResult


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
