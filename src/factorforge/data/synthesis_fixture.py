"""Original source documents make the complete source-to-hybrid example reproducible."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from factorforge.data.artifacts import ArtifactStore
from factorforge.data.hybrid_fixture import prepare_hybrid_fixture
from factorforge.domain.literature import PaperDocument
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.research_strategies import ReviewedStrategyBinding
from factorforge.orchestration.synthesis_command import SynthesisResearchRequest
from factorforge.retrieval.extraction import SourcePacket, SourcePage
from factorforge.retrieval.selection import LiteratureCatalog, LiteratureEntry


def prepare_synthesis_fixture(repository: Path, store: ArtifactStore) -> SynthesisResearchRequest:
    """Provide complete original method descriptions, with no expected model response or result."""
    hybrid = prepare_hybrid_fixture(repository, store)
    entries, bindings = [], []
    for component in hybrid.components:
        name = component.strategy.formula
        mechanism = (
            "relative strength persists" if name == "score" else "operating quality persists"
        )
        text = (
            f"Original {name} monthly strategy. Hypothesis: {mechanism} over the next month. "
            f"The sorting signal is the supplied dimensionless scalar {name}. Formula: {name}. "
            f"Required signal input: {name}. Use two equal-weight buckets. "
            f"Buy securities with high {name} values and short securities with low {name} values. "
            "Hold each cohort for 1 month and rebalance monthly. Formation lag is 0 months. "
            "No trailing lookback window is required for this scalar signal. "
            "Formation rule: Last session close each month. "
            "Use only signal values available at formation, and trade at the subsequent open. "
            "This is an original fictional research method for an engineering demonstration."
        )
        page = store.put(text.encode(), media_type="text/plain")
        packet = SourcePacket(
            paper_id="original-" + name,
            source_sha256=page.sha256,
            selected_strategy="Original " + name + " monthly strategy",
            pages=(SourcePage(pdf_page=1, artifact=page),),
        )
        entries.append(
            LiteratureEntry(
                source=packet,
                document=PaperDocument(
                    paper_id=packet.paper_id,
                    title=packet.selected_strategy,
                    text=text,
                    source_url="https://example.org/" + packet.paper_id,
                    source_sha256=page.sha256,
                    content_kind="original_summary",
                    source_version="synthesis-original-v1",
                ),
            )
        )
        bindings.append(
            ReviewedStrategyBinding(
                source=packet,
                environment=component.strategy,
                reviewed_formation_rule="Last session close each month",
            )
        )
    return SynthesisResearchRequest(
        brief=ResearchBrief(
            idea=(
                "Combine original score and quality strategies "
                "with 75% score and 25% quality contributions."
            ),
            max_experiments=1,
        ),
        catalog=LiteratureCatalog(entries=tuple(entries)),
        bindings=tuple(bindings),
        initial_cash_usd=Decimal("1002"),
        evaluated_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
    )
