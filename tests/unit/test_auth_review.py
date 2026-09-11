"""Independent adversarial checks exercise real signatures and bounded provider behavior."""

import json
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from factorforge.api.settings import Settings
from factorforge.auth.cognito import MAX_JWKS_BYTES, CognitoVerifier
from factorforge.domain.errors import ResearchError

ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Review"


@pytest.fixture(scope="module")
def key() -> rsa.RSAPrivateKey:
    """Generate independent signing material rather than trusting an injected principal."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def encode(key: rsa.RSAPrivateKey, *, kid: str = "first", **claims: Any) -> str:
    """Signed malformed claims must traverse cryptographic verification before rejection."""
    now = int(time.time())
    values = dict(
        iss=ISSUER,
        sub="review-user",
        iat=now,
        exp=now + 600,
        client_id="reviewclient",
        token_use="access",
        scope="factorforge/read",
    )
    values.update(claims)
    return jwt.encode(values, key, algorithm="RS256", headers={"kid": kid})


def document(key: rsa.RSAPrivateKey, *, kid: str = "first", **changes: Any) -> bytes:
    """Represent a provider key while permitting adversarial metadata combinations."""
    entry = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    entry.update(kid=kid, alg="RS256", use="sig", **changes)
    return json.dumps({"keys": [entry]}).encode()


def verifier(**kwargs: Any) -> CognitoVerifier:
    """Only the trusted configuration and transport are injected, never decoded claims."""
    return CognitoVerifier(
        region="us-east-1", pool_id="us-east-1_Review", client_id="reviewclient", **kwargs
    )


@pytest.mark.parametrize(
    "claims", [{"sub": " \t "}, {"exp": float("inf")}, {"iat": float("inf")}, {"nbf": float("inf")}]
)
def test_malformed_signed_values_have_typed_failure(
    key: rsa.RSAPrivateKey, claims: dict[str, Any]
) -> None:
    """Blank identities and numeric overflow must not authenticate or become raw 500s."""
    with pytest.raises(ResearchError) as error:
        verifier(fetch_jwks=lambda: document(key)).verify(encode(key, **claims))
    assert error.value.status_code == 401


@pytest.mark.parametrize("operations", [["encrypt"], ["sign"], "verify", []])
def test_key_operations_must_allow_verification(key: rsa.RSAPrivateKey, operations: object) -> None:
    """An RSA key marked for another operation is not a trusted verification key."""
    with pytest.raises(ResearchError) as error:
        verifier(fetch_jwks=lambda: document(key, key_ops=operations)).verify(encode(key))
    assert error.value.status_code == 503


def test_nested_jwks_cannot_escape_safe_dependency_error(key: rsa.RSAPrivateKey) -> None:
    """A byte-bounded JSON document can still exceed the parser's nesting limit."""
    raw = b'{"keys":' + b"[" * 20000 + b"0" + b"]" * 20000 + b"}"
    with pytest.raises(ResearchError) as error:
        verifier(fetch_jwks=lambda: raw).verify(encode(key))
    assert error.value.status_code == 503


def test_rotation_and_cached_outage_policy(key: rsa.RSAPrivateKey) -> None:
    """Known fresh keys survive outage while stale or newly rotated keys fail closed."""
    now = [0.0]
    calls = [0]
    unavailable = [False]
    kid = ["first"]

    def fetch() -> bytes:
        """Expose provider calls and rotation without replacing the signature verifier."""
        calls[0] += 1
        if unavailable[0]:
            raise OSError("provider-secret-sentinel")
        return document(key, kid=kid[0])

    auth = verifier(fetch_jwks=fetch, clock=lambda: now[0])
    assert auth.verify(encode(key)).subject == "review-user"
    now[0], unavailable[0] = 31, True
    with pytest.raises(ResearchError) as error:
        auth.verify(encode(key, kid="second"))
    assert error.value.status_code == 503
    assert "sentinel" not in str(error.value)
    assert auth.verify(encode(key)).subject == "review-user"
    assert calls[0] == 2
    now[0] = 301
    with pytest.raises(ResearchError) as error:
        auth.verify(encode(key))
    assert error.value.status_code == 503
    now[0], unavailable[0], kid[0] = 332, False, "second"
    assert auth.verify(encode(key, kid="second")).subject == "review-user"
    assert calls[0] == 4


def test_parallel_unknown_keys_share_refresh_budget(key: rsa.RSAPrivateKey) -> None:
    """Concurrent key misses must not multiply requests while the cache lock is held."""
    calls = [0]

    def fetch() -> bytes:
        """Count refreshes under the verifier's own synchronization."""
        calls[0] += 1
        return document(key)

    auth = verifier(fetch_jwks=fetch, clock=lambda: 0)

    def check(index: int) -> None:
        """Each independently signed token requests a distinct unavailable key ID."""
        with pytest.raises(ResearchError) as error:
            auth.verify(encode(key, kid=f"unknown-{index}"))
        assert error.value.status_code == 401

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(check, range(16)))
    assert calls[0] == 1


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "none"},
        {"alg": "HS256"},
        {"jku": "http://127.0.0.1/private"},
        {"x5u": "https://attacker.invalid"},
        {"crit": ["custom"]},
    ],
)
def test_disallowed_headers_never_fetch(key: rsa.RSAPrivateKey, header: dict[str, Any]) -> None:
    """Reject header-controlled algorithms and URLs before any provider request."""
    encoded_header = jwt.utils.base64url_encode(
        json.dumps({"kid": "first", **header}).encode()
    ).decode()
    raw = encoded_header + "." + encode(key).split(".", 1)[1]

    def forbidden() -> bytes:
        """Structural rejection must not spend provider traffic."""
        raise AssertionError("Unexpected provider call")

    with pytest.raises(ResearchError) as error:
        verifier(fetch_jwks=forbidden).verify(raw)
    assert error.value.status_code == 401


def test_download_honors_identity_encoding_before_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject unexpected compressed bodies before HTTPX expands them into memory."""

    class ForbiddenBody(httpx.SyncByteStream):
        """Any body iteration means encoding policy was checked too late."""

        def __iter__(self) -> Iterator[bytes]:
            """The response headers are sufficient to reject this transport."""
            raise AssertionError("Compressed body was consumed")
            yield b""

    original_client = httpx.Client

    def response(request: httpx.Request) -> httpx.Response:
        """A server can ignore Accept-Encoding, so the client must verify the response."""
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=ForbiddenBody())

    def client(**kwargs: Any) -> httpx.Client:
        """Keep the actual HTTPX streaming path and substitute only the network transport."""
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        assert kwargs["timeout"] == 3
        return original_client(transport=httpx.MockTransport(response), **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    with pytest.raises(ValueError):
        verifier()._download()


def test_oversized_provider_body_is_bounded(key: rsa.RSAPrivateKey) -> None:
    """Transport injection cannot bypass the second response size check."""
    with pytest.raises(ResearchError) as error:
        verifier(fetch_jwks=lambda: b" " * (MAX_JWKS_BYTES + 1)).verify(encode(key))
    assert error.value.status_code == 503


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.com:bad",
        "https://example.com:65536",
        "https://example.com:0",
        " https://example.com",
        "https://exam\nple.com",
    ],
)
def test_invalid_origin_is_rejected_at_configuration(origin: str) -> None:
    """Malformed origins must fail startup rather than silently deny every real browser."""
    with pytest.raises(ValueError):
        Settings(allowed_origin=origin)


def test_configured_audience_is_required_and_exact(key: rsa.RSAPrivateKey) -> None:
    """Audience support must not weaken access-token client or token_use verification."""
    auth = verifier(fetch_jwks=lambda: document(key), audience="research-api")
    assert auth.verify(encode(key, aud="research-api")).subject == "review-user"
    for changes in ({}, {"aud": "wrong"}, {"aud": "research-api", "token_use": "id"}):
        with pytest.raises(ResearchError):
            auth.verify(encode(key, **changes))


@pytest.mark.parametrize("case", ["valid", "oversize", "slow-chunk", "slow-empty"])
def test_raw_download_limits(monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    """Real HTTPX iteration must preserve small data and reject oversized or late frames."""
    now = [0.0]

    class Frames(httpx.SyncByteStream):
        """Controlled transport frames reproduce size and elapsed-time failures without sleeps."""

        def __iter__(self) -> Iterator[bytes]:
            """Advance simulated elapsed time only once the response stream is opened."""
            if case.startswith("slow"):
                now[0] = 6.0
            if case == "slow-empty":
                return
            yield b"{}" if case != "oversize" else b"x" * MAX_JWKS_BYTES
            if case == "oversize":
                yield b"x"

    original_client = httpx.Client

    def response(request: httpx.Request) -> httpx.Response:
        """Confirm URL derivation never depends on the token being checked."""
        assert str(request.url) == f"{ISSUER}/.well-known/jwks.json"
        return httpx.Response(200, stream=Frames())

    def client(**kwargs: Any) -> httpx.Client:
        """The real client still handles context closure and streaming semantics."""
        return original_client(transport=httpx.MockTransport(response), **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr("factorforge.auth.cognito.time.monotonic", lambda: now[0])
    if case == "valid":
        assert verifier()._download() == b"{}"
    else:
        with pytest.raises(ValueError):
            verifier()._download()


@pytest.mark.parametrize("raw", [b"[]", b'{"keys":[]}', b'{"keys":[null]}'])
def test_invalid_key_collections_fail_closed(key: rsa.RSAPrivateKey, raw: bytes) -> None:
    """JSON validity alone never establishes a usable provider keyset."""
    with pytest.raises(ResearchError) as error:
        verifier(fetch_jwks=lambda: raw).verify(encode(key))
    assert error.value.status_code == 503


def test_nested_unverified_header_cannot_escape_auth_failure() -> None:
    """Parser exhaustion is possible before signature checks, despite the token byte limit."""
    header = b'{"alg":"RS256","kid":"first","extra":' + b"[" * 5000 + b"0" + b"]" * 5000 + b"}"
    raw = jwt.utils.base64url_encode(header).decode() + ".e30.eA"

    def forbidden() -> bytes:
        """Unparseable headers must be rejected before provider work."""
        raise AssertionError("Unexpected provider call")

    with pytest.raises(ResearchError) as error:
        verifier(fetch_jwks=forbidden).verify(raw)
    assert error.value.status_code == 401


@pytest.mark.parametrize("config", [{"mode": "other"}, {"storage": "other"}])
def test_direct_settings_construction_is_validated(config: dict[str, Any]) -> None:
    """Test factories cannot bypass environment validation by constructing settings directly."""
    with pytest.raises(ValueError):
        Settings(**config)


@pytest.mark.parametrize(
    "region,pool",
    [
        ("us-east-1.evil", "us-east-1_Review"),
        ("us-east-1", "us-east-1_Review/../other"),
        ("cn-north-1", "cn-north-1_Review"),
    ],
)
def test_provider_configuration_cannot_redirect_transport(region: str, pool: str) -> None:
    """Only the supported Cognito endpoint shape is available to this verifier."""
    with pytest.raises(ValueError):
        CognitoVerifier(region=region, pool_id=pool, client_id="reviewclient")
