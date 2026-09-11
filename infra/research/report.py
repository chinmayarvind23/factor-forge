"""Export a deterministic offline report from one retained scheduler artifact."""

import argparse
import json
from pathlib import Path

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.orchestration.report_export import export_report


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
    exported, path = export_report(result, store)
    print(
        json.dumps(
            {
                "report": exported.report.model_dump(mode="json"),
                "markdown": exported.markdown.model_dump(mode="json"),
                "path": str(args.artifacts / path.name),
            }
        )
    )


if __name__ == "__main__":
    main()
