"""Independent CLI probes preserve fictional inputs and exercise the real module entrypoint."""

import json
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.literature import PaperDocument
from factorforge.evaluation.cli import main, run_evaluation
from factorforge.evaluation.retrieval import JudgedQuery, RetrievalCorpus, RetrievalJudgments


def write_inputs(root: Path) -> tuple[Path, Path, list[str]]:
    """Use explicit positive and negative fictional judgments unrelated to the frozen pilot."""
    corpus = RetrievalCorpus(
        version="review-v1",
        status="frozen",
        documents=(
            PaperDocument(
                paper_id="fruit",
                title="Orange",
                text="Citrus fruit.",
                source_url="https://example.invalid",
                source_version="review-v1",
                content_kind="original_summary",
            ),
        ),
    )
    qrels = RetrievalJudgments(
        version="review-v1",
        status="frozen",
        corpus_sha256=corpus.sha256,
        queries=(
            JudgedQuery(query_id="positive", text="citrus", judgments={"fruit": 1}),
            JudgedQuery(query_id="negative", text="volcano", judgments={"fruit": 0}),
        ),
    )
    corpus_path, qrels_path = root / "corpus.json", root / "qrels.json"
    corpus_path.write_bytes(
        json.dumps(corpus.model_dump(mode="json"), indent=2).replace("\n", "\r\n").encode()
    )
    qrels_path.write_bytes(json.dumps(qrels.model_dump(mode="json"), indent=3).encode())
    return (
        corpus_path,
        qrels_path,
        [
            "--corpus",
            str(corpus_path),
            "--qrels",
            str(qrels_path),
            "--output",
            str(root / "objects"),
            "--k",
            "1",
        ],
    )


def test_missing_dependency_metadata_is_safe_failed_lineage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An incomplete installed environment must not emit a traceback or successful report."""

    def absent(package: str) -> str:
        """Simulate a broken installation without uninstalling or changing real packages."""
        raise PackageNotFoundError("private diagnostic " + package)

    monkeypatch.setattr("factorforge.evaluation.cli.version", absent)
    with TemporaryDirectory(prefix="factorforge-cli-review-") as directory:
        _, _, arguments = write_inputs(Path(directory))
        assert main(arguments) == 1
    output = capsys.readouterr()
    assert output.out == "" and "private diagnostic" not in output.err
    assert json.loads(output.err)["error"]["code"] == "RETRIEVAL_LINEAGE_INVALID"


def test_module_subprocess_preserves_exact_inputs_and_replays_report() -> None:
    """Real module execution and archived-input replay produce the same canonical report."""
    with TemporaryDirectory(prefix="factorforge-cli-subprocess-") as directory:
        root = Path(directory)
        corpus_path, qrels_path, arguments = write_inputs(root)
        completed = subprocess.run(
            [sys.executable, "-m", "factorforge.evaluation.cli", *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0
        assert completed.stderr == ""
        output = json.loads(completed.stdout)
        store = LocalArtifactStore(root / "objects")
        record = json.loads(store.get(ArtifactRef.model_validate(output["record"])))
        assert store.get(ArtifactRef.model_validate(record["corpus"])) == corpus_path.read_bytes()
        assert store.get(ArtifactRef.model_validate(record["qrels"])) == qrels_path.read_bytes()
        assert output["report"]["recall_at_k"] == 1
        assert output["report"]["no_relevant_abstention_rate"] == 1
        for name in ("corpus", "qrels"):
            (root / f"replay-{name}.json").write_bytes(
                store.get(ArtifactRef.model_validate(record[name]))
            )
        replay = run_evaluation(root / "replay-corpus.json", root / "replay-qrels.json", store, k=1)
        replay_record = json.loads(store.get(ArtifactRef.model_validate(replay["record"])))
        assert replay["report"] == output["report"]
        assert replay_record["report"] == record["report"]
        assert replay_record["config"] == record["config"]
        assert replay_record["environment"] == record["environment"]


def test_module_subprocess_invalid_input_returns_only_safe_error() -> None:
    """The process exit status and stderr contract hold outside an in-process pytest call."""
    with TemporaryDirectory(prefix="factorforge-cli-subprocess-") as directory:
        root = Path(directory)
        corpus_path, _, arguments = write_inputs(root)
        corpus_path.write_bytes(
            b'{"private":"untrusted source text","status":"frozen","status":"draft"}'
        )
        completed = subprocess.run(
            [sys.executable, "-m", "factorforge.evaluation.cli", *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 1 and completed.stdout == ""
        error = json.loads(completed.stderr)
        assert error["error"]["code"] == "RETRIEVAL_INPUT_INVALID"
        assert directory not in completed.stderr and "untrusted source text" not in completed.stderr


@pytest.mark.parametrize("case", ["missing_file", "missing_module", "bad_encoding"])
def test_source_evidence_failure_is_safe_and_never_succeeds(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unavailable source evidence cannot leave a published success pointer."""
    with TemporaryDirectory(prefix="factorforge-cli-source-") as directory:
        root = Path(directory)
        _, _, arguments = write_inputs(root)
        invalid_source = root / "invalid.py"
        invalid_source.write_bytes(b"\xff")

        def module(name: str) -> SimpleNamespace:
            """Substitute only the source reader, preserving installed runtime behavior."""
            if case == "missing_module":
                raise ModuleNotFoundError("private source diagnostic " + name)
            return SimpleNamespace(__file__=str(invalid_source) if case == "bad_encoding" else None)

        monkeypatch.setattr(
            "factorforge.evaluation.cli.importlib", SimpleNamespace(import_module=module)
        )
        assert main(arguments) == 1
        output = capsys.readouterr()
        assert output.out == "" and directory not in output.err
        assert "private source diagnostic" not in output.err
        assert json.loads(output.err)["error"]["code"] == "RETRIEVAL_LINEAGE_INVALID"


@pytest.mark.parametrize(
    "invalid",
    [
        b'{"ignored":NaN}',
        b'{"ignored":1e999}',
        b'{"ignored":1.5}',
        b"\xff",
        b"[" * 2000 + b"0" + b"]" * 2000,
    ],
)
def test_ambiguous_nonfinite_or_deep_input_never_publishes_report(
    invalid: bytes,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Malformed source bytes are rejected before evaluation and source-artifact creation."""
    with TemporaryDirectory(prefix="factorforge-cli-input-") as directory:
        root = Path(directory)
        corpus_path, _, arguments = write_inputs(root)
        corpus_path.write_bytes(invalid)
        assert main(arguments) == 1
        output = capsys.readouterr()
        assert output.out == ""
        assert json.loads(output.err)["error"]["code"] == "RETRIEVAL_INPUT_INVALID"
        assert not list((root / "objects").iterdir())
