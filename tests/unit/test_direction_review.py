"""Direction review retains source-cited judgments without rewriting extraction observations."""

import json

import pytest
from test_monthly_admission import MemoryStore

from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.errors import ResearchError
from factorforge.providers.ollama import GenerationRequest, GenerationResult
from factorforge.retrieval.direction_review import review_direction
from factorforge.retrieval.extraction import SourcePacket, SourcePage


@pytest.mark.parametrize(
    "quote,page,status",
    [
        ("Long high and short low.", 1, "supported"),
        ("Invented passage", 1, "invalid"),
        ("Long high and short low.", 2, "invalid"),
    ],
)
def test_direction_review_requires_a_quote_on_the_cited_page(
    quote: str, page: int, status: str
) -> None:
    """A reviewer can support a direction only with an exact excerpt from its actual input page."""
    store = MemoryStore()
    source = SourcePacket(
        paper_id="original",
        source_sha256="a" * 64,
        selected_strategy="score",
        pages=(
            SourcePage(
                pdf_page=1, artifact=store.put(b"Long high and short low.", media_type="text/plain")
            ),
        ),
    )

    class Provider:
        """Controlled reviewer output tests evidence binding rather than model accuracy."""

        def generate(
            self, request: GenerationRequest, artifacts: ArtifactStore
        ) -> GenerationResult:
            """The reviewer receives pages but no proposed extraction direction to copy."""
            assert "extraction" not in json.loads(request.user)
            return GenerationResult(
                status="success",
                record=artifacts.put(b"{}", media_type="application/json"),
                content=json.dumps(
                    {
                        "direction": "long_high_short_low",
                        "quote": quote,
                        "pdf_page": page,
                        "uncertainty": None,
                    }
                ),
            )

    result = review_direction(source, Provider(), store)
    assert result.status == status
    assert (result.observation is not None) == (status == "supported")
    assert store.get(result.record)


def test_source_corruption_precedes_reviewer_call() -> None:
    """A generic artifact provider must not substitute text behind a reviewed page reference."""
    store = MemoryStore()
    page = store.put(b"Original passage", media_type="text/plain")
    source = SourcePacket(
        paper_id="original",
        source_sha256="a" * 64,
        selected_strategy="score",
        pages=(SourcePage(pdf_page=1, artifact=page),),
    )
    store.values[page.sha256] = b"Substituted page"

    class Provider:
        """Any provider call would demonstrate an admission-order error."""

        def generate(
            self, request: GenerationRequest, artifacts: ArtifactStore
        ) -> GenerationResult:
            """Reject invocation before source verification succeeds."""
            raise AssertionError("provider must not run")

    with pytest.raises(ResearchError):
        review_direction(source, Provider(), store)


@pytest.mark.parametrize(
    "content,delivered,status",
    [
        (
            '{"direction":null,"quote":null,"pdf_page":null,"uncertainty":"Unclear direction"}',
            True,
            "uncertain",
        ),
        (
            '{"direction":null,"direction":null,"quote":null,"pdf_page":null,"uncertainty":"Unknown"}',
            True,
            "invalid",
        ),
        (
            '{"direction":"long_high_short_low","quote":null,"pdf_page":null,"uncertainty":null}',
            True,
            "invalid",
        ),
        (None, False, "provider_failed"),
    ],
)
def test_review_preserves_uncertainty_and_invalid_delivery(
    content: str | None, delivered: bool, status: str
) -> None:
    """Unknown, contradictory and duplicate-key observations never become supported judgments."""
    store = MemoryStore()
    source = SourcePacket(
        paper_id="original",
        source_sha256="a" * 64,
        selected_strategy="score",
        pages=(
            SourcePage(
                pdf_page=1, artifact=store.put(b"Original passage", media_type="text/plain")
            ),
        ),
    )

    class Provider:
        """Supply exact response bytes for each parser/outcome boundary."""

        def generate(
            self, request: GenerationRequest, artifacts: ArtifactStore
        ) -> GenerationResult:
            """Archive a provider record even when no usable judgment was delivered."""
            return GenerationResult(
                status="success" if delivered else "unavailable",
                content=content,
                record=artifacts.put(b"{}", media_type="application/json"),
            )

    result = review_direction(source, Provider(), store)
    assert result.status == status
    assert (result.observation is not None) == (status == "uncertain")
