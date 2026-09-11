"""Verify fixed-pool Cognito access tokens before granting owner-scoped capabilities."""

import json
import re
import threading
import time
from collections.abc import Callable

import httpx
import jwt

from factorforge.auth.principal import Principal
from factorforge.domain.errors import ResearchError

MAX_TOKEN_BYTES = 16384
MAX_ENCODED_HEADER_BYTES = 2048
MAX_JWKS_BYTES = 65536


def unauthorized() -> ResearchError:
    """Credential failures deliberately disclose no token or cryptographic diagnostics."""
    return ResearchError("UNAUTHORIZED", "A valid access token is required.", 401)


class CognitoVerifier:
    """A small locked cache bounds provider traffic and supports normal signing-key rotation."""

    def __init__(
        self,
        *,
        region: str,
        pool_id: str,
        client_id: str,
        audience: str | None = None,
        fetch_jwks: Callable[[], bytes] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Deployment configuration determines the only allowed issuer and JWKS address."""
        if (
            not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d", region)
            or not re.fullmatch(re.escape(region) + r"_[A-Za-z0-9]+", pool_id)
            or not re.fullmatch(r"[A-Za-z0-9]{1,128}", client_id)
            or region.startswith("cn-")
        ):
            raise ValueError("Invalid or unsupported Cognito deployment configuration.")
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        self.client_id = client_id
        self.audience = audience
        self._fetch = fetch_jwks or self._download
        self._clock = clock
        self._lock = threading.Lock()
        self._keys: dict[str, jwt.PyJWK] = {}
        self._expires = float("-inf")
        self._refresh_after = float("-inf")
        self._unavailable = False

    def _download(self) -> bytes:
        """Bound bytes, redirects and total streamed time without trusting proxy environment."""
        started = time.monotonic()
        with (
            httpx.Client(timeout=3, follow_redirects=False, trust_env=False) as client,
            client.stream("GET", self.jwks_url, headers={"Accept-Encoding": "identity"}) as r,
        ):
            r.raise_for_status()
            if r.headers.get("content-encoding", "identity").lower().strip() != "identity":
                raise ValueError("Compressed signing-key responses are not permitted.")
            body = bytearray()
            # Raw iteration prevents decompression from allocating before the byte budget check.
            for chunk in r.iter_raw():
                if len(body) + len(chunk) > MAX_JWKS_BYTES or time.monotonic() - started > 5:
                    raise ValueError("Signing-key response exceeded its budget.")
                body.extend(chunk)
            if time.monotonic() - started > 5:
                raise ValueError("Signing-key response exceeded its time budget.")
            return bytes(body)

    def _key(self, kid: str) -> jwt.PyJWK:
        """One refresh per 30 seconds prevents arbitrary unknown IDs from amplifying traffic."""
        with self._lock:
            now = self._clock()
            if now < self._expires and kid in self._keys:
                return self._keys[kid]
            if now >= self._refresh_after:
                self._refresh_after = now + 30
                try:
                    raw = self._fetch()
                    if len(raw) > MAX_JWKS_BYTES:
                        raise ValueError("Excessive signing-key response.")
                    document = json.loads(raw)
                    entries = document.get("keys") if isinstance(document, dict) else None
                    if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
                        raise ValueError("Invalid signing-key collection.")
                    keys: dict[str, jwt.PyJWK] = {}
                    for entry in entries:
                        if not isinstance(entry, dict):
                            raise ValueError("Invalid signing key.")
                        key_id = entry.get("kid")
                        if (
                            not isinstance(key_id, str)
                            or not 1 <= len(key_id) <= 256
                            or key_id in keys
                            or entry.get("kty") != "RSA"
                            or entry.get("use") != "sig"
                            or entry.get("alg", "RS256") != "RS256"
                            or entry.get("key_ops", ["verify"]) != ["verify"]
                            or not isinstance(entry.get("n"), str)
                            or len(entry["n"]) > 1400
                        ):
                            raise ValueError("Untrusted signing-key shape.")
                        keys[key_id] = jwt.PyJWK.from_dict(entry, algorithm="RS256")
                    self._keys = keys
                    self._expires = now + 300
                    self._unavailable = False
                except (
                    OSError,
                    ValueError,
                    TypeError,
                    KeyError,
                    RecursionError,
                    jwt.PyJWTError,
                    httpx.HTTPError,
                ):
                    self._unavailable = True
            if self._unavailable:
                raise ResearchError(
                    "AUTH_UNAVAILABLE", "Identity verification is unavailable.", 503
                )
            if self._clock() >= self._expires or kid not in self._keys:
                raise unauthorized()
            return self._keys[kid]

    def verify(self, token: str) -> Principal:
        """Unverified headers select a trusted key but can never supply identity or URLs."""
        if (
            not token
            or len(token) > MAX_TOKEN_BYTES
            or not token.isascii()
            or len(token.partition(".")[0]) > MAX_ENCODED_HEADER_BYTES
        ):
            raise unauthorized()
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if (
                header.get("alg") != "RS256"
                or not isinstance(kid, str)
                or not 1 <= len(kid) <= 256
                or any(name in header for name in ("jku", "x5u", "jwk", "crit"))
            ):
                raise unauthorized()
            key = self._key(kid)
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                leeway=30,
                options={"require": ["iss", "sub", "exp", "iat", "token_use", "client_id"]},
            )
            if (
                claims["client_id"] != self.client_id
                or claims["token_use"] != "access"
                or not isinstance(claims["sub"], str)
                or not 1 <= len(claims["sub"]) <= 256
                or not claims["sub"].strip()
                or any(type(claims[name]) is not int for name in ("exp", "iat"))
                or ("nbf" in claims and type(claims["nbf"]) is not int)
                or not isinstance(claims.get("scope", ""), str)
            ):
                raise unauthorized()
            scopes = set(claims.get("scope", "").split())
            capabilities = frozenset(
                capability
                for scope, capability in (
                    ("factorforge/create", "create_run"),
                    ("factorforge/read", "read_own_run"),
                )
                if scope in scopes
            )
            return Principal(self.issuer, claims["sub"], capabilities)
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
            raise unauthorized() from None
