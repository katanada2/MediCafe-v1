from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import threading
import unittest
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from medicafe_v1.claims.delivery_adapter import (
    MAX_ENVELOPE_BYTES,
    MAX_EVIDENCE_JSON_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_TIMEOUT_SECONDS,
    RECEIVER_ID,
    FrozenDelivery,
    LoopbackReceiverAdapter,
)
from medicafe_v1.sources.domain import CommandError


class _ResponseState:
    def __init__(self):
        self.responses = deque()
        self.requests = []
        self._lock = threading.Lock()

    def queue(self, body, *, status=200, headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.responses.append((status, dict(headers or {}), bytes(body)))

    def next_response(self, request):
        with self._lock:
            if not self.responses:
                return 500, {}, b"{}"
            response = self.responses.popleft()
        if callable(response):
            return response(request)
        return response


class _LoopbackHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _serve(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        body = self.rfile.read(content_length)
        request = {
            "method": self.command,
            "path": self.path,
            "headers": dict(self.headers.items()),
            "body": body,
        }
        state = self.server.state
        with state._lock:
            state.requests.append(request)
        status, headers, payload = state.next_response(request)
        self.send_response(status)
        sent_headers = {name.lower() for name in headers}
        for name, value in headers.items():
            self.send_header(name, value)
        if "content-length" not in sent_headers:
            self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    do_GET = _serve
    do_POST = _serve

    def log_message(self, _format, *_args):
        return


class _LoopbackServer:
    def __init__(self):
        self.state = _ResponseState()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _LoopbackHandler)
        self.server.state = self.state
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class LoopbackReceiverAdapterTests(SimpleTestCase):
    def setUp(self):
        self.receiver = _LoopbackServer()

    def tearDown(self):
        self.receiver.close()

    def _endpoints(self, *, trailing_slash=False):
        suffix = "/" if trailing_slash else ""
        return {
            "v1": f"{self.receiver.base_url}/v1{suffix}",
            "v2": f"{self.receiver.base_url}/v2{suffix}",
        }

    def _settings(self, *, trailing_slash=False):
        return override_settings(
            SYNTHETIC_RECEIVER_ENDPOINTS=self._endpoints(
                trailing_slash=trailing_slash
            )
        )

    def _frozen(self, version="v1", payload=b'{"synthetic":true}\n'):
        return FrozenDelivery(
            organization_id="00000000-0000-0000-0000-000000000001",
            intent_id="00000000-0000-0000-0000-000000000002",
            claim_revision_id="00000000-0000-0000-0000-000000000003",
            delivery_key="00000000-0000-0000-0000-000000000004",
            attempt_id="00000000-0000-0000-0000-000000000005",
            receiver_id=RECEIVER_ID,
            receiver_version=version,
            envelope_digest=hashlib.sha256(payload).hexdigest(),
            byte_length=len(payload),
            payload=payload,
        )

    @staticmethod
    def _json_bytes(body):
        return json.dumps(body, separators=(",", ":")).encode("utf-8")

    def _evidence_body(self, frozen, **overrides):
        body = {
            "state": "accepted",
            "receiver_id": frozen.receiver_id,
            "receiver_version": frozen.receiver_version,
            "organization_id": frozen.organization_id,
            "intent_id": frozen.intent_id,
            "claim_revision_id": frozen.claim_revision_id,
            "delivery_key": frozen.delivery_key,
            "receipt_id": f"receipt-{frozen.receiver_version}",
            "reported_attempt_id": frozen.attempt_id,
            "envelope_digest": frozen.envelope_digest,
            "byte_length": frozen.byte_length,
            "received_bytes": base64.b64encode(frozen.payload).decode("ascii"),
            "no_acceptance_guaranteed": False,
            "observed_at": "2026-01-01T00:00:00+00:00",
        }
        body.update(overrides)
        return body

    def test_v1_and_v2_send_exact_payload_and_parse_readback(self):
        payload = b'{"synthetic":"exact bytes"}\x00\n'
        with self._settings():
            adapter = LoopbackReceiverAdapter(timeout=1)
            for version in ("v1", "v2"):
                frozen = self._frozen(version, payload)
                self.receiver.state.queue(
                    self._json_bytes({"status": "accepted", "reason": "SENTINEL"})
                )
                self.receiver.state.queue(self._json_bytes(self._evidence_body(frozen)))

                result = adapter.send(frozen)
                evidence = adapter.readback(frozen)

                self.assertEqual((result.status, result.reason), ("accepted", "receiver_response"))
                self.assertNotIn("SENTINEL", result.reason)
                self.assertIsNotNone(evidence)
                self.assertEqual(evidence.received_bytes, payload)
                self.assertEqual(evidence.receiver_version, version)
                self.assertEqual(evidence.reported_attempt_id, frozen.attempt_id)

            self.assertEqual(
                [request["body"] for request in self.receiver.state.requests[::2]],
                [payload, payload],
            )
            self.assertEqual(
                [request["path"] for request in self.receiver.state.requests[::2]],
                ["/v1/deliver", "/v2/deliver"],
            )
            self.assertEqual(
                [request["path"] for request in self.receiver.state.requests[1::2]],
                [
                    "/v1/receipts/00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000004?attempt_id=00000000-0000-0000-0000-000000000005",
                    "/v2/receipts/00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000004?attempt_id=00000000-0000-0000-0000-000000000005",
                ],
            )

    def test_proxy_environment_is_ignored_and_redirect_is_not_followed(self):
        frozen = self._frozen()
        with self._settings(), patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "http://127.0.0.1:1",
                "HTTPS_PROXY": "http://127.0.0.1:1",
                "ALL_PROXY": "http://127.0.0.1:1",
                "NO_PROXY": "",
            },
            clear=False,
        ):
            adapter = LoopbackReceiverAdapter(timeout=1)
            self.receiver.state.queue(self._json_bytes({"status": "accepted"}))
            direct = adapter.send(frozen)
            self.assertEqual(direct.status, "accepted")

            self.receiver.state.queue(
                self._json_bytes({"status": "rejected", "reason": "SENTINEL"}),
                status=302,
                headers={"Location": f"{self.receiver.base_url}/evil"},
            )
            redirected = adapter.send(frozen)

        self.assertEqual(
            (redirected.status, redirected.reason),
            ("unknown", "receiver_response_invalid"),
        )
        self.assertEqual(
            [request["path"] for request in self.receiver.state.requests],
            ["/v1/deliver", "/v1/deliver"],
        )

    def test_readback_redirect_becomes_command_error_without_following(self):
        frozen = self._frozen()
        with self._settings():
            adapter = LoopbackReceiverAdapter(timeout=1)
            self.receiver.state.queue(
                b"redirect",
                status=302,
                headers={"Location": f"{self.receiver.base_url}/evil"},
            )
            with self.assertRaises(CommandError) as raised:
                adapter.readback(frozen)

        self.assertEqual(raised.exception.reason_code, "receiver_readback_failed")
        self.assertEqual(
            [request["path"] for request in self.receiver.state.requests],
            ["/v1/receipts/00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000004?attempt_id=00000000-0000-0000-0000-000000000005"],
        )

    def test_configuration_rejects_non_loopback_and_unsafe_urls(self):
        base = self.receiver.base_url
        bad_endpoints = (
            f"https://127.0.0.1:{self.receiver.server.server_port}/v1",
            f"http://example.test:{self.receiver.server.server_port}/v1",
            f"http://user:password@127.0.0.1:{self.receiver.server.server_port}/v1",
            f"http://127.0.0.1:{self.receiver.server.server_port}/v1?",
            f"http://127.0.0.1:{self.receiver.server.server_port}/v1#fragment",
            f"http://127.0.0.1:{self.receiver.server.server_port}/v1;params",
            f"{base}/v1/extra",
            f"{base}/v1//",
            f"{base}/v2",
            f"http://127.0.0.1:99999/v1",
            f"{base}/v1%2f..",
        )
        adapter = LoopbackReceiverAdapter(timeout=1)
        for endpoint in bad_endpoints:
            with self.subTest(endpoint=endpoint), override_settings(
                SYNTHETIC_RECEIVER_ENDPOINTS={"v1": endpoint, "v2": f"{base}/v2"}
            ):
                with self.assertRaises(CommandError) as raised:
                    adapter.validate_configuration(RECEIVER_ID, "v1")
                self.assertEqual(
                    raised.exception.reason_code,
                    "receiver_configuration_not_loopback",
                )

        with override_settings(SYNTHETIC_RECEIVER_ENDPOINTS={"v1": None, "v2": None}):
            with self.assertRaises(CommandError) as raised:
                adapter.validate_configuration(RECEIVER_ID, "v1")
        self.assertEqual(raised.exception.reason_code, "receiver_configuration_missing")

    def test_send_malformed_or_oversized_json_is_unknown_without_wire_reason(self):
        frozen = self._frozen()
        raw_bodies = (
            b"[]",
            b'{"status":"accepted","status":"rejected"}',
            b'{"status":true}',
            b'{"status":[]}',
            b'{"status":"unknown","reason":"SENTINEL"}',
            b"\xff",
            b'{"status":NaN}',
            b"{" + b"x" * (MAX_RESPONSE_BYTES + 1),
        )
        with self._settings():
            adapter = LoopbackReceiverAdapter(timeout=1)
            for raw_body in raw_bodies:
                with self.subTest(raw_body=raw_body[:32]):
                    self.receiver.state.queue(raw_body)
                    result = adapter.send(frozen)
                    self.assertEqual(
                        (result.status, result.reason),
                        ("unknown", "receiver_response_invalid"),
                    )
                    self.assertNotIn("SENTINEL", result.reason)

    def test_http_rejection_uses_fixed_reason(self):
        frozen = self._frozen()
        with self._settings():
            adapter = LoopbackReceiverAdapter(timeout=1)
            self.receiver.state.queue(
                self._json_bytes({"status": "rejected", "reason": "SENTINEL"}),
                status=409,
            )
            result = adapter.send(frozen)

        self.assertEqual((result.status, result.reason), ("rejected", "receiver_rejected"))
        self.assertNotIn("SENTINEL", result.reason)

    def test_readback_rejects_bad_json_types_and_base64(self):
        frozen = self._frozen()
        invalid_bodies = [
            b"[]",
            b'{"state":"accepted","state":"rejected"}',
            self._evidence_body(frozen, byte_length=True),
            self._evidence_body(frozen, byte_length=1.5),
            self._evidence_body(frozen, no_acceptance_guaranteed=1),
            self._evidence_body(frozen, received_bytes=123),
            self._evidence_body(frozen, received_bytes="%%%%"),
            self._evidence_body(frozen, state=True),
            self._evidence_body(frozen, observed_at=""),
            self._evidence_body(frozen, observed_at="2026-99-99T00:00:00Z"),
            self._evidence_body(frozen, organization_id="not-a-uuid"),
            self._evidence_body(frozen, reported_attempt_id="bad"),
            self._evidence_body(frozen, envelope_digest="z" * 64),
            self._evidence_body(
                frozen, organization_id="x" * 129
            ),
            self._evidence_body(
                frozen, received_bytes="A" * (MAX_ENVELOPE_BYTES * 2)
            ),
        ]
        raw_bodies = [
            body if isinstance(body, bytes) else self._json_bytes(body)
            for body in invalid_bodies
        ]
        raw_bodies.extend(
            (
                b"\xff",
                b"{" + b"x" * (MAX_EVIDENCE_JSON_BYTES + 1),
            )
        )
        with self._settings():
            adapter = LoopbackReceiverAdapter(timeout=1)
            for raw_body in raw_bodies:
                with self.subTest(raw_body=raw_body[:32]):
                    self.receiver.state.queue(raw_body)
                    with self.assertRaises(CommandError) as raised:
                        adapter.readback(frozen)
                    self.assertEqual(
                        raised.exception.reason_code, "receiver_readback_invalid"
                    )

    def test_readback_preserves_mismatched_tuple_and_bytes_for_owner_validation(self):
        frozen = self._frozen()
        body = self._evidence_body(
            frozen,
            organization_id=str(uuid.uuid4()),
            envelope_digest="f" * 64,
            byte_length=1,
            received_bytes=base64.b64encode(b"wrong-bytes").decode("ascii"),
        )
        with self._settings():
            adapter = LoopbackReceiverAdapter(timeout=1)
            self.receiver.state.queue(self._json_bytes(body))
            evidence = adapter.readback(frozen)

        self.assertEqual(evidence.organization_id, body["organization_id"])
        self.assertEqual(evidence.envelope_digest, "f" * 64)
        self.assertEqual(evidence.byte_length, 1)
        self.assertEqual(evidence.received_bytes, b"wrong-bytes")

    def test_readback_allows_one_megabyte_base64_payload_with_bounded_wire_size(self):
        payload = b"x" * MAX_ENVELOPE_BYTES
        frozen = self._frozen(payload=payload)
        body = self._evidence_body(frozen)
        raw_body = self._json_bytes(body)
        self.assertLessEqual(len(raw_body), MAX_EVIDENCE_JSON_BYTES)
        with self._settings():
            adapter = LoopbackReceiverAdapter(timeout=1)
            self.receiver.state.queue(raw_body)
            evidence = adapter.readback(frozen)

        self.assertEqual(evidence.received_bytes, payload)
        self.assertEqual(evidence.byte_length, MAX_ENVELOPE_BYTES)

    def test_timeout_is_finite_and_bounded(self):
        invalid_timeouts = (
            True,
            False,
            0,
            -1,
            math.inf,
            math.nan,
            MAX_TIMEOUT_SECONDS + 0.1,
            10**1000,
            "1",
        )
        for timeout in invalid_timeouts:
            with self.subTest(timeout=timeout):
                with self.assertRaises(CommandError) as raised:
                    LoopbackReceiverAdapter(timeout=timeout)
                self.assertEqual(raised.exception.reason_code, "receiver_timeout_invalid")

        self.assertEqual(LoopbackReceiverAdapter(timeout=0.001).timeout, 0.001)

    def test_missing_readback_is_not_observed(self):
        frozen = self._frozen()
        with self._settings():
            adapter = LoopbackReceiverAdapter(timeout=1)
            self.receiver.state.queue(b"missing", status=404)
            self.assertIsNone(adapter.readback(frozen))


if __name__ == "__main__":
    unittest.main()
