"""Identity, storage and environment labels have separate explicit configuration roles."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

LOCAL_ORIGIN = "http://127.0.0.1:3001"


@dataclass(frozen=True)
class Settings:
    """Secrets are excluded from diagnostic representations and never select identity mode."""

    mode: Literal["disabled", "local", "cognito"] = "disabled"
    storage: Literal["memory", "postgres"] = "memory"
    dsn: str | None = field(default=None, repr=False)
    region: str = ""
    pool_id: str = ""
    client_id: str = ""
    audience: str | None = None
    allowed_origin: str = LOCAL_ORIGIN

    def __post_init__(self) -> None:
        """Validate direct construction too, so application factories cannot bypass invariants."""
        if self.mode not in {"disabled", "local", "cognito"}:
            raise ValueError("Invalid access mode.")
        if self.storage not in {"memory", "postgres"}:
            raise ValueError("Invalid storage mode.")
        if self.storage == "postgres" and not self.dsn:
            raise ValueError("PostgreSQL storage requires RDS_DSN.")
        if self.mode == "cognito" and (
            self.storage != "postgres" or not all((self.region, self.pool_id, self.client_id))
        ):
            raise ValueError("Cognito mode requires durable storage and identity configuration.")
        if any(ord(character) <= 32 or ord(character) == 127 for character in self.allowed_origin):
            raise ValueError("Browser origin cannot contain whitespace or control characters.")
        try:
            origin = urlsplit(self.allowed_origin)
            port = origin.port
        except ValueError:
            raise ValueError("Browser origin has an invalid host or port.") from None
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.path
            or origin.query
            or origin.fragment
            or origin.username
            or origin.password
            or port == 0
            or (
                origin.scheme == "http" and origin.hostname not in {"127.0.0.1", "localhost", "::1"}
            )
        ):
            raise ValueError("Configure one exact HTTPS browser origin or a loopback HTTP origin.")

    @classmethod
    def from_environment(cls, values: Mapping[str, str] | None = None) -> "Settings":
        """Do not autoload .env or interpret FACTORFORGE_ENV as an authorization switch."""
        env = os.environ if values is None else values
        mode = env.get("FACTORFORGE_MODE", "disabled")
        storage = env.get("FACTORFORGE_STORAGE", "postgres" if mode == "cognito" else "memory")
        if mode not in {"disabled", "local", "cognito"} or storage not in {"memory", "postgres"}:
            raise ValueError("Invalid access or storage mode.")
        return cls(
            mode=mode,  # type: ignore[arg-type]
            storage=storage,  # type: ignore[arg-type]
            dsn=env.get("RDS_DSN"),
            region=env.get("AWS_REGION", ""),
            pool_id=env.get("COGNITO_USER_POOL_ID", ""),
            client_id=env.get("COGNITO_CLIENT_ID", ""),
            audience=env.get("COGNITO_AUDIENCE"),
            allowed_origin=env.get("FACTORFORGE_ALLOWED_ORIGIN", LOCAL_ORIGIN),
        )
