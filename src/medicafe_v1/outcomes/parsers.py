from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from medicafe_v1.sources.domain import CommandError


INTERPRETER_VERSION = "f4-outcomes-v1"
SCHEMA_VERSION = "synthetic-outcomes-v1"
SENDER_RECEIVERS = {
    "synthetic-sender-v1": ("synthetic-receiver", "v1"),
    "synthetic-sender-v2": ("synthetic-receiver", "v2"),
}
BASE_KEYS = {
    "schema_version", "kind", "sender_id", "event_id", "delivery_key",
    "intent_id", "claim_revision_id", "receiver_receipt_id",
}
LIFECYCLE_KEYS = BASE_KEYS | {
    "lifecycle_sequence", "predecessor_event_id", "status",
}
REMITTANCE_KEYS = BASE_KEYS | {"currency", "lines"}
MONEY_RE = re.compile(r"^(0|[1-9][0-9]{0,7})\.[0-9]{2}$")


@dataclass(frozen=True)
class ParsedInboundLine:
    line_ordinal: int
    paid_amount: Decimal
    contractual_adjustment: Decimal


@dataclass(frozen=True)
class ParsedInbound:
    schema_version: str
    kind: str
    sender_id: str
    event_id: uuid.UUID
    delivery_key: uuid.UUID
    intent_id: uuid.UUID
    claim_revision_id: uuid.UUID
    receiver_receipt_id: str
    currency: str
    lifecycle_sequence: int | None
    predecessor_event_id: uuid.UUID | None
    lifecycle_status: str
    lines: tuple[ParsedInboundLine, ...]
    normalized_content: dict
    semantic_bytes: bytes
    semantic_digest: str


def _object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CommandError("malformed_or_unsupported")
        result[key] = value
    return result


def _uuid(value):
    if not isinstance(value, str):
        raise CommandError("malformed_or_unsupported")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise CommandError("malformed_or_unsupported") from exc
    if str(parsed) != value:
        raise CommandError("malformed_or_unsupported")
    return parsed


def _money(value):
    if not isinstance(value, str) or not MONEY_RE.fullmatch(value):
        raise CommandError("malformed_or_unsupported")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise CommandError("malformed_or_unsupported") from exc
    if not amount.is_finite() or amount < 0:
        raise CommandError("malformed_or_unsupported")
    return amount


def _canonical(normalized):
    encoded = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return encoded, hashlib.sha256(encoded).hexdigest()


def parse_inbound(content, *, source_namespace, media_type):
    if media_type != "application/json" or len(content) > 1024 * 1024:
        raise CommandError("malformed_or_unsupported")
    try:
        value = json.loads(
            content.decode("utf-8"), object_pairs_hook=_object_without_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                CommandError("malformed_or_unsupported")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CommandError("malformed_or_unsupported") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise CommandError("malformed_or_unsupported")
    kind = value.get("kind")
    expected_namespace = {
        "lifecycle": "synthetic-lifecycle",
        "remittance": "synthetic-remittance",
    }.get(kind)
    if expected_namespace is None or source_namespace != expected_namespace:
        raise CommandError("malformed_or_unsupported")
    expected_keys = LIFECYCLE_KEYS if kind == "lifecycle" else REMITTANCE_KEYS
    if set(value) != expected_keys:
        raise CommandError("malformed_or_unsupported")
    sender_id = value.get("sender_id")
    if sender_id not in SENDER_RECEIVERS:
        raise CommandError("malformed_or_unsupported")
    receipt_id = value.get("receiver_receipt_id")
    if not isinstance(receipt_id, str) or not 1 <= len(receipt_id) <= 100:
        raise CommandError("malformed_or_unsupported")

    event_id = _uuid(value.get("event_id"))
    delivery_key = _uuid(value.get("delivery_key"))
    intent_id = _uuid(value.get("intent_id"))
    claim_revision_id = _uuid(value.get("claim_revision_id"))
    lines = ()
    currency = ""
    sequence = None
    predecessor = None
    status = ""
    if kind == "lifecycle":
        sequence = value.get("lifecycle_sequence")
        status = value.get("status")
        if (
            not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1
            or status not in {"ACK_ACCEPTED", "ACK_REJECTED"}
        ):
            raise CommandError("malformed_or_unsupported")
        raw_predecessor = value.get("predecessor_event_id")
        if sequence == 1:
            if raw_predecessor is not None:
                raise CommandError("malformed_or_unsupported")
        else:
            predecessor = _uuid(raw_predecessor)
    else:
        currency = value.get("currency")
        raw_lines = value.get("lines")
        if currency != "USD" or not isinstance(raw_lines, list) or not 1 <= len(raw_lines) <= 100:
            raise CommandError("malformed_or_unsupported")
        parsed_lines = []
        seen = set()
        for raw_line in raw_lines:
            if not isinstance(raw_line, dict) or set(raw_line) != {
                "line_ordinal", "paid_amount", "contractual_adjustment",
            }:
                raise CommandError("malformed_or_unsupported")
            ordinal = raw_line["line_ordinal"]
            if (
                not isinstance(ordinal, int) or isinstance(ordinal, bool)
                or not 1 <= ordinal <= 100 or ordinal in seen
            ):
                raise CommandError("malformed_or_unsupported")
            seen.add(ordinal)
            paid = _money(raw_line["paid_amount"])
            adjustment = _money(raw_line["contractual_adjustment"])
            if paid == 0 and adjustment == 0:
                raise CommandError("malformed_or_unsupported")
            parsed_lines.append(ParsedInboundLine(ordinal, paid, adjustment))
        lines = tuple(parsed_lines)

    normalized = {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "sender_id": sender_id,
        "event_id": str(event_id),
        "delivery_key": str(delivery_key),
        "intent_id": str(intent_id),
        "claim_revision_id": str(claim_revision_id),
        "receiver_receipt_id": receipt_id,
    }
    if kind == "lifecycle":
        normalized.update({
            "lifecycle_sequence": sequence,
            "predecessor_event_id": str(predecessor) if predecessor else None,
            "status": status,
        })
    else:
        normalized.update({
            "currency": currency,
            "lines": [{
                "line_ordinal": line.line_ordinal,
                "paid_amount": f"{line.paid_amount:.2f}",
                "contractual_adjustment": f"{line.contractual_adjustment:.2f}",
            } for line in lines],
        })
    semantic_bytes, semantic_digest = _canonical(normalized)
    return ParsedInbound(
        SCHEMA_VERSION, kind, sender_id, event_id, delivery_key, intent_id,
        claim_revision_id, receipt_id, currency, sequence, predecessor, status,
        lines, normalized, semantic_bytes, semantic_digest,
    )
