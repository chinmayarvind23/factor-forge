"""Bounded offline verification of every explicitly referenced object in an evidence bundle."""

import json

from factorforge.data.artifacts import ArtifactStore, verify_bytes
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.extraction import _unique_pairs


def verify_closure(root: ArtifactRef, store: ArtifactStore) -> tuple[ArtifactRef, ...]:
    """Verify references without interpreting source text, executing code or following URLs.

    This proves byte integrity of reachable typed references, not author authenticity or
    completeness against an external lineage specification. Bounds limit untrusted bundles.
    """
    try:
        pending = [ArtifactRef.model_validate(root)]
        seen: dict[str, ArtifactRef] = {}
        total = 0
        while pending:
            ref = pending.pop()
            if ref.sha256 in seen:
                if seen[ref.sha256] != ref:
                    raise ValueError("Conflicting metadata for the same object")
                continue
            total += ref.size_bytes
            if len(seen) >= 512 or not 0 <= ref.size_bytes <= 8 * 2**20 or total > 64 * 2**20:
                raise ValueError("Evidence closure exceeds limits")
            raw = store.get(ref.model_copy(deep=True))
            if type(raw) is not bytes:
                raise ValueError("Artifact provider must return bytes")
            verify_bytes(raw, ref)
            seen[ref.sha256] = ref
            if ref.media_type == "application/json":
                values: list[object] = [json.loads(raw, object_pairs_hook=_unique_pairs)]
                visited = 0
                while values:
                    value = values.pop()
                    visited += 1
                    if visited > 100000:
                        raise ValueError("JSON evidence exceeds structural bounds")
                    if isinstance(value, dict):
                        if set(value) == {"sha256", "size_bytes", "media_type"}:
                            pending.append(ArtifactRef.model_validate(value))
                        else:
                            values.extend(value.values())
                    elif isinstance(value, list):
                        values.extend(value)
        return tuple(seen[key] for key in sorted(seen))
    except Exception:
        raise ResearchError(
            "LINEAGE_EVIDENCE_INVALID", "Evidence closure cannot be verified.", 409
        ) from None
