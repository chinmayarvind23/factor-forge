"""A single-case trial must check frozen inputs and retain evidence before any delivery."""

import json
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import pytest
from pydantic import JsonValue

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.extraction import SourceExtraction
from factorforge.evaluation.extraction import CaseGrade, GoldCase, NumericalVector
from factorforge.evaluation.source_trial import main, run_source_trial
from factorforge.providers.ollama import GenerationRequest, GenerationResult, _request_payload
from factorforge.retrieval.extraction import (
    ExtractionResult,
    SourcePacket,
    SourcePage,
    prepare_prompt,
)


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Avoid pytest's current-directory symlink on this Windows mount policy."""
    with TemporaryDirectory(prefix="factorforge-trial-") as directory:
        yield Path(directory)


def inputs(root: Path) -> tuple[Path, Path, Path, LocalArtifactStore, GoldCase]:
    """Construct source and gold independently of the private three-paper development suite."""
    store = LocalArtifactStore(root / "objects")
    page = store.put(b"An original synthetic strategy description.", media_type="text/plain")
    packet = SourcePacket(
        paper_id="synthetic",
        source_sha256="a" * 64,
        selected_strategy="Original engineering case",
        pages=(SourcePage(pdf_page=1, artifact=page),),
    )
    observation = SourceExtraction(
        status="extracted",
        refusal_reason=None,
        refusal_category=None,
        formula="x * 2",
        required_inputs=["x"],
        long_short_direction="long_high_short_low",
        bucket_count=5,
        weighting="equal_weight",
        lookback_months=None,
        holding_months=12,
        rebalance_frequency="annual",
        formation_lag_months=0,
        formation_rule="PRIVATE_GOLD_MARKER",
        source_pages=[1],
    )
    gold = GoldCase(
        case_id="original-v1",
        paper_id="synthetic",
        source_sha256="a" * 64,
        expected=observation,
        numerical_vectors=tuple(
            NumericalVector(name=f"case-{n}", scalars={"x": str(n)}, expected=str(n * 2))
            for n in (1, 2, 3)
        ),
        allowed_source_pages=(1,),
    )
    prompt = prepare_prompt(packet, store)
    request = GenerationRequest(
        model="llama3.1:8b",
        system=cast(str, prompt["system"]),
        user=cast(str, prompt["user"]),
        response_schema=cast(dict[str, JsonValue], prompt["response_schema"]),
    )
    expected = store.put(_request_payload(request)[1], media_type="application/json")
    paths = (root / "packet.json", root / "gold.json", root / "expected.json")
    for path, value in zip(paths, (packet, gold, expected), strict=True):
        path.write_text(value.model_dump_json(), encoding="utf-8")
    return *paths, store, gold


class Provider:
    """Inspect the pre-call start record and return only a saved original protocol fixture."""

    def __init__(self, content: str | None, *, fatal: bool = False) -> None:
        """Keep a deterministic response and invocation count for no-retry checks."""
        self.content = content
        self.fatal = fatal
        self.calls = 0
        self.requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest, store: ArtifactStore) -> GenerationResult:
        """The actual model boundary receives no gold, and its start record already exists."""
        self.calls += 1
        self.requests.append(request)
        assert isinstance(store, LocalArtifactStore)
        starts = [
            json.loads(path.read_bytes())
            for path in store.root.glob("sha256/*/*")
            if path.read_bytes().startswith(b'{"case_id"')
        ]
        assert any(row.get("schema_version") == "source-trial-start-v1" for row in starts)
        assert "PRIVATE_GOLD_MARKER" not in request.model_dump_json()
        assert "numerical_vectors" not in request.model_dump_json()
        if self.fatal:
            raise RuntimeError("private-token-that-must-not-be-archived")
        return GenerationResult(
            status="success" if self.content else "unavailable",
            record=store.put(b'{"original_protocol_fixture":true}', media_type="application/json"),
            content=self.content,
        )


def test_success_archives_start_result_grade_and_complete_references(tmp_path: Path) -> None:
    """The grade and output are saved separately and refer back to a start created before I/O."""
    packet, goldpath, expected, store, gold = inputs(tmp_path)
    provider = Provider(gold.expected.model_dump_json())
    result = run_source_trial(packet, goldpath, expected, store, provider=provider)
    assert provider.calls == 1
    assert CaseGrade.model_validate(result["grade"]).matched_fields == 9
    root = json.loads(store.get(ArtifactRef.model_validate(result["record"])))
    assert root["provider_invocations"] == 1 and root["elapsed_ms"] >= 0
    start = json.loads(store.get(ArtifactRef.model_validate(root["start"])))
    for name in ("packet", "gold", "expected_request", "expected_request_pointer", "environment"):
        assert store.get(ArtifactRef.model_validate(start[name]))
    for ref in start["code"].values():
        assert store.get(ArtifactRef.model_validate(ref))
    assert store.get(ArtifactRef.model_validate(root["result"]))
    assert store.get(ArtifactRef.model_validate(root["grade"]))


def test_qwen_requires_its_own_frozen_wire_request(tmp_path: Path) -> None:
    """A profile comparison changes only the declared model, never bypassing frozen input checks."""
    packet, goldpath, expected, store, gold = inputs(tmp_path)
    provider = Provider(gold.expected.model_dump_json())
    with pytest.raises(ResearchError):
        run_source_trial(packet, goldpath, expected, store, provider=provider, model="qwen3:8b")
    assert provider.calls == 0
    prompt = prepare_prompt(SourcePacket.model_validate_json(packet.read_bytes()), store)
    request = GenerationRequest(
        model="qwen3:8b",
        system=cast(str, prompt["system"]),
        user=cast(str, prompt["user"]),
        response_schema=cast(dict[str, JsonValue], prompt["response_schema"]),
    )
    expected.write_text(
        store.put(_request_payload(request)[1], media_type="application/json").model_dump_json()
    )
    result = run_source_trial(
        packet, goldpath, expected, store, provider=provider, model="qwen3:8b"
    )
    assert provider.calls == 1 and provider.requests[0].model == "qwen3:8b"
    assert CaseGrade.model_validate(result["grade"]).matched_fields == 9


def test_evidence_style_flows_through_frozen_trial(tmp_path: Path) -> None:
    """The wrapper reaches the provider and its nested observation reaches the unchanged grader."""
    packet, goldpath, expected, store, gold = inputs(tmp_path)
    prompt = prepare_prompt(
        SourcePacket.model_validate_json(packet.read_bytes()), store, style="evidence-first-v1"
    )
    request = GenerationRequest.model_validate(dict(model="qwen3:8b", **prompt))
    expected.write_text(
        store.put(_request_payload(request)[1], media_type="application/json").model_dump_json()
    )
    fields = [
        name
        for name, value in gold.expected.model_dump().items()
        if name not in {"status", "refusal_reason", "refusal_category", "source_pages"}
        and value is not None
        and value != []
    ]
    provider = Provider(
        json.dumps(
            {
                "evidence": [
                    {
                        "fields": fields,
                        "pdf_page": 1,
                        "quote": "An original synthetic strategy description.",
                    }
                ],
                "observation": gold.expected.model_dump(),
            }
        )
    )
    result = run_source_trial(
        packet,
        goldpath,
        expected,
        store,
        provider=provider,
        model="qwen3:8b",
        style="evidence-first-v1",
    )
    assert provider.calls == 1 and CaseGrade.model_validate(result["grade"]).matched_fields == 9
    start = json.loads(store.get(ArtifactRef.model_validate(result["start"])))
    assert start["prompt_version"] == "source-evidence-first-v1"


@pytest.mark.parametrize("change", ["paper", "source", "pages", "request", "missing_page"])
def test_preflight_mismatch_never_calls_provider(tmp_path: Path, change: str) -> None:
    """Declared source and exact wire identity fail before admission or a model request."""
    packet, gold, expected, store, _ = inputs(tmp_path)
    value = json.loads(packet.read_bytes())
    if change == "paper":
        value["paper_id"] = "other"
    elif change == "source":
        value["source_sha256"] = "b" * 64
    elif change == "pages":
        value["pages"][0]["pdf_page"] = 2
    elif change == "missing_page":
        digest = value["pages"][0]["artifact"]["sha256"]
        (store.root / "sha256" / digest[:2] / digest).unlink()
    else:
        expected.write_text(store.put(b"{}", media_type="application/json").model_dump_json())
    packet.write_text(json.dumps(value))
    provider = Provider(None)
    with pytest.raises(ResearchError):
        run_source_trial(packet, gold, expected, store, provider=provider)
    assert provider.calls == 0


def test_fatal_provider_exception_leaves_safe_event_and_propagates(tmp_path: Path) -> None:
    """An unexpected failure cannot look like a missing attempt or be silently retried."""
    packet, gold, expected, store, _ = inputs(tmp_path)
    provider = Provider(None, fatal=True)
    with pytest.raises(RuntimeError) as failure:
        run_source_trial(packet, gold, expected, store, provider=provider)
    assert provider.calls == 1
    ref = getattr(failure.value, "trial_failure_record", None)
    assert isinstance(ref, ArtifactRef)
    event = store.get(ref)
    assert b"private-token" not in event
    record = json.loads(event)
    assert record["status"] == "fatal" and record["provider_invocations"] == 1
    assert store.get(ArtifactRef.model_validate(record["start"]))


def test_unavailable_delivery_is_graded_zero_without_retry(tmp_path: Path) -> None:
    """An ordinary failed delivery still contributes a saved nine-field failed case."""
    packet, gold, expected, store, _ = inputs(tmp_path)
    provider = Provider(None)
    result = run_source_trial(packet, gold, expected, store, provider=provider)
    assert provider.calls == 1
    assert ExtractionResult.model_validate(result["result"]).status == "provider_failed"
    assert CaseGrade.model_validate(result["grade"]).matched_fields == 0


def test_cli_does_not_create_a_missing_output_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The single-case command must use the caller's already populated owned directory."""
    missing = tmp_path / "missing"
    assert (
        main(
            [
                "--packet",
                "absent",
                "--gold",
                "absent",
                "--expected-request",
                "absent",
                "--output",
                str(missing),
            ]
        )
        == 1
    )
    assert not missing.exists()
    output = capsys.readouterr()
    assert not output.out and str(missing) not in output.err


@pytest.mark.parametrize("invalid", ["duplicate", "missing", "request_size", "request_type"])
def test_invalid_files_and_reference_scope_stop_before_delivery(
    tmp_path: Path, invalid: str
) -> None:
    """Duplicate keys, absent metadata and overbroad references cannot admit a trial."""
    packet, gold, expected, store, _ = inputs(tmp_path)
    if invalid == "duplicate":
        packet.write_text('{"paper_id":"x","paper_id":"y"}')
    elif invalid == "missing":
        gold.unlink()
    else:
        value = json.loads(expected.read_bytes())
        value["size_bytes" if invalid == "request_size" else "media_type"] = (
            24577 if invalid == "request_size" else "text/plain"
        )
        expected.write_text(json.dumps(value))
    provider = Provider(None)
    with pytest.raises(ResearchError):
        run_source_trial(packet, gold, expected, store, provider=provider)
    assert provider.calls == 0


def test_oversized_prompt_cannot_start_provider_work(tmp_path: Path) -> None:
    """Source page admission is wider than the provider prompt field; both bounds must apply."""
    packet, gold, expected, store, _ = inputs(tmp_path)
    value = json.loads(packet.read_bytes())
    value["pages"][0]["artifact"] = store.put(b"x" * 40000).model_dump(mode="json")
    packet.write_text(json.dumps(value))
    provider = Provider(None)
    with pytest.raises(ResearchError, match="provider admission"):
        run_source_trial(packet, gold, expected, store, provider=provider)
    assert provider.calls == 0


@pytest.mark.parametrize("failure", ["no_module_file", "oversized", "encoding"])
def test_source_snapshot_failure_prevents_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """A trial cannot deliver first and later discover that its code provenance is missing."""
    from types import SimpleNamespace

    packet, gold, expected, store, _ = inputs(tmp_path)
    path = tmp_path / "source.py"
    path.write_bytes(b"x" * (1024 * 1024 + 1) if failure == "oversized" else b"\xff")
    module = SimpleNamespace(__file__=None if failure == "no_module_file" else str(path))
    monkeypatch.setattr(
        "factorforge.evaluation.source_trial.importlib.import_module", lambda name: module
    )
    provider = Provider(None)
    with pytest.raises(ResearchError) as rejected:
        run_source_trial(packet, gold, expected, store, provider=provider)
    assert rejected.value.code == "SOURCE_TRIAL_LINEAGE_INVALID"
    assert provider.calls == 0


def test_cli_success_and_fatal_failure_are_safe_and_single_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Injected delivery covers CLI output without contacting the default loopback service."""
    from factorforge.evaluation import source_trial

    packet, gold, expected, store, answer = inputs(tmp_path)
    provider = Provider(answer.expected.model_dump_json())
    monkeypatch.setattr(source_trial, "OllamaProvider", lambda: provider)
    arguments = [
        "--packet",
        str(packet),
        "--gold",
        str(gold),
        "--expected-request",
        str(expected),
        "--output",
        str(store.root),
    ]
    assert main(arguments) == 0 and provider.calls == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["grade"]["matched_fields"] == 9 and not output.err
    provider.fatal = True
    assert main(arguments) == 1 and provider.calls == 2
    output = capsys.readouterr()
    assert not output.out and "private-token" not in output.err
    event = json.loads(output.err)["error"]
    assert store.get(ArtifactRef.model_validate(event["trial_failure_record"]))


def test_unavailable_failure_store_does_not_mask_original_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A storage outage can leave only the start record; the original failure still propagates."""
    from factorforge.evaluation import source_trial

    packet, gold, expected, store, _ = inputs(tmp_path)
    from factorforge.evaluation.cli import _save as save

    def fail_event(target: ArtifactStore, value: object) -> ArtifactRef:
        """Fail only after a retained start and an attempted provider invocation."""
        if isinstance(value, dict) and value.get("schema_version") == "source-trial-failure-v1":
            raise OSError("private-storage-path")
        return save(target, value)

    monkeypatch.setattr(source_trial, "_save", fail_event)
    provider = Provider(None, fatal=True)
    with pytest.raises(RuntimeError) as original:
        run_source_trial(packet, gold, expected, store, provider=provider)
    assert provider.calls == 1
    assert getattr(original.value, "trial_start_record", None) is not None
    assert getattr(original.value, "trial_failure_record", None) is None
    assert "Failure event unavailable" in original.value.__notes__[0]


def test_constructor_failure_has_zero_call_failure_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unexpected adapter-construction failure after admission keeps the start association."""
    from factorforge.evaluation import source_trial

    packet, gold, expected, store, _ = inputs(tmp_path)

    def fail_constructor() -> None:
        """Fail before provider invocation, without any external access."""
        raise RuntimeError("private-constructor-state")

    monkeypatch.setattr(source_trial, "OllamaProvider", fail_constructor)
    with pytest.raises(RuntimeError) as original:
        run_source_trial(packet, gold, expected, store)
    ref = getattr(original.value, "trial_failure_record", None)
    assert isinstance(ref, ArtifactRef)
    assert json.loads(store.get(ref))["provider_invocations"] == 0


def test_delivery_guard_rejects_drift_and_second_invocation(tmp_path: Path) -> None:
    """A second boundary check protects exact wire identity even if the extractor later changes."""
    from factorforge.evaluation.source_trial import _FrozenProvider

    _, _, expected, store, _ = inputs(tmp_path)
    ref = ArtifactRef.model_validate_json(expected.read_bytes())
    request = GenerationRequest(
        model="llama3.1:8b", system="changed", user="changed", response_schema={}
    )
    provider = Provider(None)
    guard = _FrozenProvider(provider, store.get(ref))
    with pytest.raises(ResearchError, match="changed"):
        guard.generate(request, store)
    guard.expected = _request_payload(request)[1]
    guard.invocations = 1
    with pytest.raises(ResearchError, match="second"):
        guard.generate(request, store)
    assert provider.calls == 0


def test_module_help_exits_without_provider_invocation() -> None:
    """The real module entry point can be discovered without admitting an extraction trial."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "factorforge.evaluation.source_trial", "--help"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert "--expected-request" in result.stdout
