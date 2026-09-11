"""Restart an owned real Uvicorn process against an explicitly isolated test database."""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import httpx
import pytest
from psycopg.conninfo import conninfo_to_dict


def available_port() -> int:
    """Choose a loopback port without touching existing servers."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def running_api(dsn: str, port: int) -> Iterator[str]:
    """Terminate only the owned child and keep raw driver diagnostics out of test output."""
    environment = dict(
        os.environ, FACTORFORGE_MODE="local", FACTORFORGE_STORAGE="postgres", RDS_DSN=dsn
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "factorforge.api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-proxy-headers",
            "--log-level",
            "warning",
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 25
        with httpx.Client(timeout=2, trust_env=False) as client:
            while time.monotonic() < deadline:
                assert process.poll() is None, "Owned API process exited during startup"
                try:
                    if client.get(url + "/ready").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("Owned API did not become ready against the isolated test database")
        yield url
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_real_api_restart_preserves_receipt_and_recovers_run() -> None:
    """A real HTTP receipt and persisted graph survive server restart without duplicate events."""
    dsn = os.environ.get("FACTORFORGE_TEST_DSN")
    if not dsn:
        pytest.skip("Set FACTORFORGE_TEST_DSN to an isolated PostgreSQL test database")
    assert str(conninfo_to_dict(dsn).get("dbname", "")).startswith("factorforge_test_"), (
        "API restart checks require a dedicated FactorForge test database"
    )
    key = "api-restart-" + uuid4().hex
    headers = {"Idempotency-Key": key}
    body = {"idea": "Investigate   momentum after an API restart"}
    port = available_port()
    with httpx.Client(timeout=5, trust_env=False) as client:
        with running_api(dsn, port) as url:
            created = client.post(url + "/api/v1/research-runs", json=body, headers=headers)
            assert created.status_code == 202
            receipt = created.json()
            assert receipt["status"] == "RECEIVED"
        with running_api(dsn, port) as url:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                response = client.get(url + "/api/v1/research-runs/" + receipt["run_id"])
                assert response.status_code == 200
                record = response.json()
                if record["status"] == "BRIEF_NORMALIZED":
                    break
                time.sleep(0.1)
            else:
                pytest.fail("Restarted API did not recover the accepted run")
            assert record["storage"] == "postgres"
            assert record["brief"] == "Investigate momentum after an API restart"
            assert [event["status"] for event in record["events"]] == [
                "RECEIVED",
                "BRIEF_NORMALIZED",
            ]
            replay = client.post(url + "/api/v1/research-runs", json=body, headers=headers)
            assert replay.status_code == 202
            assert replay.json() == receipt
            after = client.get(url + "/api/v1/research-runs/" + receipt["run_id"]).json()
            assert after["events"] == record["events"]
