"""Export a deterministic offline report from one retained scheduler artifact."""

import argparse
import json
from pathlib import Path

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.orchestration.research_report import build_report, render_report
from factorforge.orchestration.research_strategies import _publish


def main() -> None:
    """Read evidence without models or database writes and publish JSON/Markdown artifacts."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--result-sha256", required=True)
    parser.add_argument("--result-size", type=int, required=True)
    args = parser.parse_args()
    store = LocalArtifactStore(args.artifacts)
    result = ArtifactRef(
        sha256=args.result_sha256, size_bytes=args.result_size, media_type="application/json"
    )
    report = build_report(result, store)
    reference = _publish(report, store)
    markdown = render_report(report).encode()
    rendered = store.put(markdown, media_type="text/markdown")
    path = args.artifacts / ("report-" + report.sha256 + ".md")
    try:
        with path.open("xb") as output:
            output.write(markdown)
    except FileExistsError:
        if path.read_bytes() != markdown:
            raise ValueError("Existing exported report differs from its content identity") from None
    print(
        json.dumps(
            {
                "report": reference.model_dump(mode="json"),
                "markdown": rendered.model_dump(mode="json"),
                "path": str(path),
            }
        )
    )


if __name__ == "__main__":
    main()
