"""Replay a bounded original-fixture data check from verified bytes, never from saved code."""

import hashlib
import json
import os
import platform
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Literal

import pydantic
import pydantic_core
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, ValidationError

from factorforge import __version__
from factorforge.data.artifacts import ArtifactStore
from factorforge.data.point_in_time import (
    FundamentalFact,
    MembershipEvent,
    select_facts,
    select_universe,
    validate_decision_time,
)
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.datasets import DatasetManifest, DatasetObject, UsageRights
from factorforge.domain.errors import ResearchError

MAX_COMPONENT_BYTES = 2 * 2**20
FIXTURE_PATH = "data/fixtures/tiny-market-v1.json"
# This command grants reuse only for the reviewed original fixture and its authored terms.
# A future fixture revision must update its version and these identities through review.
FIXTURE_SHA256 = "f0f075c544a78fa99ce27dadf615b5fc4d6bd68f0ebe7268591cdcc75ac4e36b"
TERMS_UTF8_LF_SHA256 = "b6c5eda55e023a53c2f6a48a0777b9ab99ab2cb87b8bc00e02fb175faba4946e"
CODE_PATHS = {
    "point_in_time.py": "src/factorforge/data/point_in_time.py",
    "fixture_bundle.py": "src/factorforge/data/fixture_bundle.py",
    "datasets.py": "src/factorforge/domain/datasets.py",
    "domain_artifacts.py": "src/factorforge/domain/artifacts.py",
    "artifacts.py": "src/factorforge/data/artifacts.py",
    "errors.py": "src/factorforge/domain/errors.py",
    "cli.py": "src/factorforge/cli.py",
    "__init__.py": "src/factorforge/__init__.py",
}


class _StrictModel(BaseModel):
    """Saved contracts forbid undeclared fields and coercion of JSON primitives."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FixtureSource(_StrictModel):
    """Metadata identifies authored coverage and policies without inferring market observations."""

    name: str
    origin: str
    purpose: str
    trading_dates: list[date] = Field(min_length=1, max_length=1000)
    timestamp_zone: Literal["UTC"]
    price_policy: str
    availability_policy: str
    membership_interval_policy: str
    missing_terminal_policy: str


class FixtureRights(_StrictModel):
    """Preserve the fixture's explicit permission and limited scope alongside its original bytes."""

    permission: str
    scope: str
    attribution: str
    retention: str


type Rows = Annotated[list[dict[str, JsonValue]], Field(max_length=1000)]


class FixtureInput(_StrictModel):
    """Only facts and membership are interpreted; all other source tables remain preserved."""

    schema_version: Literal["tiny-market-v1"]
    tier: Literal["original_fixture"]
    source: FixtureSource
    license_notes: FixtureRights
    security_history: Rows
    membership: list[MembershipEvent] = Field(max_length=1000)
    facts: list[FundamentalFact] = Field(max_length=1000)
    prices: Rows
    corporate_actions: Rows
    exits: Rows


class FixtureConfig(_StrictModel):
    """Formation admits equal availability; trading must occur strictly later in absolute time."""

    schema_version: Literal["fixture-selection-v1"] = "fixture-selection-v1"
    formation_at: AwareDatetime
    trade_at: AwareDatetime


class FixtureResult(_StrictModel):
    """A data-selection result makes no return, backtest or research-completion claim."""

    tier: Literal["original_fixture"] = "original_fixture"
    universe: list[str] = Field(max_length=1000)
    facts: list[FundamentalFact] = Field(max_length=1000)


class FixtureEnvironment(_StrictModel):
    """Capture the installed versions that interpret JSON, dates, decimals and selection code."""

    python: str
    implementation: str
    pydantic: str
    pydantic_core: str
    factorforge: str


class GitState(_StrictModel):
    """An actual repository revision is optional; unavailable Git metadata stays unknown."""

    revision: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")] | None
    dirty: bool | None


class FixtureBundle(_StrictModel):
    """A small fixed graph of artifact references binds input, interpretation and replay output."""

    schema_version: Literal["fixture-bundle-v1"] = "fixture-bundle-v1"
    tier: Literal["original_fixture"] = "original_fixture"
    text_identity: Literal["utf8-lf-v1"] = "utf8-lf-v1"
    input: ArtifactRef
    terms: ArtifactRef
    manifest: ArtifactRef
    config: ArtifactRef
    result: ArtifactRef
    code: dict[str, ArtifactRef] = Field(max_length=16)
    lock: ArtifactRef
    environment: ArtifactRef
    git: ArtifactRef


def _error(message: str, code: str = "BUNDLE_INVALID") -> ResearchError:
    """Expose actionable bundle failures without echoing input bytes or host paths."""
    return ResearchError(code, message, 422)


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    """Duplicate JSON keys create ambiguous lineage and must not silently keep the last value."""
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    """Nonfinite JSON literals are not portable saved values."""
    raise ValueError("Invalid JSON constant")


def _check_depth(value: JsonValue, depth: int = 0) -> None:
    """Keep nested unconsumed fixture fields below one portable JSON depth budget."""
    if depth > 32:
        raise ValueError("JSON depth limit exceeded")
    if isinstance(value, dict):
        for child in value.values():
            _check_depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _check_depth(child, depth + 1)


def parse_saved[Model: BaseModel](data: bytes, model: type[Model]) -> Model:
    """Bound bytes and JSON depth through strict validation before any stored value is used."""
    if len(data) > MAX_COMPONENT_BYTES:
        raise _error("Bundle component exceeds the byte limit.")
    try:
        value = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
        _check_depth(value)
        return model.model_validate_json(data, strict=True)
    except (ValueError, ValidationError, RecursionError, OverflowError):
        raise _error("Bundle component has an invalid schema.") from None


def _bytes(model: BaseModel) -> bytes:
    """Canonical validated JSON gives equivalent saved metadata one byte identity."""
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()


def _read_file(path: Path) -> bytes:
    """Trusted checkout files still have finite memory use and sanitized missing-file errors."""
    try:
        with path.open("rb") as source:
            data = source.read(MAX_COMPONENT_BYTES + 1)
    except OSError:
        raise _error("Required trusted repository file is unavailable.") from None
    if len(data) > MAX_COMPONENT_BYTES:
        raise _error("Trusted repository file exceeds the byte limit.")
    return data


def _get(store: ArtifactStore, ref: ArtifactRef) -> bytes:
    """Apply the smaller bundle bound before allowing an artifact store to allocate content."""
    if ref.size_bytes > MAX_COMPONENT_BYTES:
        raise _error("Bundle component exceeds the byte limit.")
    return store.get(ref)


def _canonical_text(data: bytes) -> bytes:
    """Normalize declared UTF-8 text without changing raw input or saved terms identities."""
    try:
        return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode()
    except UnicodeDecodeError:
        raise _error("Trusted code or lock file is not UTF-8.", "BUNDLE_CODE") from None


def _canonical_file(path: Path) -> bytes:
    """UTF-8/LF code and lock identities survive Git checkout newline conversion explicitly."""
    return _canonical_text(_read_file(path))


def _authorized_fixture(source: bytes, terms: bytes) -> None:
    """A fixture label cannot grant rights to changed data or altered permission text."""
    if (
        hashlib.sha256(source).hexdigest() != FIXTURE_SHA256
        or hashlib.sha256(_canonical_text(terms)).hexdigest() != TERMS_UTF8_LF_SHA256
    ):
        raise _error(
            "Fixture content or terms differ from the authorized version.", "BUNDLE_SOURCE"
        )


def _environment() -> FixtureEnvironment:
    """Record installed libraries rather than assuming the lock file describes the interpreter."""
    return FixtureEnvironment(
        python=platform.python_version(),
        implementation=platform.python_implementation(),
        pydantic=pydantic.__version__,
        pydantic_core=pydantic_core.__version__,
        factorforge=__version__,
    )


def _git_state(repository: Path) -> GitState:
    """Snapshot actual HEAD and working-tree state without persisting filenames or inventing IDs."""
    try:
        environment = {
            key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
        }
        top = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            env=environment,
        ).stdout.strip()
        if Path(top).resolve() != repository.resolve():
            return GitState(revision=None, dirty=None)
        revision = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "--verify", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            env=environment,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(repository), "status", "--porcelain", "--untracked-files=normal"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            env=environment,
        ).stdout
        return GitState(revision=revision, dirty=bool(status))
    except (OSError, subprocess.SubprocessError, ValidationError):
        return GitState(revision=None, dirty=None)


def _trusted_code(repository: Path) -> dict[str, bytes]:
    """The supplied checkout must match the executing installed package, never saved code."""
    package = Path(__file__).resolve().parents[1]
    result = {}
    for name, relative in CODE_PATHS.items():
        data = _canonical_file(repository / relative)
        installed = _canonical_file(package / relative.removeprefix("src/factorforge/"))
        if data != installed:
            raise _error("Trusted checkout code differs from the installed package.", "BUNDLE_CODE")
        result[name] = data
    return result


def _select(source: FixtureInput, config: FixtureConfig) -> FixtureResult:
    """Selection uses saved times and historical membership while retaining all input elsewhere."""
    universe = select_universe(source.membership, config.formation_at, config.trade_at)
    facts = select_facts(source.facts, config.formation_at, config.trade_at)
    return FixtureResult(
        universe=list(universe), facts=[row for row in facts if row.security_id in universe]
    )


def _manifest_model(
    source: FixtureInput, ref: ArtifactRef, retrieved_at: datetime
) -> DatasetManifest:
    """Describe authored fixture coverage and permission without claiming observed market data."""
    return DatasetManifest(
        name="tiny-market",
        kind="original_fixture",
        provider=source.source.name,
        source_version=source.schema_version,
        retrieved_at=retrieved_at,
        coverage_start=min(source.source.trading_dates),
        coverage_end=max(source.source.trading_dates),
        security_id_namespace="fixture-stable-security-id",
        universe_policy="known-effective-events",
        availability_policy="explicit-authored-timestamps",
        corporate_action_policy="unadjusted-explicit-events",
        delisting_policy="unknown-terminal-value-blocks-accounting",
        rights=UsageRights(
            provenance=source.source.origin,
            terms_reference="data/fixtures/README.md",
            permitted_uses=("local_research", "public_demo", "redistribution"),
        ),
        objects=(
            DatasetObject(
                name="tiny-market",
                schema_version=source.schema_version,
                row_count=sum(
                    len(getattr(source, name))
                    for name in (
                        "security_history",
                        "membership",
                        "facts",
                        "prices",
                        "corporate_actions",
                        "exits",
                    )
                ),
                artifact=ref,
            ),
        ),
    )


def _manifest(source: FixtureInput, ref: ArtifactRef, retrieved_at: datetime) -> DatasetManifest:
    """Translate metadata constraints without leaking Pydantic's echoed source values."""
    try:
        return _manifest_model(source, ref, retrieved_at)
    except ValidationError:
        raise _error("Fixture metadata does not satisfy the dataset manifest schema.") from None


def create_fixture_bundle(
    store: ArtifactStore,
    *,
    repository: Path,
    formation_at: datetime = datetime(2024, 5, 1, 20, tzinfo=UTC),
    trade_at: datetime = datetime(2024, 5, 2, 13, 30, tzinfo=UTC),
) -> ArtifactRef:
    """Capture an original fixture and its exact replay dependencies, with honest Git metadata."""
    validate_decision_time(formation_at, trade_at)
    config = FixtureConfig(
        formation_at=formation_at.astimezone(UTC), trade_at=trade_at.astimezone(UTC)
    )
    source_bytes = _read_file(repository / FIXTURE_PATH)
    source = parse_saved(source_bytes, FixtureInput)
    terms_bytes = _read_file(repository / "data/fixtures/README.md")
    _authorized_fixture(source_bytes, terms_bytes)
    code = _trusted_code(repository)
    result = _select(source, config)
    input_ref = store.put(source_bytes, media_type="application/json")
    manifest = _manifest(source, input_ref, datetime.now(UTC))
    bundle = FixtureBundle(
        input=input_ref,
        terms=store.put(terms_bytes, media_type="text/markdown"),
        manifest=store.put(manifest.canonical_bytes(), media_type="application/json"),
        config=store.put(_bytes(config), media_type="application/json"),
        result=store.put(_bytes(result), media_type="application/json"),
        code={name: store.put(data, media_type="text/x-python") for name, data in code.items()},
        lock=store.put(_canonical_file(repository / "uv.lock"), media_type="text/plain"),
        environment=store.put(_bytes(_environment()), media_type="application/json"),
        git=store.put(_bytes(_git_state(repository)), media_type="application/json"),
    )
    return store.put(_bytes(bundle), media_type="application/json")


def verify_fixture_bundle(
    store: ArtifactStore,
    ref: ArtifactRef,
    *,
    repository: Path,
) -> dict[str, JsonValue]:
    """Verify every component and replay with current trusted code; never import saved artifacts."""
    bundle = parse_saved(_get(store, ref), FixtureBundle)
    code = _trusted_code(repository)
    if set(bundle.code) != set(code):
        raise _error("Bundle code inventory does not match trusted code.", "BUNDLE_CODE")
    for name, data in code.items():
        if _get(store, bundle.code[name]) != data:
            raise _error("Bundle code does not match trusted code.", "BUNDLE_CODE")
    if _get(store, bundle.lock) != _canonical_file(repository / "uv.lock"):
        raise _error("Bundle dependency lock differs from the trusted lock.", "BUNDLE_ENVIRONMENT")
    if parse_saved(_get(store, bundle.environment), FixtureEnvironment) != _environment():
        raise _error(
            "Bundle environment differs from the installed environment.", "BUNDLE_ENVIRONMENT"
        )
    parse_saved(_get(store, bundle.git), GitState)
    terms_bytes = _get(store, bundle.terms)
    source_bytes = _get(store, bundle.input)
    source = parse_saved(source_bytes, FixtureInput)
    _authorized_fixture(source_bytes, terms_bytes)
    manifest = parse_saved(_get(store, bundle.manifest), DatasetManifest)
    if manifest != _manifest(source, bundle.input, manifest.retrieved_at):
        raise _error("Bundle dataset manifest does not describe its input.")
    config = parse_saved(_get(store, bundle.config), FixtureConfig)
    result = parse_saved(_get(store, bundle.result), FixtureResult)
    reproduced = _select(source, config)
    if result != reproduced:
        raise _error("Saved result does not reproduce under trusted selection.", "BUNDLE_REPLAY")
    return reproduced.model_dump(mode="json")
