"""Configuration cannot infer authorization from database credentials or an environment label."""

import pytest

from factorforge.api.settings import Settings


def test_default_and_explicit_local_modes() -> None:
    """The deployment label is metadata, while only the explicit mode authorizes local access."""
    assert Settings.from_environment({"FACTORFORGE_ENV": "local"}).mode == "disabled"
    local = Settings.from_environment({"FACTORFORGE_MODE": "local"})
    assert (local.mode, local.storage) == ("local", "memory")


@pytest.mark.parametrize(
    "values",
    [
        {"FACTORFORGE_MODE": "unknown"},
        {"FACTORFORGE_MODE": "local", "FACTORFORGE_STORAGE": "postgres"},
        {"FACTORFORGE_MODE": "cognito", "FACTORFORGE_STORAGE": "memory"},
        {"FACTORFORGE_MODE": "cognito", "RDS_DSN": "secret"},
        {"FACTORFORGE_MODE": "local", "FACTORFORGE_ALLOWED_ORIGIN": "https://example.com/path"},
    ],
)
def test_invalid_configuration_fails_closed(values: dict[str, str]) -> None:
    """Missing identity or durable configuration cannot silently choose an easier backend."""
    with pytest.raises(ValueError):
        Settings.from_environment(values)


def test_secret_configuration_is_not_in_repr() -> None:
    """Diagnostics may print settings, so database credentials must remain redacted."""
    settings = Settings.from_environment(
        {
            "FACTORFORGE_MODE": "local",
            "FACTORFORGE_STORAGE": "postgres",
            "RDS_DSN": "credential-sentinel",
        }
    )
    assert "credential-sentinel" not in repr(settings)
