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
        "MEDICAFE_RECEIVER_DB_NAME": values["POSTGRES_DB"],
        "MEDICAFE_RECEIVER_DB_USER": values["POSTGRES_USER"],
        "MEDICAFE_RECEIVER_DB_PASSWORD": values["POSTGRES_PASSWORD"],
        "MEDICAFE_RECEIVER_DB_HOST": values["POSTGRES_HOST"],
        "MEDICAFE_RECEIVER_DB_PORT": values["POSTGRES_PORT"],
    })
    return values


def postgres_kwargs():
    config = connection.settings_dict
    return {
        "dbname": config["NAME"], "user": config["USER"],
        "password": config["PASSWORD"], "host": config["HOST"],
        "port": config["PORT"], "connect_timeout": 3,
    }


class ReceiverProcess:
    def __init__(self):
        self.port = free_loopback_port()
        self.schema = f"f3_receiver_{uuid.uuid4().hex}"
        self.process = None

    @property
    def endpoints(self):
        base = f"http://127.0.0.1:{self.port}"
        return {"v1": f"{base}/v1", "v2": f"{base}/v2"}

    def start(self):
        if self.process is not None:
            raise RuntimeError("receiver process already started")
        env = os.environ.copy()
        env.update(postgres_env())
        env["MEDICAFE_RECEIVER_SCHEMA"] = self.schema
        self.process = subprocess.Popen(
            [sys.executable, str(Path(settings.BASE_DIR) / "manage.py"),
             "run_synthetic_receiver", "--host", "127.0.0.1",
             "--port", str(self.port), "--schema", self.schema],
            cwd=settings.BASE_DIR, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"receiver exited during startup: {self.process.returncode}")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/health", timeout=0.25
                ) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(0.05)
        self.stop()
        raise RuntimeError("receiver startup timeout")

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
            raise RuntimeError("stop receiver before dropping its schema")
        with psycopg.connect(**postgres_kwargs()) as conn, conn.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    def worker_environment(self):
        env = os.environ.copy()
        env.update(postgres_env())
        env["MEDICAFE_SYNTHETIC_RECEIVER_V1_URL"] = self.endpoints["v1"]
        env["MEDICAFE_SYNTHETIC_RECEIVER_V2_URL"] = self.endpoints["v2"]
        env["MEDICAFE_SYNTHETIC_RECEIVER_TIMEOUT"] = "1.0"
        env["PYTHONPATH"] = str(Path(settings.BASE_DIR) / "src")
        env["DJANGO_SETTINGS_MODULE"] = "medicafe_v1.settings"
        return env

    def run_worker(self):
        return subprocess.run(
            [sys.executable, str(Path(settings.BASE_DIR) / "manage.py"),
             "run_delivery_worker", "--once", "--worker-id", "process-test",
             "--lease-seconds", "5"],
            cwd=settings.BASE_DIR, env=self.worker_environment(),
            capture_output=True, text=True, timeout=15, check=False,
        )

    def run_test_worker(self, *, test_mode):
        return subprocess.run(
            [sys.executable, "-m", "tests.f3.worker_process",
             "--worker-id", f"process-test-{uuid.uuid4()}",
             "--lease-seconds", "5", "--test-mode", test_mode],
            cwd=settings.BASE_DIR, env=self.worker_environment(),
            capture_output=True, text=True, timeout=15, check=False,
        )

    def query_state(self, intent_id):
        result = subprocess.run(
            [sys.executable, "-m", "tests.f3.state_process", str(intent_id)],
            cwd=settings.BASE_DIR, env=self.worker_environment(),
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return json.loads(result.stdout.strip())
