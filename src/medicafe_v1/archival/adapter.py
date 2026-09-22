from __future__ import annotations

import base64
import hashlib
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from django.conf import settings

from medicafe_v1.sources.domain import CommandError


MAX_PROJECTION_BYTES = 2 * 1024 * 1024


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect_rejected", headers, fp)


@dataclass(frozen=True)
class FrozenArchiveProjection:
    organization_id: str
    encounter_id: str
    projection_id: str
    projection_version: int
    attempt_id: str
    receiver_id: str
    receiver_version: str
    projection_digest: str
    byte_length: int
    payload: bytes


@dataclass(frozen=True)
class ArchiveTransportResult:
    status: str
    reason: str


@dataclass(frozen=True)
class ArchiveEvidence:
    receiver_id: str
    receiver_version: str
    target_receipt_id: str
    organization_id: str
    encounter_id: str
    projection_id: str
    projection_version: int
    reported_attempt_id: str | None
    projection_digest: str
    byte_length: int
    received_bytes: bytes
    observed_at: str


class LoopbackArchiveAdapter:
    def __init__(self, *, timeout=None, endpoint=None):
        value = settings.SYNTHETIC_ARCHIVE_TIMEOUT_SECONDS if timeout is None else timeout
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CommandError("archive_timeout_invalid")
        value = float(value)
        if not math.isfinite(value) or not 0 < value <= 60:
            raise CommandError("archive_timeout_invalid")
        self.timeout = value
        self.endpoint = endpoint if endpoint is not None else settings.SYNTHETIC_ARCHIVE_ENDPOINT
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _RejectRedirects()
        )

    def validate_configuration(self, receiver_id, receiver_version):
        if receiver_id != "synthetic-archive" or receiver_version != "v1":
            raise CommandError("archive_receiver_identity_mismatch")
        if not isinstance(self.endpoint, str) or not self.endpoint:
            raise CommandError("archive_configuration_missing")
        try:
            parsed = urllib.parse.urlparse(self.endpoint)
            port = parsed.port
        except (TypeError, ValueError) as exc:
            raise CommandError("archive_configuration_not_loopback") from exc
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None or parsed.password is not None
            or parsed.params or parsed.query or parsed.fragment
            or parsed.path.rstrip("/") != "/v1"
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise CommandError("archive_configuration_not_loopback")

    @staticmethod
    def _decode(response, reason):
        raw = response.read(((MAX_PROJECTION_BYTES + 2) // 3) * 4 + 8192)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommandError(reason) from exc
        if not isinstance(body, dict):
            raise CommandError(reason)
        return body

    def send(self, frozen):
        self.validate_configuration(frozen.receiver_id, frozen.receiver_version)
        body = json.dumps({
            "organization_id": frozen.organization_id,
            "encounter_id": frozen.encounter_id,
            "projection_id": frozen.projection_id,
            "projection_version": frozen.projection_version,
            "attempt_id": frozen.attempt_id,
            "projection_digest": frozen.projection_digest,
            "byte_length": frozen.byte_length,
            "payload_b64": base64.b64encode(frozen.payload).decode("ascii"),
        }, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint.rstrip('/')}/store", data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                result = self._decode(response, "archive_response_invalid")
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                return ArchiveTransportResult("rejected", "archive_target_conflict")
            return ArchiveTransportResult("unknown", "archive_transport_error")
        except (OSError, TimeoutError, urllib.error.URLError):
            return ArchiveTransportResult("unknown", "archive_transport_error")
        status = result.get("status")
        if status not in {"stored", "replayed"}:
            return ArchiveTransportResult("unknown", "archive_response_invalid")
        return ArchiveTransportResult("accepted", "archive_target_response")

    def readback(self, frozen):
        self.validate_configuration(frozen.receiver_id, frozen.receiver_version)
        query = urllib.parse.urlencode({
            "organization_id": frozen.organization_id,
            "projection_id": frozen.projection_id,
        })
        request = urllib.request.Request(
            f"{self.endpoint.rstrip('/')}/read?{query}", method="GET"
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = self._decode(response, "archive_readback_invalid")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise CommandError("archive_readback_unavailable") from exc
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise CommandError("archive_readback_unavailable") from exc
        expected = {
            "receiver_id", "receiver_version", "target_receipt_id",
            "organization_id", "encounter_id", "projection_id",
            "projection_version", "reported_attempt_id", "projection_digest",
            "byte_length", "received_bytes_b64", "observed_at",
        }
        if set(body) != expected:
            raise CommandError("archive_readback_invalid")
        try:
            received = base64.b64decode(body["received_bytes_b64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise CommandError("archive_readback_invalid") from exc
        if len(received) > MAX_PROJECTION_BYTES:
            raise CommandError("archive_readback_invalid")
        digest = hashlib.sha256(received).hexdigest()
        if digest != body["projection_digest"] or len(received) != body["byte_length"]:
            raise CommandError("archive_readback_invalid")
        return ArchiveEvidence(
            body["receiver_id"], body["receiver_version"], body["target_receipt_id"],
            body["organization_id"], body["encounter_id"], body["projection_id"],
            body["projection_version"], body["reported_attempt_id"],
            body["projection_digest"], body["byte_length"], received,
            body["observed_at"],
        )
