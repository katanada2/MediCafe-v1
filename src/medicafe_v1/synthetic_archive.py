from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import psycopg
from psycopg import sql


SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
MAX_REQUEST = ((2 * 1024 * 1024 + 2) // 3) * 4 + 16384


class ArchiveLedger:
    def __init__(self, schema):
        if not SCHEMA_RE.fullmatch(schema):
            raise ValueError("archive schema must be a simple PostgreSQL identifier")
        self.schema = schema
        self.params = {
            "dbname": os.environ.get("MEDICAFE_ARCHIVE_DB_NAME", os.environ.get("POSTGRES_DB", "medicafe_v1")),
            "user": os.environ.get("MEDICAFE_ARCHIVE_DB_USER", os.environ.get("POSTGRES_USER", "medicafe")),
            "password": os.environ.get("MEDICAFE_ARCHIVE_DB_PASSWORD", os.environ.get("POSTGRES_PASSWORD", "")),
            "host": os.environ.get("MEDICAFE_ARCHIVE_DB_HOST", os.environ.get("POSTGRES_HOST", "127.0.0.1")),
            "port": os.environ.get("MEDICAFE_ARCHIVE_DB_PORT", os.environ.get("POSTGRES_PORT", "5432")),
            "connect_timeout": int(os.environ.get("POSTGRES_CONNECT_TIMEOUT", "3")),
        }
        self.ensure_schema()

    def connect(self):
        connection = psycopg.connect(**self.params)
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(self.schema)))
        return connection

    def ensure_schema(self):
        with psycopg.connect(**self.params) as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            cursor.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(self.schema)))
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS archive_projection (
                  organization_id uuid NOT NULL,
                  encounter_id uuid NOT NULL,
                  projection_id uuid PRIMARY KEY,
                  projection_version integer NOT NULL,
                  attempt_id uuid NOT NULL,
                  projection_digest char(64) NOT NULL,
                  byte_length integer NOT NULL,
                  received_bytes bytea NOT NULL,
                  target_receipt_id varchar(100) NOT NULL UNIQUE,
                  observed_at timestamptz NOT NULL,
                  UNIQUE (organization_id,encounter_id,projection_version)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS archive_head (
                  organization_id uuid NOT NULL,
                  encounter_id uuid NOT NULL,
                  projection_id uuid NOT NULL REFERENCES archive_projection(projection_id),
                  projection_version integer NOT NULL,
                  PRIMARY KEY (organization_id,encounter_id)
                )
            """)

    def store(self, value):
        payload = base64.b64decode(value["payload_b64"], validate=True)
        if (
            len(payload) != value["byte_length"]
            or hashlib.sha256(payload).hexdigest() != value["projection_digest"]
            or len(payload) > 2 * 1024 * 1024
        ):
            return "conflict"
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT projection_digest,received_bytes,target_receipt_id FROM archive_projection WHERE projection_id=%s FOR UPDATE",
                [value["projection_id"]],
            )
            existing = cursor.fetchone()
            if existing:
                if existing[0] == value["projection_digest"] and bytes(existing[1]) == payload:
                    return "replayed"
                return "conflict"
            cursor.execute(
                "SELECT projection_version FROM archive_head WHERE organization_id=%s AND encounter_id=%s FOR UPDATE",
                [value["organization_id"], value["encounter_id"]],
            )
            head = cursor.fetchone()
            receipt = f"archive-{value['projection_id']}"
            observed_at = datetime.now(timezone.utc)
            try:
                cursor.execute("""
                    INSERT INTO archive_projection
                      (organization_id,encounter_id,projection_id,projection_version,
                       attempt_id,projection_digest,byte_length,received_bytes,
                       target_receipt_id,observed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, [
                    value["organization_id"], value["encounter_id"], value["projection_id"],
                    value["projection_version"], value["attempt_id"],
                    value["projection_digest"], value["byte_length"], payload,
                    receipt, observed_at,
                ])
            except psycopg.errors.UniqueViolation:
                connection.rollback()
                return "conflict"
            if head is None:
                cursor.execute(
                    "INSERT INTO archive_head (organization_id,encounter_id,projection_id,projection_version) VALUES (%s,%s,%s,%s)",
                    [value["organization_id"], value["encounter_id"], value["projection_id"], value["projection_version"]],
                )
            elif value["projection_version"] > head[0]:
                cursor.execute(
                    "UPDATE archive_head SET projection_id=%s,projection_version=%s WHERE organization_id=%s AND encounter_id=%s",
                    [value["projection_id"], value["projection_version"], value["organization_id"], value["encounter_id"]],
                )
        return "stored"

    def read(self, organization_id, projection_id):
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("""
                SELECT organization_id,encounter_id,projection_id,projection_version,
                       attempt_id,projection_digest,byte_length,received_bytes,
                       target_receipt_id,observed_at
                  FROM archive_projection
                 WHERE organization_id=%s AND projection_id=%s
            """, [organization_id, projection_id])
            return cursor.fetchone()


def handler_for(ledger):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format_, *args):
            return

        def _json(self, status, value):
            body = json.dumps(value, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/v1/store":
                self._json(404, {"status": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_REQUEST:
                    raise ValueError
                value = json.loads(self.rfile.read(length).decode("utf-8"))
                required = {
                    "organization_id", "encounter_id", "projection_id",
                    "projection_version", "attempt_id", "projection_digest",
                    "byte_length", "payload_b64",
                }
                if not isinstance(value, dict) or set(value) != required:
                    raise ValueError
                status = ledger.store(value)
            except Exception:
                self._json(400, {"status": "invalid"})
                return
            self._json(409 if status == "conflict" else 200, {"status": status})

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/v1/read":
                self._json(404, {"status": "not_found"})
                return
            query = parse_qs(parsed.query)
            if set(query) != {"organization_id", "projection_id"}:
                self._json(400, {"status": "invalid"})
                return
            row = ledger.read(query["organization_id"][0], query["projection_id"][0])
            if row is None:
                self._json(404, {"status": "not_found"})
                return
            self._json(200, {
                "receiver_id": "synthetic-archive", "receiver_version": "v1",
                "target_receipt_id": row[8], "organization_id": str(row[0]),
                "encounter_id": str(row[1]), "projection_id": str(row[2]),
                "projection_version": row[3], "reported_attempt_id": str(row[4]),
                "projection_digest": row[5], "byte_length": row[6],
                "received_bytes_b64": base64.b64encode(bytes(row[7])).decode("ascii"),
                "observed_at": row[9].isoformat(),
            })

    return Handler


def run_archive_server(*, host, port, schema):
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("synthetic archive must bind loopback")
    server = ThreadingHTTPServer((host, port), handler_for(ArchiveLedger(schema)))
    server.serve_forever()
