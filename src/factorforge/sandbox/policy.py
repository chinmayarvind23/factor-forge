"""Server-owned admission verifies authority and exact bytes without invoking any runtime."""

import hashlib
import re

from pydantic import ValidationError

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.errors import ResearchError
from factorforge.domain.experiments import (
    ExperimentAdmission,
    ExperimentSpec,
    PythonSandboxPolicy,
)


def _principal(value: Principal) -> Principal:
    """Reconstruct dataclass fields before authority checks; do not trust overridden methods."""
    if not isinstance(value, Principal):
        raise ResearchError("FORBIDDEN", "Experiment execution is not permitted.", 403)
    valid_text = (
        type(value.issuer) is str
        and 0 < len(value.issuer) <= 2048
        and value.issuer.isprintable()
        and bool(value.issuer.strip())
        and type(value.subject) is str
        and 0 < len(value.subject) <= 256
        and value.subject.isprintable()
        and bool(value.subject.strip())
    )
    if (
        not valid_text
        or type(value.capabilities) is not frozenset
        or len(value.capabilities) > 64
        or any(
            type(cap) is not str
            or not 0 < len(cap) <= 128
            or not cap.isprintable()
            or not cap.strip()
            for cap in value.capabilities
        )
    ):
        raise ResearchError("FORBIDDEN", "Experiment execution is not permitted.", 403)
    return Principal(value.issuer, value.subject, value.capabilities)


def admit_experiment(
    spec: ExperimentSpec,
    store: ArtifactStore,
    *,
    principal: Principal,
    image_digest: str | None,
    allowed_image_digests: frozenset[str],
) -> ExperimentAdmission:
    """Fail before reads on authority/config errors, then check every unique artifact exactly once.

    Image configuration is trusted server input, but still requires canonical immutable identity.
    This function neither resolves an image nor creates a container; a future executor must
    stage these same verified bytes and enforce the recorded policy without caller overrides.
    """
    owner = _principal(principal)
    owner.require("execute_experiment")
    try:
        request = ExperimentSpec.model_validate(spec)
    except (ValueError, TypeError, ValidationError):
        raise ResearchError("SANDBOX_INPUT_INVALID", "Experiment input is invalid.", 422) from None
    if (request.owner_issuer, request.owner_subject) != (owner.issuer, owner.subject):
        raise ResearchError("FORBIDDEN", "Experiment execution is not permitted.", 403)
    if (
        type(image_digest) is not str
        or re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest) is None
        or type(allowed_image_digests) is not frozenset
        or not 0 < len(allowed_image_digests) <= 32
        or any(
            type(item) is not str or re.fullmatch(r"sha256:[a-f0-9]{64}", item) is None
            for item in allowed_image_digests
        )
        or image_digest not in allowed_image_digests
    ):
        raise ResearchError("SANDBOX_UNAVAILABLE", "An allowed runtime image is unavailable.", 503)
    references = request.unique_artifacts()
    for ref in references:
        data = store.get(ref)
        if (
            type(data) is not bytes
            or len(data) != ref.size_bytes
            or hashlib.sha256(data).hexdigest() != ref.sha256
        ):
            raise ResearchError(
                "SANDBOX_ARTIFACT_INVALID", "Experiment artifact bytes are invalid.", 422
            )
    return ExperimentAdmission(
        spec=request,
        policy=PythonSandboxPolicy(),
        image_digest=image_digest,
        verified_refs=references,
    )
