from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Comparison(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    COMPARISON_UNSPECIFIED: _ClassVar[Comparison]
    COMPARISON_EXACT_NAV: _ClassVar[Comparison]

class Outcome(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    OUTCOME_UNSPECIFIED: _ClassVar[Outcome]
    OUTCOME_UNSUPPORTED: _ClassVar[Outcome]
    OUTCOME_UNAVAILABLE: _ClassVar[Outcome]
    OUTCOME_DEADLINE: _ClassVar[Outcome]
    OUTCOME_ENGINE_FAILED: _ClassVar[Outcome]
    OUTCOME_DISAGREED: _ClassVar[Outcome]
    OUTCOME_VERIFIED: _ClassVar[Outcome]
    OUTCOME_CANCELLED: _ClassVar[Outcome]
    OUTCOME_BUSY: _ClassVar[Outcome]
COMPARISON_UNSPECIFIED: Comparison
COMPARISON_EXACT_NAV: Comparison
OUTCOME_UNSPECIFIED: Outcome
OUTCOME_UNSUPPORTED: Outcome
OUTCOME_UNAVAILABLE: Outcome
OUTCOME_DEADLINE: Outcome
OUTCOME_ENGINE_FAILED: Outcome
OUTCOME_DISAGREED: Outcome
OUTCOME_VERIFIED: Outcome
OUTCOME_CANCELLED: Outcome
OUTCOME_BUSY: Outcome

class ArtifactReference(_message.Message):
    __slots__ = ("sha256", "size_bytes", "media_type")
    SHA256_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    sha256: str
    size_bytes: int
    media_type: str
    def __init__(self, sha256: _Optional[str] = ..., size_bytes: _Optional[int] = ..., media_type: _Optional[str] = ...) -> None: ...

class HealthRequest(_message.Message):
    __slots__ = ("wire_version",)
    WIRE_VERSION_FIELD_NUMBER: _ClassVar[int]
    wire_version: str
    def __init__(self, wire_version: _Optional[str] = ...) -> None: ...

class HealthResponse(_message.Message):
    __slots__ = ("wire_version", "alive", "engine_ready")
    WIRE_VERSION_FIELD_NUMBER: _ClassVar[int]
    ALIVE_FIELD_NUMBER: _ClassVar[int]
    ENGINE_READY_FIELD_NUMBER: _ClassVar[int]
    wire_version: str
    alive: bool
    engine_ready: bool
    def __init__(self, wire_version: _Optional[str] = ..., alive: _Optional[bool] = ..., engine_ready: _Optional[bool] = ...) -> None: ...

class CapabilitiesRequest(_message.Message):
    __slots__ = ("wire_version",)
    WIRE_VERSION_FIELD_NUMBER: _ClassVar[int]
    wire_version: str
    def __init__(self, wire_version: _Optional[str] = ...) -> None: ...

class CapabilitiesResponse(_message.Message):
    __slots__ = ("wire_version", "declared_profiles", "ready_profiles", "unsupported_features", "max_message_bytes", "max_inflight", "max_deadline_seconds")
    WIRE_VERSION_FIELD_NUMBER: _ClassVar[int]
    DECLARED_PROFILES_FIELD_NUMBER: _ClassVar[int]
    READY_PROFILES_FIELD_NUMBER: _ClassVar[int]
    UNSUPPORTED_FEATURES_FIELD_NUMBER: _ClassVar[int]
    MAX_MESSAGE_BYTES_FIELD_NUMBER: _ClassVar[int]
    MAX_INFLIGHT_FIELD_NUMBER: _ClassVar[int]
    MAX_DEADLINE_SECONDS_FIELD_NUMBER: _ClassVar[int]
    wire_version: str
    declared_profiles: _containers.RepeatedScalarFieldContainer[str]
    ready_profiles: _containers.RepeatedScalarFieldContainer[str]
    unsupported_features: _containers.RepeatedScalarFieldContainer[str]
    max_message_bytes: int
    max_inflight: int
    max_deadline_seconds: int
    def __init__(self, wire_version: _Optional[str] = ..., declared_profiles: _Optional[_Iterable[str]] = ..., ready_profiles: _Optional[_Iterable[str]] = ..., unsupported_features: _Optional[_Iterable[str]] = ..., max_message_bytes: _Optional[int] = ..., max_inflight: _Optional[int] = ..., max_deadline_seconds: _Optional[int] = ...) -> None: ...

class VerifyStrategyRequest(_message.Message):
    __slots__ = ("schema_version", "verification_id", "run_id", "owner_issuer", "owner_subject", "factor_spec_sha256", "profile", "source", "reference", "comparison")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    VERIFICATION_ID_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    OWNER_ISSUER_FIELD_NUMBER: _ClassVar[int]
    OWNER_SUBJECT_FIELD_NUMBER: _ClassVar[int]
    FACTOR_SPEC_SHA256_FIELD_NUMBER: _ClassVar[int]
    PROFILE_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    REFERENCE_FIELD_NUMBER: _ClassVar[int]
    COMPARISON_FIELD_NUMBER: _ClassVar[int]
    schema_version: str
    verification_id: str
    run_id: str
    owner_issuer: str
    owner_subject: str
    factor_spec_sha256: str
    profile: str
    source: ArtifactReference
    reference: ArtifactReference
    comparison: Comparison
    def __init__(self, schema_version: _Optional[str] = ..., verification_id: _Optional[str] = ..., run_id: _Optional[str] = ..., owner_issuer: _Optional[str] = ..., owner_subject: _Optional[str] = ..., factor_spec_sha256: _Optional[str] = ..., profile: _Optional[str] = ..., source: _Optional[_Union[ArtifactReference, _Mapping]] = ..., reference: _Optional[_Union[ArtifactReference, _Mapping]] = ..., comparison: _Optional[_Union[Comparison, str]] = ...) -> None: ...

class NavPoint(_message.Message):
    __slots__ = ("at_utc", "nav_usd")
    AT_UTC_FIELD_NUMBER: _ClassVar[int]
    NAV_USD_FIELD_NUMBER: _ClassVar[int]
    at_utc: str
    nav_usd: str
    def __init__(self, at_utc: _Optional[str] = ..., nav_usd: _Optional[str] = ...) -> None: ...

class VerifyStrategyResponse(_message.Message):
    __slots__ = ("outcome", "request_sha256", "failure_code", "record", "observed_nav", "engine_image_sha256", "translator_sha256", "lean_commit")
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    REQUEST_SHA256_FIELD_NUMBER: _ClassVar[int]
    FAILURE_CODE_FIELD_NUMBER: _ClassVar[int]
    RECORD_FIELD_NUMBER: _ClassVar[int]
    OBSERVED_NAV_FIELD_NUMBER: _ClassVar[int]
    ENGINE_IMAGE_SHA256_FIELD_NUMBER: _ClassVar[int]
    TRANSLATOR_SHA256_FIELD_NUMBER: _ClassVar[int]
    LEAN_COMMIT_FIELD_NUMBER: _ClassVar[int]
    outcome: Outcome
    request_sha256: str
    failure_code: str
    record: ArtifactReference
    observed_nav: _containers.RepeatedCompositeFieldContainer[NavPoint]
    engine_image_sha256: str
    translator_sha256: str
    lean_commit: str
    def __init__(self, outcome: _Optional[_Union[Outcome, str]] = ..., request_sha256: _Optional[str] = ..., failure_code: _Optional[str] = ..., record: _Optional[_Union[ArtifactReference, _Mapping]] = ..., observed_nav: _Optional[_Iterable[_Union[NavPoint, _Mapping]]] = ..., engine_image_sha256: _Optional[str] = ..., translator_sha256: _Optional[str] = ..., lean_commit: _Optional[str] = ...) -> None: ...
