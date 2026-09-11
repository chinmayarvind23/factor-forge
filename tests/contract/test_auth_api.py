"""HTTP credentials are cryptographically verified before capability and owner checks."""

import json
import time
from collections.abc import Iterator

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from factorforge.api.app import create_app
from factorforge.api.settings import Settings
from factorforge.auth.cognito import CognitoVerifier
from factorforge.domain.errors import ResearchError
from factorforge.orchestration.local_runs import LocalRunStore
from factorforge.orchestration.postgres_runs import PostgresRunStore


@pytest.fixture
def auth_client() -> Iterator[tuple[TestClient, rsa.RSAPrivateKey]]:
    """Replace storage in this HTTP unit boundary, retaining the actual RSA verifier."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    public.update(kid="api-key", use="sig", alg="RS256")
    verifier = CognitoVerifier(
        region="us-east-1",
        pool_id="us-east-1_TestPool",
        client_id="client123",
        fetch_jwks=lambda: json.dumps({"keys": [public]}).encode(),
    )
    settings = Settings(
        mode="cognito",
        storage="postgres",
        dsn="unused-test-sentinel",
        region="us-east-1",
        pool_id="us-east-1_TestPool",
        client_id="client123",
    )
    with TestClient(
        create_app(settings=settings, store=LocalRunStore(), verifier=verifier),
        base_url="https://api.example.test",
    ) as client:
        yield client, key


def credential(
    key: rsa.RSAPrivateKey, subject: str, scope: str = "factorforge/create factorforge/read"
) -> str:
    """Construct a valid test access token whose identity differs only in signed claims."""
    now = int(time.time())
    return "Bearer " + jwt.encode(
        dict(
            iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool",
            sub=subject,
            client_id="client123",
            token_use="access",
            iat=now,
            exp=now + 300,
            scope=scope,
        ),
        key,
        algorithm="RS256",
        headers={"kid": "api-key"},
    )


def test_auth_and_owner_isolation(auth_client: tuple[TestClient, rsa.RSAPrivateKey]) -> None:
    """Users cannot inherit local identity or read another user's accepted receipt."""
    client, key = auth_client
    body = {"idea": "Investigate momentum"}
    assert client.post("/api/v1/research-runs", json=body).status_code == 401
    denied = client.post(
        "/api/v1/research-runs",
        json=body,
        headers={
            "Authorization": credential(key, "a", "factorforge/read"),
            "Idempotency-Key": "same",
        },
    )
    assert denied.status_code == 403
    first = client.post(
        "/api/v1/research-runs",
        json=body,
        headers={"Authorization": credential(key, "a"), "Idempotency-Key": "same"},
    )
    assert first.status_code == 202
    run_url = "/api/v1/research-runs/" + first.json()["run_id"]
    assert client.get(run_url, headers={"Authorization": credential(key, "b")}).status_code == 404
    own = client.get(run_url, headers={"Authorization": credential(key, "a")})
    assert own.status_code == 200
    assert own.json()["mode"] == "cognito"


def test_duplicate_or_malformed_headers(auth_client: tuple[TestClient, rsa.RSAPrivateKey]) -> None:
    """Ambiguous credentials must be rejected before parsing the body or allocating state."""
    client, key = auth_client
    url = "/api/v1/research-runs/00000000-0000-0000-0000-000000000000"
    for headers in [
        [("Authorization", credential(key, "a")), ("Authorization", credential(key, "b"))],
        [("Authorization", "Basic abc")],
        [("Authorization", "Bearer " + "x" * 16385)],
    ]:
        assert client.get(url, headers=headers).status_code == 401
    response = client.options(
        url,
        headers={
            "Origin": "http://127.0.0.1:3001",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200


def test_storage_outage_never_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed durable startup keeps health responsive but cannot accept ephemeral receipts."""

    class UnavailableStore(PostgresRunStore):
        """Simulate a driver startup failure without connecting to any configured database."""

        def __init__(self, dsn: str) -> None:
            """Only the public failure crosses the injected infrastructure boundary."""
            raise ResearchError("DEPENDENCY_UNAVAILABLE", "Storage unavailable.", 503)

    monkeypatch.setattr("factorforge.api.app.PostgresRunStore", UnavailableStore)
    config = Settings(mode="local", storage="postgres", dsn="secret-sentinel")
    with TestClient(
        create_app(settings=config), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
    ) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        response = client.post(
            "/api/v1/research-runs",
            json={"idea": "Investigate value"},
            headers={"Idempotency-Key": "outage"},
        )
        assert response.status_code == 503
        assert "sentinel" not in response.text
