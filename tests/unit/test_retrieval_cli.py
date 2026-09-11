"""The local evaluation command archives original hand fixtures and reports safe failures."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.literature import PaperDocument
from factorforge.evaluation.cli import main
from factorforge.evaluation.retrieval import JudgedQuery, RetrievalCorpus, RetrievalJudgments


def inputs(root: Path) -> list[str]:
    """Create one explicitly judged original test document without using frozen pilot outcomes."""
    corpus = RetrievalCorpus(
        version="test",
        status="frozen",
        documents=(
            PaperDocument(
                paper_id="test",
                title="Oranges",
                text="A fruit.",
                source_url="https://example.invalid",
                source_version="original-test",
                content_kind="original_summary",
            ),
        ),
    )
    qrels = RetrievalJudgments(
        version="test",
        status="frozen",
        corpus_sha256=corpus.sha256,
        queries=(JudgedQuery(query_id="q", text="orange", judgments={"test": 1}),),
    )
    (root / "corpus.json").write_bytes(corpus.canonical_bytes())
    (root / "qrels.json").write_bytes(qrels.canonical_bytes())
    return [
        "--corpus",
        str(root / "corpus.json"),
        "--qrels",
        str(root / "qrels.json"),
        "--output",
        str(root / "objects"),
    ]


def test_cli_preserves_inputs_config_code_environment_and_actual_miss(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No stemming means orange misses oranges; preserve that miss without repair."""
    with TemporaryDirectory(prefix="factorforge-retrieval-cli-") as directory:
        root = Path(directory)
        assert main(inputs(root)) == 0
        output = json.loads(capsys.readouterr().out)
        store = LocalArtifactStore(root / "objects")
        record = json.loads(store.get(ArtifactRef.model_validate(output["record"])))
        for key in ("corpus", "qrels", "config", "report", "environment"):
            assert store.get(ArtifactRef.model_validate(record[key]))
        assert len(record["code"]) >= 7
        for reference in record["code"].values():
            assert store.get(ArtifactRef.model_validate(reference))
        report = json.loads(store.get(ArtifactRef.model_validate(record["report"])))
        assert report["recall_at_k"] == 0 and report["mrr_at_k"] == 0
        assert report["answerable_queries"] == 1
        assert output["report"] == report


@pytest.mark.parametrize("case", ["duplicate", "missing", "oversize", "bad_identity"])
def test_cli_errors_are_typed_without_paths_or_raw_input(
    case: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ambiguous inputs and filesystem failures cannot produce a successful evaluation artifact."""
    with TemporaryDirectory(prefix="factorforge-retrieval-cli-") as directory:
        root = Path(directory)
        args = inputs(root)
        if case == "duplicate":
            path = root / "corpus.json"
            path.write_bytes(path.read_bytes()[:-1] + b',"status":"frozen"}')
        elif case == "missing":
            args[1] = str(root / "absent.json")
        elif case == "oversize":
            (root / "corpus.json").write_bytes(b"x" * (16 * 1024 * 1024 + 1))
        else:
            path = root / "qrels.json"
            value = json.loads(path.read_bytes())
            value["corpus_sha256"] = "0" * 64
            path.write_text(json.dumps(value), encoding="utf-8")
        assert main(args) == 1
        output = capsys.readouterr()
        assert output.out == "" and directory not in output.err
        assert json.loads(output.err)["error"]["code"].startswith("RETRIEVAL_")
