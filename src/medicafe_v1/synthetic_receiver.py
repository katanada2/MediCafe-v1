"""Separate-process, PostgreSQL-backed loopback receiver for synthetic F3."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import psycopg
from psycopg import sql


MAX_ENVELOPE_BYTES = 1024 * 1024
RECEIVER_ID = "synthetic-receiver"
SCHEMA_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def receiver_connection_kwargs():
    return {
        "dbname": os.environ.get("MEDICAFE_RECEIVER_DB_NAME", os.environ.get("POSTGRES_DB", "medicafe_v1")),
        "user": os.environ.get("MEDICAFE_RECEIVER_DB_USER", os.environ.get("POSTGRES_USER", "medicafe")),
        "password": os.environ.get("MEDICAFE_RECEIVER_DB_PASSWORD", os.environ.get("POSTGRES_PASSWORD", "")),
        "host": os.environ.get("MEDICAFE_RECEIVER_DB_HOST", os.environ.get("POSTGRES_HOST", "127.0.0.1")),
        "port": os.environ.get("MEDICAFE_RECEIVER_DB_PORT", os.environ.get("POSTGRES_PORT", "5432")),
        "connect_timeout": int(os.environ.get("POSTGRES_CONNECT_TIMEOUT", "3")),
    }


def initialize_ledger(schema):
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError("invalid receiver schema")
    with psycopg.connect(**receiver_connection_kwargs()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
            cursor.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {}.accepted_receipt (
                    id uuid PRIMARY KEY,
                    receiver_id varchar(80) NOT NULL,
                    receiver_version varchar(20) NOT NULL,
                    organization_id uuid NOT NULL,
                    intent_id uuid NOT NULL,
                    claim_revision_id uuid NOT NULL,
                    delivery_key uuid NOT NULL,
                    attempt_id uuid NOT NULL,
                    receipt_id varchar(100) NOT NULL,
                    envelope_digest char(64) NOT NULL,
                    byte_length integer NOT NULL,
                    received_bytes bytea NOT NULL,
                    observed_at timestamptz NOT NULL,
                    evidence_mode varchar(40) NOT NULL DEFAULT '',
                    UNIQUE (receiver_id, receiver_version, receipt_id)
                )
            """).format(sql.Identifier(schema)))
            cursor.execute(sql.SQL("""
                CREATE UNIQUE INDEX IF NOT EXISTS receiver_v1_delivery_key_uniq
                ON {}.accepted_receipt
                  (receiver_id, receiver_version, organization_id, delivery_key)
                WHERE receiver_version='v1'
            """).format(sql.Identifier(schema)))
            cursor.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {}.rejected_invocation (
                    id uuid PRIMARY KEY,
                    receiver_id varchar(80) NOT NULL,
                    receiver_version varchar(20) NOT NULL,
                    organization_id uuid NOT NULL,
                    intent_id uuid NOT NULL,
                    claim_revision_id uuid NOT NULL,
                    delivery_key uuid NOT NULL,
                    attempt_id uuid NOT NULL,
                    receipt_id varchar(100) NOT NULL,
                    envelope_digest char(64) NOT NULL,
                    byte_length integer NOT NULL,
                    attempted_bytes bytea NOT NULL,
                    observed_at timestamptz NOT NULL,
                    UNIQUE (receiver_id, receiver_version, receipt_id),
                    UNIQUE (receiver_id, receiver_version, organization_id, attempt_id)
                )
            """).format(sql.Identifier(schema)))
            cursor.execute(sql.SQL("""
                CREATE OR REPLACE FUNCTION {}.reject_ledger_change() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                  RAISE EXCEPTION 'synthetic receiver ledger is immutable' USING ERRCODE='55000';
                END;
                $$
            """).format(sql.Identifier(schema)))
            cursor.execute(sql.SQL("DROP TRIGGER IF EXISTS accepted_receipt_immutable ON {}.accepted_receipt").format(sql.Identifier(schema)))
            cursor.execute(sql.SQL("DROP TRIGGER IF EXISTS rejected_invocation_immutable ON {}.rejected_invocation").format(sql.Identifier(schema)))
            cursor.execute(sql.SQL("""
                CREATE TRIGGER accepted_receipt_immutable BEFORE UPDATE OR DELETE
                ON {}.accepted_receipt FOR EACH ROW EXECUTE FUNCTION {}.reject_ledger_change()
            """).format(sql.Identifier(schema), sql.Identifier(schema)))
            cursor.execute(sql.SQL("""
                CREATE TRIGGER rejected_invocation_immutable BEFORE UPDATE OR DELETE
                ON {}.rejected_invocation FOR EACH ROW EXECUTE FUNCTION {}.reject_ledger_change()
            """).format(sql.Identifier(schema), sql.Identifier(schema)))


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _unique_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


class ReceiverHandler(BaseHTTPRequestHandler):
    server_version = "MediCafeSyntheticReceiver/1"

    def log_message(self, format, *args):
        return

    @property
    def schema(self):
        return self.server.receiver_schema

    def _connection(self):
        return psycopg.connect(**receiver_connection_kwargs())

    def _respond(self, status, body):
        encoded = _json_bytes(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _version(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if not parts or parts[0] not in {"v1", "v2"}:
            return None
        return parts[0]

    def _metadata(self, version):
        mapping = {
            "organization_id": "X-Synthetic-Organization",
            "intent_id": "X-Synthetic-Intent",
            "claim_revision_id": "X-Synthetic-Revision",
            "delivery_key": "X-Synthetic-Delivery-Key",
            "attempt_id": "X-Synthetic-Attempt",
            "receiver_id": "X-Synthetic-Receiver",
            "receiver_version": "X-Synthetic-Receiver-Version",
            "envelope_digest": "X-Synthetic-SHA256",
        }
        values = {name: self.headers.get(header, "") for name, header in mapping.items()}
        try:
            for name in ("organization_id", "intent_id", "claim_revision_id", "delivery_key", "attempt_id"):
                values[name] = str(uuid.UUID(values[name]))
        except (ValueError, AttributeError):
            return None
        try:
            length = int(self.headers.get("X-Synthetic-Byte-Length", ""))
        except ValueError:
            return None
        if (
            values["receiver_id"] != RECEIVER_ID or values["receiver_version"] != version
            or len(values["envelope_digest"]) != 64
            or any(c not in "0123456789abcdef" for c in values["envelope_digest"])
            or not 1 <= length <= MAX_ENVELOPE_BYTES
            or values["delivery_key"] != values["intent_id"]
        ):
            return None
        values["byte_length"] = length
        return values

    def do_POST(self):
        parsed = urlparse(self.path)
        version = self._version()
        if version is None or parsed.path != f"/{version}/deliver" or parsed.query:
            self._respond(404, {"status": "unknown"})
            return
        metadata = self._metadata(version)
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            content_length = -1
        if metadata is None or content_length != metadata.get("byte_length"):
            self._respond(400, {"status": "rejected", "reason": "identity_invalid"})
            return
        self.connection.settimeout(float(os.environ.get("MEDICAFE_RECEIVER_SOCKET_TIMEOUT", "5.0")))
        try:
            body = self.rfile.read(content_length)
        except (OSError, TimeoutError, socket.timeout):
            self._respond(408, {"status": "unknown"})
            return
        if len(body) != content_length or hashlib.sha256(body).hexdigest() != metadata["envelope_digest"]:
            self._respond(400, {"status": "rejected", "reason": "body_invalid"})
            return
        try:
            envelope = _unique_json(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._respond(400, {"status": "rejected", "reason": "envelope_invalid"})
            return
        if (
            not isinstance(envelope, dict) or envelope.get("synthetic_only") is not True
            or envelope.get("organization_id") != metadata["organization_id"]
            or envelope.get("revision_id") != metadata["claim_revision_id"]
            or envelope.get("format_version") != "synthetic-json-v1"
            or envelope.get("route") != {"id": RECEIVER_ID, "version": version}
        ):
            self._respond(400, {"status": "rejected", "reason": "envelope_identity_invalid"})
            return
        test_mode = self.headers.get("X-Synthetic-Test-Mode", "")
        observed_at = datetime.now(timezone.utc)
        receipt_id = str(uuid.uuid4())
        if test_mode == "reject_before_acceptance":
            with self._connection() as conn, conn.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (metadata["attempt_id"],))
                cursor.execute(sql.SQL("""
                    SELECT 1 FROM {}.accepted_receipt
                    WHERE receiver_id=%s AND receiver_version=%s
                      AND organization_id=%s AND attempt_id=%s
                """).format(sql.Identifier(self.schema)), (
                    RECEIVER_ID, version, metadata["organization_id"], metadata["attempt_id"],
                ))
                if cursor.fetchone():
                    self._respond(409, {"status": "unknown"})
                    return
                cursor.execute(sql.SQL("""
                    INSERT INTO {}.rejected_invocation
                      (id,receiver_id,receiver_version,organization_id,intent_id,
                       claim_revision_id,delivery_key,attempt_id,receipt_id,envelope_digest,
                       byte_length,attempted_bytes,observed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (receiver_id,receiver_version,organization_id,attempt_id)
                    DO NOTHING
                """).format(sql.Identifier(self.schema)), (
                    uuid.uuid4(), RECEIVER_ID, version, metadata["organization_id"],
                    metadata["intent_id"], metadata["claim_revision_id"],
                    metadata["delivery_key"], metadata["attempt_id"], receipt_id,
                    metadata["envelope_digest"], content_length, body, observed_at,
                ))
            self._respond(409, {"status": "rejected", "reason": "test_rejection"})
            return
        with self._connection() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (metadata["attempt_id"],))
            cursor.execute(sql.SQL("""
                SELECT 1 FROM {}.rejected_invocation
                WHERE receiver_id=%s AND receiver_version=%s
                  AND organization_id=%s AND attempt_id=%s
            """).format(sql.Identifier(self.schema)), (
                RECEIVER_ID, version, metadata["organization_id"], metadata["attempt_id"],
            ))
            if cursor.fetchone():
                self._respond(409, {"status": "unknown"})
                return
            if version == "v1":
                cursor.execute(sql.SQL("""
                    INSERT INTO {}.accepted_receipt
                      (id,receiver_id,receiver_version,organization_id,intent_id,
                       claim_revision_id,delivery_key,attempt_id,receipt_id,envelope_digest,
                       byte_length,received_bytes,observed_at,evidence_mode)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                    RETURNING intent_id,claim_revision_id,attempt_id,receipt_id,envelope_digest,
                              byte_length,received_bytes
                """).format(sql.Identifier(self.schema)), (
                    uuid.uuid4(), RECEIVER_ID, version, metadata["organization_id"],
                    metadata["intent_id"], metadata["claim_revision_id"],
                    metadata["delivery_key"], metadata["attempt_id"], receipt_id,
                    metadata["envelope_digest"], content_length, body, observed_at,
                    test_mode if test_mode in {"wrong_target_evidence", "corrupt_evidence"} else "",
                ))
                stored = cursor.fetchone()
                if stored is None:
                    cursor.execute(sql.SQL("""
                        SELECT intent_id,claim_revision_id,attempt_id,receipt_id,envelope_digest,
                               byte_length,received_bytes
                        FROM {}.accepted_receipt
                        WHERE receiver_id=%s AND receiver_version=%s
                          AND organization_id=%s AND delivery_key=%s
                    """).format(sql.Identifier(self.schema)), (
                        RECEIVER_ID, version, metadata["organization_id"], metadata["delivery_key"],
                    ))
                    stored = cursor.fetchone()
                if stored:
                    exact = (
                        str(stored[0]) == metadata["intent_id"]
                        and str(stored[1]) == metadata["claim_revision_id"]
                        and stored[4] == metadata["envelope_digest"]
                        and stored[5] == content_length and bytes(stored[6]) == body
                    )
                    if not exact:
                        self._respond(409, {"status": "rejected", "reason": "delivery_key_conflict"})
                        return
                    receipt_id = stored[3]
            else:
                cursor.execute(sql.SQL("""
                    INSERT INTO {}.accepted_receipt
                      (id,receiver_id,receiver_version,organization_id,intent_id,
                       claim_revision_id,delivery_key,attempt_id,receipt_id,envelope_digest,
                       byte_length,received_bytes,observed_at,evidence_mode)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """).format(sql.Identifier(self.schema)), (
                    uuid.uuid4(), RECEIVER_ID, version, metadata["organization_id"],
                    metadata["intent_id"], metadata["claim_revision_id"],
                    metadata["delivery_key"], metadata["attempt_id"], receipt_id,
                    metadata["envelope_digest"], content_length, body, observed_at,
                    test_mode if test_mode in {"wrong_target_evidence", "corrupt_evidence"} else "",
                ))
        if test_mode == "commit_acceptance_then_drop_response":
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return
        if test_mode == "delay_before_response":
            time.sleep(float(os.environ.get("MEDICAFE_RECEIVER_TEST_DELAY", "1.0")))
        self._respond(202, {"status": "accepted"})

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health" and not parsed.query:
            self._respond(200, {"status": "ready"})
            return
        version = self._version()
        parts = parsed.path.strip("/").split("/")
        if version is None or len(parts) != 4 or parts[1] != "receipts":
            self._respond(404, {"status": "not_observed"})
            return
        try:
            organization_id = str(uuid.UUID(parts[2]))
            delivery_key = str(uuid.UUID(parts[3]))
            attempt_id = str(uuid.UUID(parse_qs(parsed.query).get("attempt_id", [""])[0]))
        except (ValueError, AttributeError):
            self._respond(400, {"status": "invalid_lookup"})
            return
        if (
            self.headers.get("X-Synthetic-Receiver") != RECEIVER_ID
            or self.headers.get("X-Synthetic-Receiver-Version") != version
        ):
            self._respond(400, {"status": "invalid_lookup"})
            return
        with self._connection() as conn, conn.cursor() as cursor:
            cursor.execute(sql.SQL("""
                SELECT intent_id,claim_revision_id,delivery_key,attempt_id,receipt_id,
                       envelope_digest,byte_length,received_bytes,observed_at,evidence_mode
                FROM {}.accepted_receipt
                WHERE receiver_id=%s AND receiver_version=%s
                  AND organization_id=%s AND delivery_key=%s
                ORDER BY observed_at,id LIMIT 1
            """).format(sql.Identifier(self.schema)), (
                RECEIVER_ID, version, organization_id, delivery_key,
            ))
            accepted = cursor.fetchone()
            if accepted:
                intent_id = str(accepted[0])
                digest = accepted[5]
                received = bytes(accepted[7])
                if accepted[9] == "wrong_target_evidence":
                    intent_id = str(uuid.uuid4())
                elif accepted[9] == "corrupt_evidence":
                    received = received + b"!"
                self._respond(200, {
                    "state": "accepted", "receiver_id": RECEIVER_ID,
                    "receiver_version": version, "organization_id": organization_id,
                    "intent_id": intent_id, "claim_revision_id": str(accepted[1]),
                    "delivery_key": str(accepted[2]), "reported_attempt_id": str(accepted[3]),
                    "receipt_id": accepted[4], "envelope_digest": digest,
                    "byte_length": accepted[6],
                    "received_bytes": base64.b64encode(received).decode("ascii"),
                    "no_acceptance_guaranteed": False,
                    "observed_at": accepted[8].isoformat(),
                })
                return
            cursor.execute(sql.SQL("""
                SELECT intent_id,claim_revision_id,delivery_key,attempt_id,receipt_id,
                       envelope_digest,byte_length,attempted_bytes,observed_at
                FROM {}.rejected_invocation
                WHERE receiver_id=%s AND receiver_version=%s
                  AND organization_id=%s AND delivery_key=%s AND attempt_id=%s
                ORDER BY observed_at,id LIMIT 1
            """).format(sql.Identifier(self.schema)), (
                RECEIVER_ID, version, organization_id, delivery_key, attempt_id,
            ))
            rejected = cursor.fetchone()
        if not rejected:
            self._respond(404, {"status": "not_observed"})
            return
        self._respond(200, {
            "state": "rejected", "receiver_id": RECEIVER_ID,
            "receiver_version": version, "organization_id": organization_id,
            "intent_id": str(rejected[0]), "claim_revision_id": str(rejected[1]),
            "delivery_key": str(rejected[2]), "reported_attempt_id": str(rejected[3]),
            "receipt_id": rejected[4], "envelope_digest": rejected[5],
            "byte_length": rejected[6],
            "received_bytes": base64.b64encode(bytes(rejected[7])).decode("ascii"),
            "no_acceptance_guaranteed": True, "observed_at": rejected[8].isoformat(),
        })


def serve_receiver(*, host, port, schema):
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("synthetic receiver must bind to loopback")
    initialize_ledger(schema)
    server = ThreadingHTTPServer((host, port), ReceiverHandler)
    server.receiver_schema = schema
    server.serve_forever()
