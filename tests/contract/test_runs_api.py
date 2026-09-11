"""Exercise the local HTTP boundary before adding research or durable workers."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from factorforge.api.app import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Opt into local identity explicitly, using the same loopback boundary as the browser."""
    with TestClient(
        create_app(local_mode=True), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
    ) as connection:
        yield connection


def test_create_and_read_transition(client: TestClient) -> None:
    """A run can be tracked independently of the submission HTTP request."""
    response = client.post(
        "/api/v1/research-runs",
        json={"idea": "  Investigate   momentum across US equities  "},
        headers={"Idempotency-Key": "research-1"},
    )
    assert response.status_code == 202
    payload = response.json()
    assert UUID(payload["run_id"])
    assert payload["status"] == "RECEIVED"
    record = client.get(f"/api/v1/research-runs/{payload['run_id']}").json()
    assert record["status"] == "BRIEF_NORMALIZED"
    assert record["brief"] == "Investigate momentum across US equities"
    assert [event["status"] for event in record["events"]] == ["RECEIVED", "BRIEF_NORMALIZED"]
    assert record["mode"] == "local"


def test_retries_are_idempotent_and_payload_conflict_is_explicit(client: TestClient) -> None:
    """Network retries must not create duplicate runs or silently reuse a different brief."""
    headers = {"Idempotency-Key": "retry-key"}
    body = {"idea": "Investigate momentum"}
    first = client.post("/api/v1/research-runs", json=body, headers=headers)
    second = client.post("/api/v1/research-runs", json=body, headers=headers)
    assert first.json() == second.json()
    conflict = client.post(
        "/api/v1/research-runs", json={"idea": "Investigate value"}, headers=headers
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize(
    "body",
    [
        {"idea": "  "},
        {"idea": "x" * 4001},
        {"idea": "valid idea", "max_llm_cost_usd": "NaN"},
        {"idea": "valid idea", "max_llm_cost_usd": "-1"},
        {"idea": "valid idea", "max_experiments": 0},
        {"idea": "valid idea", "max_wall_time_s": 0},
        {"idea": "valid idea", "owner_id": "somebody-else"},
    ],
)
def test_invalid_input_cannot_create_runs(client: TestClient, body: dict[str, object]) -> None:
    """Reject invalid budgets and identity injection before creating any local state."""
    response = client.post(
        "/api/v1/research-runs", json=body, headers={"Idempotency-Key": "bad-input"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INPUT_INVALID"


def test_idempotency_key_required_and_unknown_run(client: TestClient) -> None:
    """Malformed requests and unknown IDs retain a typed error envelope."""
    assert client.post("/api/v1/research-runs", json={"idea": "momentum"}).status_code == 422
    response = client.get("/api/v1/research-runs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RUN_NOT_FOUND"
    assert UUID(response.json()["error"]["trace_id"])


def test_unconfigured_service_is_not_ready() -> None:
    """Absence of production identity cannot silently enable local write access."""
    with TestClient(create_app(local_mode=False), base_url="http://127.0.0.1") as connection:
        assert connection.get("/health").status_code == 200
        assert connection.get("/ready").status_code == 503
        response = connection.post(
            "/api/v1/research-runs",
            json={"idea": "Investigate momentum"},
            headers={"Idempotency-Key": "closed"},
        )
        assert response.status_code == 503


def test_local_origin_and_client_gates(client: TestClient) -> None:
    """A browser on an unrelated site and a remote client cannot use the development identity."""
    assert client.get("/ready").status_code == 200
    response = client.post(
        "/api/v1/research-runs",
        json={"idea": "Investigate momentum"},
        headers={"Idempotency-Key": "hostile", "Origin": "https://untrusted.example"},
    )
    assert response.status_code == 403
    assert response.headers["x-trace-id"] == response.json()["error"]["trace_id"]
    with TestClient(
        create_app(local_mode=True), base_url="http://127.0.0.1", client=("192.0.2.1", 50000)
    ) as remote:
        assert (
            remote.get("/api/v1/research-runs/00000000-0000-0000-0000-000000000000").status_code
            == 403
        )


def test_concurrent_retry_has_one_run(client: TestClient) -> None:
    """An atomic create gate handles retries that arrive before normalization finishes."""

    def submit(_: int) -> str:
        """Use an identical request to represent overlapping transport retries."""
        return str(
            client.post(
                "/api/v1/research-runs",
                json={"idea": "Investigate momentum"},
                headers={"Idempotency-Key": "concurrent"},
            ).json()["run_id"]
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        identifiers = list(pool.map(submit, range(8)))
    assert len(set(identifiers)) == 1


def test_oversized_request_rejected_before_allocating_state(client: TestClient) -> None:
    """A body with whitespace or chunked transport cannot evade the raw byte limit."""
    headers = {
        "Idempotency-Key": "oversized",
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3001",
    }
    response = client.post(
        "/api/v1/research-runs",
        content=iter([b'{"idea":"', b" " * 20000, b'momentum"}']),
        headers=headers,
    )
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3001"
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert (
        client.post(
            "/api/v1/research-runs", json={"idea": "Investigate value"}, headers=headers
        ).status_code
        == 202
    )


def test_untrusted_host_cannot_use_local_identity(client: TestClient) -> None:
    """Host validation prevents a DNS-rebound origin from borrowing loopback identity."""
    response = client.post(
        "/api/v1/research-runs",
        json={"idea": "Investigate value"},
        headers={"Host": "untrusted.example", "Idempotency-Key": "rebound"},
    )
    assert response.status_code == 403
