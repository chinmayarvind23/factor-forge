"""Operator request validation must precede database setup or provider work."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from factorforge.orchestration.command import OperatorRequest, main
from factorforge.orchestration.research_experiments import ExperimentPlan, ReviewedExperimentPlan
from infra.research.prepare_original import main as prepare_original


def test_invalid_request_returns_safe_error(capsys: pytest.CaptureFixture[str]) -> None:
    """Untrusted JSON details are not included in the public command error."""
    with TemporaryDirectory() as directory:
        request = Path(directory) / "request.json"
        request.write_text('{"private-test-content":true}', encoding="utf-8")
        assert (
            main(["--request", str(request), "--artifacts", str(Path(directory) / "objects")]) == 1
        )
    captured = capsys.readouterr()
    assert "OPERATOR_REQUEST_INVALID" in captured.err
    assert "private-test-content" not in captured.err


@pytest.mark.parametrize("review", [False, True])
def test_original_preparation_preserves_versioned_request(
    monkeypatch: pytest.MonkeyPatch, review: bool
) -> None:
    """Both operator plan versions round-trip exactly and refuse replacement of saved evidence."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "request.json"
        args = ["prepare", "--request", str(path), "--artifacts", str(Path(directory) / "objects")]
        if review:
            args.append("--direction-review")
        monkeypatch.setattr("sys.argv", args)
        prepare_original()
        raw = path.read_bytes()
        request = OperatorRequest.model_validate_json(raw)
        assert request.canonical_bytes() == raw
        assert isinstance(request.plan, ReviewedExperimentPlan if review else ExperimentPlan)
        if isinstance(request.plan, ReviewedExperimentPlan):
            assert request.plan.max_cost_per_review_microusd == 1000000
        with pytest.raises(FileExistsError):
            prepare_original()
        assert path.read_bytes() == raw
