from __future__ import annotations

import os
import json
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import psycopg
from django.conf import settings
from django.db import connection
from psycopg import sql


def free_loopback_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def postgres_env():
    config = connection.settings_dict
    values = {
        "POSTGRES_DB": str(config["NAME"]),
        "POSTGRES_USER": str(config["USER"]),
        "POSTGRES_PASSWORD": str(config["PASSWORD"]),
        "POSTGRES_HOST": str(config["HOST"]),
        "POSTGRES_PORT": str(config["PORT"]),
        "POSTGRES_CONNECT_TIMEOUT": "3",
    }
    values.update({
        "MEDICAFE_ARCHIVE_DB_NAME": values["POSTGRES_DB"],
        "MEDICAFE_ARCHIVE_DB_USER": values["POSTGRES_USER"],
        "MEDICAFE_ARCHIVE_DB_PASSWORD": values["POSTGRES_PASSWORD"],
        "MEDICAFE_ARCHIVE_DB_HOST": values["POSTGRES_HOST"],
        "MEDICAFE_ARCHIVE_DB_PORT": values["POSTGRES_PORT"],
    })
    return values


def postgres_kwargs():
    config = connection.settings_dict
    return {
        "dbname": config["NAME"], "user": config["USER"],
        "password": config["PASSWORD"], "host": config["HOST"],
        "port": config["PORT"], "connect_timeout": 3,
    }


class ArchiveProcess:
    def __init__(self):
        self.port = free_loopback_port()
        self.schema = f"f4_archive_{uuid.uuid4().hex}"
        self.process = None

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.port}/v1"

    def environment(self):
        env = os.environ.copy()
        env.update(postgres_env())
        env["MEDICAFE_ARCHIVE_SCHEMA"] = self.schema
        env["MEDICAFE_SYNTHETIC_ARCHIVE_URL"] = self.endpoint
        env["MEDICAFE_SYNTHETIC_ARCHIVE_TIMEOUT"] = "1.0"
        env["PYTHONPATH"] = str(Path(settings.BASE_DIR) / "src")
        env["DJANGO_SETTINGS_MODULE"] = "medicafe_v1.settings"
        return env

    def start(self):
        if self.process is not None:
            raise RuntimeError("archive process already started")
        self.process = subprocess.Popen(
            [sys.executable, str(Path(settings.BASE_DIR) / "manage.py"),
             "run_synthetic_archive", "--host", "127.0.0.1",
             "--port", str(self.port), "--schema", self.schema],
            cwd=settings.BASE_DIR, env=self.environment(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"archive target exited during startup: {self.process.returncode}"
                )
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/health", timeout=0.25,
                ) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(0.05)
        self.stop()
        raise RuntimeError("archive target startup timeout")

    def stop(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None

    def drop_schema(self):
        if self.process is not None:
            raise RuntimeError("stop archive target before dropping schema")
        with psycopg.connect(**postgres_kwargs()) as conn, conn.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(self.schema)
                )
            )

    def run_worker(self):
        return subprocess.run(
            [sys.executable, str(Path(settings.BASE_DIR) / "manage.py"),
             "run_archive_worker", "--once", "--worker-id", "process-f4-worker",
             "--lease-seconds", "5"],
            cwd=settings.BASE_DIR, env=self.environment(), capture_output=True,
            text=True, timeout=15, check=False,
        )

    def query_outcome_state(self, *, organization_id, user_id, claim_revision_id):
        result = subprocess.run(
            [sys.executable, "-m", "tests.f4.state_process",
             str(organization_id), str(user_id), str(claim_revision_id)],
            cwd=settings.BASE_DIR, env=self.environment(), capture_output=True,
            text=True, timeout=10, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return json.loads(result.stdout.strip()), result
