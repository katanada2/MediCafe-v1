"""Loopback-only F3 transport and independent receiver readback."""

from __future__ import annotations

import base64
import binascii
import json
import math
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from medicafe_v1.sources.domain import CommandError


RECEIVER_ID = "synthetic-receiver"
SUPPORTED_RECEIVER_VERSIONS = frozenset({"v1", "v2"})
MAX_ENVELOPE_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 4096
MAX_BASE64_CHARS = ((MAX_ENVELOPE_BYTES + 2) // 3) * 4
MAX_EVIDENCE_JSON_BYTES = MAX_BASE64_CHARS + 16384
MAX_TIMEOUT_SECONDS = 60.0
MAX_ENDPOINT_LENGTH = 2048
MAX_RECEIVER_ID_LENGTH = 80
MAX_RECEIVER_VERSION_LENGTH = 20
MAX_IDENTITY_FIELD_LENGTH = 128
MAX_RECEIPT_ID_LENGTH = 100
MAX_OBSERVED_AT_LENGTH = 64
MAX_ATTEMPT_ID_LENGTH = 128


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect_rejected", headers, fp)


@dataclass(frozen=True)
class FrozenDelivery:
    organization_id: str
    intent_id: str
    claim_revision_id: str
    delivery_key: str
    attempt_id: str
    receiver_id: str
    receiver_version: str
    envelope_digest: str
    byte_length: int
    payload: bytes


@dataclass(frozen=True)
class TransportResult:
    status: str
    reason: str


@dataclass(frozen=True)
class ReceiverEvidence:
    state: str
    receiver_id: str
    receiver_version: str
    organization_id: str
    intent_id: str
    claim_revision_id: str
    delivery_key: str
    receipt_id: str
    reported_attempt_id: str | None
    envelope_digest: str
    byte_length: int
    received_bytes: bytes | None
    no_acceptance_guaranteed: bool
    observed_at: str


class LoopbackReceiverAdapter:
    def __init__(self, *, timeout=None):
        configured_timeout = (
            settings.SYNTHETIC_RECEIVER_TIMEOUT_SECONDS if timeout is None else timeout
        )
        if (
            isinstance(configured_timeout, bool)
            or not isinstance(configured_timeout, (int, float))
        ):
            raise CommandError("receiver_timeout_invalid")
        try:
            timeout_value = float(configured_timeout)
        except (OverflowError, ValueError) as exc:
            raise CommandError("receiver_timeout_invalid") from exc
        if not math.isfinite(timeout_value) or not 0 < timeout_value <= MAX_TIMEOUT_SECONDS:
            raise CommandError("receiver_timeout_invalid")
        self.timeout = timeout_value
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _RejectRedirects()
        )

    def _base_url(self, version):
        if not isinstance(version, str) or version not in SUPPORTED_RECEIVER_VERSIONS:
            raise CommandError("receiver_configuration_missing")
        endpoints = getattr(settings, "SYNTHETIC_RECEIVER_ENDPOINTS", None)
        if not hasattr(endpoints, "get"):
            raise CommandError("receiver_configuration_missing")
        endpoint = endpoints.get(version)
        if not isinstance(endpoint, str) or not endpoint:
            raise CommandError("receiver_configuration_missing")
        if (
            len(endpoint) > MAX_ENDPOINT_LENGTH
            or endpoint != endpoint.strip()
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in endpoint)
            or "?" in endpoint
            or "#" in endpoint
        ):
            raise CommandError("receiver_configuration_not_loopback")
        try:
            parsed = urllib.parse.urlparse(endpoint)
            hostname = parsed.hostname
            port = parsed.port
        except (TypeError, ValueError) as exc:
            raise CommandError("receiver_configuration_not_loopback") from exc
        expected_path = f"/{version}"
        if (
            parsed.scheme != "http"
            or hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.params
            or parsed.query
            or parsed.fragment
            or parsed.path not in {expected_path, f"{expected_path}/"}
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise CommandError("receiver_configuration_not_loopback")
        return endpoint.rstrip("/")

    def validate_configuration(self, receiver_id, version):
        if receiver_id != RECEIVER_ID:
            raise CommandError("receiver_identity_mismatch")
        self._base_url(version)

    @staticmethod
    def _read_json(response, limit, reason):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise CommandError(reason)
        try:
            raw = response.read(limit + 1)
        except (AttributeError, TypeError) as exc:
            raise CommandError(reason) from exc
        if not isinstance(raw, (bytes, bytearray, memoryview)):
            raise CommandError(reason)
        raw = bytes(raw)
        if len(raw) > limit:
            raise CommandError(reason)
        try:
            body = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=LoopbackReceiverAdapter._object_from_pairs,
                parse_constant=LoopbackReceiverAdapter._reject_constant,
            )
        except (TypeError, ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise CommandError(reason) from exc
        if not isinstance(body, dict):
            raise CommandError(reason)
        return body

    @staticmethod
    def _object_from_pairs(pairs):
        body = {}
        for key, value in pairs:
            if key in body:
                raise ValueError("duplicate_json_key")
            body[key] = value
        return body

    @staticmethod
    def _reject_constant(value):
        raise ValueError(f"invalid_json_constant:{value}")

    @staticmethod
    def _headers(frozen, *, test_mode=None):
        headers = {
            "Content-Type": "application/octet-stream",
            "X-Synthetic-Organization": frozen.organization_id,
            "X-Synthetic-Intent": frozen.intent_id,
            "X-Synthetic-Revision": frozen.claim_revision_id,
            "X-Synthetic-Delivery-Key": frozen.delivery_key,
            "X-Synthetic-Attempt": frozen.attempt_id,
            "X-Synthetic-Receiver": frozen.receiver_id,
            "X-Synthetic-Receiver-Version": frozen.receiver_version,
            "X-Synthetic-SHA256": frozen.envelope_digest,
            "X-Synthetic-Byte-Length": str(frozen.byte_length),
        }
        if test_mode:
            headers["X-Synthetic-Test-Mode"] = test_mode
        return headers

    def send(self, frozen, *, test_mode=None):
        if frozen.receiver_id != RECEIVER_ID:
            raise CommandError("receiver_identity_mismatch")
        request = urllib.request.Request(
            f"{self._base_url(frozen.receiver_version)}/deliver",
            data=frozen.payload,
            headers=self._headers(frozen, test_mode=test_mode),
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = self._read_json(response, MAX_RESPONSE_BYTES, "receiver_response_invalid")
                status = body.get("status")
                if not isinstance(status, str) or status not in {"accepted", "rejected"}:
                    return TransportResult("unknown", "receiver_response_invalid")
                return TransportResult(status, "receiver_response")
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                return TransportResult("unknown", "receiver_response_invalid")
            try:
                body = self._read_json(exc, MAX_RESPONSE_BYTES, "receiver_response_invalid")
            except CommandError:
                return TransportResult("unknown", "receiver_response_invalid")
            if body.get("status") == "rejected":
                return TransportResult("rejected", "receiver_rejected")
            return TransportResult("unknown", "http_error")
        except CommandError:
            return TransportResult("unknown", "receiver_response_invalid")
        except (OSError, TimeoutError, urllib.error.URLError):
            return TransportResult("unknown", "transport_uncertain")

    def readback(self, frozen):
        query = urllib.parse.urlencode({"attempt_id": frozen.attempt_id})
        key = urllib.parse.quote(frozen.delivery_key, safe="")
        org = urllib.parse.quote(frozen.organization_id, safe="")
        request = urllib.request.Request(
            f"{self._base_url(frozen.receiver_version)}/receipts/{org}/{key}?{query}",
            headers={
                "Accept": "application/json",
                "X-Synthetic-Receiver": frozen.receiver_id,
                "X-Synthetic-Receiver-Version": frozen.receiver_version,
            },
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = self._read_json(
                    response, MAX_EVIDENCE_JSON_BYTES, "receiver_readback_invalid"
                )
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise CommandError("receiver_readback_failed") from exc
        except CommandError:
            raise
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise CommandError("receiver_readback_failed") from exc
        encoded = body.get("received_bytes")
        if encoded is not None and not isinstance(encoded, str):
            raise CommandError("receiver_readback_invalid")
        if encoded is not None and len(encoded) > MAX_BASE64_CHARS:
            raise CommandError("receiver_readback_invalid")
        try:
            received = (
                base64.b64decode(encoded, validate=True) if encoded is not None else None
            )
        except (binascii.Error, ValueError, TypeError) as exc:
            raise CommandError("receiver_readback_invalid") from exc
        required = (
            "state", "receiver_id", "receiver_version", "organization_id", "intent_id",
            "claim_revision_id", "delivery_key", "receipt_id", "envelope_digest",
            "byte_length", "observed_at",
        )
        if any(name not in body for name in required):
            raise CommandError("receiver_readback_invalid")
        string_fields = (
            "state", "receiver_id", "receiver_version", "organization_id", "intent_id",
            "claim_revision_id", "delivery_key", "receipt_id", "envelope_digest", "observed_at",
        )
        if any(not isinstance(body[name], str) for name in string_fields):
            raise CommandError("receiver_readback_invalid")
        if (
            body["state"] not in {"accepted", "rejected"}
            or len(body["receiver_id"]) > MAX_RECEIVER_ID_LENGTH
            or len(body["receiver_version"]) > MAX_RECEIVER_VERSION_LENGTH
            or any(
                len(body[name]) > MAX_IDENTITY_FIELD_LENGTH
                for name in (
                    "organization_id", "intent_id", "claim_revision_id", "delivery_key",
                )
            )
            or not 1 <= len(body["receipt_id"]) <= MAX_RECEIPT_ID_LENGTH
            or len(body["envelope_digest"]) != 64
            or not 1 <= len(body["observed_at"]) <= MAX_OBSERVED_AT_LENGTH
        ):
            raise CommandError("receiver_readback_invalid")
        byte_length = body["byte_length"]
        no_acceptance = body.get("no_acceptance_guaranteed", False)
        attempt_id = body.get("reported_attempt_id")
        if (
            isinstance(byte_length, bool) or not isinstance(byte_length, int)
            or not 1 <= byte_length <= MAX_ENVELOPE_BYTES
            or not isinstance(no_acceptance, bool)
            or (attempt_id is not None and not isinstance(attempt_id, str))
            or (isinstance(attempt_id, str) and len(attempt_id) > MAX_ATTEMPT_ID_LENGTH)
            or (received is not None and len(received) > MAX_ENVELOPE_BYTES)
        ):
            raise CommandError("receiver_readback_invalid")
        try:
            for name in (
                "organization_id", "intent_id", "claim_revision_id", "delivery_key"
            ):
                uuid.UUID(body[name])
            if attempt_id is not None:
                uuid.UUID(attempt_id)
            observed_at = parse_datetime(body["observed_at"])
        except (TypeError, ValueError, OverflowError):
            raise CommandError("receiver_readback_invalid") from None
        if (
            any(char not in "0123456789abcdef" for char in body["envelope_digest"])
            or observed_at is None
            or not timezone.is_aware(observed_at)
        ):
            raise CommandError("receiver_readback_invalid")
        return ReceiverEvidence(
            state=body["state"], receiver_id=body["receiver_id"],
            receiver_version=body["receiver_version"], organization_id=body["organization_id"],
            intent_id=body["intent_id"], claim_revision_id=body["claim_revision_id"],
            delivery_key=body["delivery_key"], receipt_id=body["receipt_id"],
            reported_attempt_id=attempt_id,
            envelope_digest=body["envelope_digest"], byte_length=byte_length,
            received_bytes=received,
            no_acceptance_guaranteed=no_acceptance,
            observed_at=body["observed_at"],
        )
