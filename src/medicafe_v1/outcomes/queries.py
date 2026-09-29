from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Q, Sum

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.sources.domain import CommandError

from .models import (
    AcceptedEvent, FinancialAccount, InboundCandidate, InboundConflict,
    PostingEntry,
)


BLOCKER_ORDER = (
    "artifact_unavailable", "malformed_or_unsupported",
    "conflicting_identity_or_content", "unmatched_target",
    "pending_delivery_evidence", "pending_sequence_gap", "overallocated_line",
    "unaccepted",
)


@dataclass(frozen=True)
class LedgerLineView:
    line_ordinal: int
    claim_line_id: object
    original_charge: Decimal
    payer_reported_credits: Decimal
    contractual_adjustments: Decimal
    residual: Decimal


@dataclass(frozen=True)
class LedgerView:
    account_id: object
    claim_revision_id: object
    currency: str
    original_charge: Decimal
    payer_reported_credits: Decimal
    contractual_adjustments: Decimal
    residual: Decimal
    lines: tuple[LedgerLineView, ...]


@dataclass(frozen=True)
class OutcomeArchiveEvent:
    event_id: object
    sender_id: str
    kind: str
    semantic_event_id: object
    semantic_digest: str
    claim_revision_id: object
    intent_id: object
    receiver_observation_id: object
    lifecycle_sequence: int | None
    lifecycle_status: str


@dataclass(frozen=True)
class OutcomeArchiveEntry:
    entry_id: object
    event_id: object
    claim_revision_id: object
    claim_line_id: object
    kind: str
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class OutcomeArchiveBasis:
    basis_id: object
    claim_line_id: object
    line_ordinal: int
    original_charge: Decimal
    payer_reported_credits: Decimal
    contractual_adjustments: Decimal
    residual: Decimal


@dataclass(frozen=True)
class OutcomeArchiveAccount:
    account_id: object
    claim_revision_id: object
    currency: str
    original_charge: Decimal
    payer_reported_credits: Decimal
    contractual_adjustments: Decimal
    residual: Decimal
    bases: tuple[OutcomeArchiveBasis, ...]


@dataclass(frozen=True)
class OutcomeArchiveSnapshot:
    organization_id: object
    encounter_id: object
    events: tuple[OutcomeArchiveEvent, ...]
    entries: tuple[OutcomeArchiveEntry, ...]
    accounts: tuple[OutcomeArchiveAccount, ...]
    conflict_ids: tuple[object, ...]


def inbound_candidates(*, actor, organization_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    return InboundCandidate.objects.filter(organization_id=organization_id).select_related(
        "delivery"
    ).prefetch_related("lines").order_by("-interpreted_at", "id")


def candidate_detail(*, actor, organization_id, candidate_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        return InboundCandidate.objects.select_related("delivery__artifact").prefetch_related(
            "lines", "accepted_evidence__event"
        ).get(organization_id=organization_id, id=candidate_id)
    except (InboundCandidate.DoesNotExist, ValueError) as exc:
        raise CommandError("unmatched_target") from exc


def current_lifecycle(*, actor, organization_id, intent_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    events = AcceptedEvent.objects.filter(
        organization_id=organization_id, intent_id=intent_id,
        kind=InboundCandidate.KIND_LIFECYCLE,
    ).order_by("lifecycle_sequence", "accepted_at", "id")
    contiguous = []
    expected = 1
    for event in events:
        if event.lifecycle_sequence != expected:
            break
        contiguous.append(event)
        expected += 1
    return tuple(contiguous)


def ledger_detail(*, actor, organization_id, claim_revision_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        account = FinancialAccount.objects.prefetch_related("charge_lines").get(
            organization_id=organization_id, claim_revision_id=claim_revision_id
        )
    except (FinancialAccount.DoesNotExist, ValueError) as exc:
        raise CommandError("financial_account_not_found") from exc
    line_views = []
    payment_total = Decimal("0.00")
    adjustment_total = Decimal("0.00")
    for basis in account.charge_lines.order_by("line_ordinal", "id"):
        payments = PostingEntry.objects.filter(
            organization_id=organization_id, charge_basis=basis,
            kind=PostingEntry.KIND_PAYMENT,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        adjustments = PostingEntry.objects.filter(
            organization_id=organization_id, charge_basis=basis,
            kind=PostingEntry.KIND_ADJUSTMENT,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        payment_total += payments
        adjustment_total += adjustments
        line_views.append(LedgerLineView(
            basis.line_ordinal, basis.claim_line_id, basis.original_charge,
            payments, adjustments, basis.original_charge - payments - adjustments,
        ))
    return LedgerView(
        account.id, account.claim_revision_id, account.currency,
        account.original_charge, payment_total, adjustment_total,
        account.original_charge - payment_total - adjustment_total,
        tuple(line_views),
    )


def archive_outcome_snapshot(*, actor, organization_id, encounter_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    events = AcceptedEvent.objects.filter(
        organization_id=organization_id,
        claim_revision__encounter_id=encounter_id,
    ).order_by("accepted_at", "id")
    event_values = tuple(OutcomeArchiveEvent(
        item.id, item.sender_id, item.kind, item.event_id, item.semantic_digest,
        item.claim_revision_id, item.intent_id, item.receiver_observation_id,
        item.lifecycle_sequence, item.lifecycle_status,
    ) for item in events)
    event_ids = [item.event_id for item in event_values]
    entries = PostingEntry.objects.filter(
        organization_id=organization_id, event_id__in=event_ids,
    ).select_related("account").order_by("posted_at", "id")
    entry_values = tuple(OutcomeArchiveEntry(
        item.id, item.event_id, item.account.claim_revision_id,
        item.claim_line_id, item.kind, item.amount, item.currency,
    ) for item in entries)
    account_values = []
    accounts = FinancialAccount.objects.filter(
        organization_id=organization_id,
        claim_revision_id__in={item.claim_revision_id for item in event_values},
    ).prefetch_related("charge_lines").order_by("created_at", "id")
    for account in accounts:
        basis_values = []
        payment_total = Decimal("0.00")
        adjustment_total = Decimal("0.00")
        for basis in account.charge_lines.order_by("line_ordinal", "id"):
            payments = PostingEntry.objects.filter(
                organization_id=organization_id, charge_basis=basis,
                kind=PostingEntry.KIND_PAYMENT,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            adjustments = PostingEntry.objects.filter(
                organization_id=organization_id, charge_basis=basis,
                kind=PostingEntry.KIND_ADJUSTMENT,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            payment_total += payments
            adjustment_total += adjustments
            basis_values.append(OutcomeArchiveBasis(
                basis.id, basis.claim_line_id, basis.line_ordinal,
                basis.original_charge, payments, adjustments,
                basis.original_charge - payments - adjustments,
            ))
        account_values.append(OutcomeArchiveAccount(
            account.id, account.claim_revision_id, account.currency,
            account.original_charge, payment_total, adjustment_total,
            account.original_charge - payment_total - adjustment_total,
            tuple(basis_values),
        ))
    candidates = InboundCandidate.objects.filter(
        organization_id=organization_id,
        claim_revision_id__in={item.claim_revision_id for item in event_values},
    )
    conflicts = InboundConflict.objects.filter(
        Q(existing_candidate__in=candidates) | Q(conflicting_candidate__in=candidates)
    ).order_by("recorded_at", "id").values_list("id", flat=True)
    return OutcomeArchiveSnapshot(
        organization_id, encounter_id, event_values, entry_values,
        tuple(account_values), tuple(conflicts)
    )
