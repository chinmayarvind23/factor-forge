"""Only verified identity, never request-supplied ownership, crosses the storage boundary."""

from dataclasses import dataclass

from factorforge.domain.errors import ResearchError


@dataclass(frozen=True)
class Principal:
    """Issuer and subject together isolate identities from different identity providers."""

    issuer: str
    subject: str
    capabilities: frozenset[str]

    def require(self, capability: str) -> None:
        """Capabilities are checked before storage access or work allocation."""
        if capability not in self.capabilities:
            raise ResearchError("FORBIDDEN", "This operation is not permitted.", 403)


LOCAL_PRINCIPAL = Principal(
    issuer="factorforge-local",
    subject="local-researcher",
    capabilities=frozenset({"create_run", "read_own_run"}),
)
