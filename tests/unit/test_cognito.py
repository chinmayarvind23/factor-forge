"""Real RSA signatures test the boundary between untrusted tokens and stored ownership."""

import json
import time
from collections.abc import Callable
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from factorforge.auth.cognito import CognitoVerifier
from factorforge.domain.errors import ResearchError

ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool"


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    """Ephemeral test keys avoid embedding a reusable credential in the repository."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks(key: rsa.RSAPrivateKey, kid: str = "key-1") -> bytes:
    """Represent an actual public key in the same format as the provider endpoint."""
    item = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    item.update(kid=kid, use="sig", alg="RS256")
    return json.dumps({"keys": [item]}).encode()


def token(key: rsa.RSAPrivateKey, **changes: Any) -> str:
    """Alter signed claims so failure cases exercise claim validation after cryptography."""
    now = int(time.time())
    claims = dict(
        iss=ISSUER,
        sub="user-1",
        exp=now + 300,
        iat=now,
        token_use="access",
        client_id="client123",
        scope="factorforge/read factorforge/create",
    )
    claims.update(changes)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "key-1"})


def verifier(fetch: Callable[[], bytes]) -> CognitoVerifier:
    """Transport injection changes bytes, not the cryptographic verification path."""
    return CognitoVerifier(
        region="us-east-1", pool_id="us-east-1_TestPool", client_id="client123", fetch_jwks=fetch
    )


def test_verified_identity_and_scopes(signing_key: rsa.RSAPrivateKey) -> None:
    """Only configured OAuth scopes grant the two owner-scoped API capabilities."""
    auth = verifier(lambda: jwks(signing_key))
    principal = auth.verify(token(signing_key))
    assert (principal.issuer, principal.subject) == (ISSUER, "user-1")
    principal.require("create_run")
    principal.require("read_own_run")
    with pytest.raises(ResearchError, match="not permitted"):
        auth.verify(token(signing_key, scope="admin")).require("create_run")


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://attacker.invalid"},
        {"client_id": "wrong"},
        {"token_use": "id"},
        {"exp": 0},
        {"exp": None},
        {"iat": 9999999999},
        {"nbf": 9999999999},
        {"sub": ""},
        {"sub": 123},
        {"scope": ["factorforge/create"]},
        {"aud": "unconfigured"},
        {"exp": "9999999999"},
        {"iat": True},
    ],
)
def test_invalid_signed_claims(signing_key: rsa.RSAPrivateKey, changes: dict[str, Any]) -> None:
    """A valid signature cannot make an inappropriate or malformed credential acceptable."""
    with pytest.raises(ResearchError) as failure:
        verifier(lambda: jwks(signing_key)).verify(token(signing_key, **changes))
    assert failure.value.status_code == 401


def test_forged_signature(signing_key: rsa.RSAPrivateKey) -> None:
    """A correctly shaped token signed by a different key cannot establish identity."""
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ResearchError):
        verifier(lambda: jwks(signing_key)).verify(token(other))


def test_missing_expiry(signing_key: rsa.RSAPrivateKey) -> None:
    """Required claims are presence constraints as well as value constraints."""
    claims = jwt.decode(token(signing_key), options={"verify_signature": False})
    del claims["exp"]
    missing = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "key-1"})
    with pytest.raises(ResearchError):
        verifier(lambda: jwks(signing_key)).verify(missing)


@pytest.mark.parametrize("raw", ["", "abc", "x" * 16385])
def test_malformed_before_network(raw: str) -> None:
    """Cheap rejection prevents malformed tokens from consuming provider requests."""

    def forbidden_fetch() -> bytes:
        """Network should never be reached for structurally invalid credentials."""
        raise AssertionError("unexpected provider call")

    with pytest.raises(ResearchError):
        verifier(forbidden_fetch).verify(raw)


def test_provider_unavailable_is_safe(signing_key: rsa.RSAPrivateKey) -> None:
    """Dependency failures remain distinguishable without exposing connection diagnostics."""

    def fail() -> bytes:
        """An injected network error contains a sentinel that must not reach the caller."""
        raise OSError("private-network-sentinel")

    with pytest.raises(ResearchError) as failure:
        verifier(fail).verify(token(signing_key))
    assert failure.value.status_code == 503
    assert "sentinel" not in str(failure.value)


def test_unknown_key_refresh_is_bounded(signing_key: rsa.RSAPrivateKey) -> None:
    """An attacker varying key IDs cannot turn verification into unlimited network calls."""
    calls = 0

    def fetch() -> bytes:
        """Count actual refreshes across repeated unknown-key requests."""
        nonlocal calls
        calls += 1
        return jwks(signing_key)

    auth = verifier(fetch)
    auth.verify(token(signing_key))
    claims = jwt.decode(token(signing_key), options={"verify_signature": False})
    for i in range(5):
        unknown = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": f"other-{i}"})
        with pytest.raises(ResearchError):
            auth.verify(unknown)
    assert calls == 1
