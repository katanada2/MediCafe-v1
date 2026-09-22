"""F2 feature assertions layered on the shared workflow boundary helper."""

from __future__ import annotations

from tests.helpers.workflow_boundary_contract import assert_parse_boundary


def assert_claim_boundary(testcase, *, delivery, claim_revision, expected_service_revisions,
                          expected_total, expected_observations=1, expected_attempts=1):
    """Assert the parsed source and selected claim lines remain same-target and ordered."""

    parse_result = assert_parse_boundary(
        testcase,
        delivery=delivery,
        parser_version="f1-v1",
        expected_observations=expected_observations,
        expected_attempts=expected_attempts,
        expected_successes=1,
    )
    lines = list(claim_revision.lines.order_by("ordinal"))
    testcase.assertEqual(
        [line.service_revision_id for line in lines],
        list(expected_service_revisions),
    )
    testcase.assertEqual([line.ordinal for line in lines], list(range(1, len(lines) + 1)))
    testcase.assertEqual(claim_revision.organization_id, delivery.organization_id)
    testcase.assertEqual(claim_revision.total_amount, expected_total)
    testcase.assertTrue(claim_revision.envelope_bytes)
    testcase.assertEqual(len(claim_revision.envelope_digest), 64)
    return parse_result

