"""Tests for the setup service's database bootstrap config and reconciliation."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from pydantic_settings import SettingsConfigDict

from srdp.setup.bootstrap import DatabaseTarget, SetupSettings, ensure_target

CONFIG_TOML = """
[[databases]]
name = "zitadel"
role = "zitadel"
enabled = false

[[databases]]
name = "marquez"
role = "marquez"

[[databases]]
name = "ducklake"
"""


class FakeCursor:
    """Records executed statements and answers existence checks from a fixed set."""

    def __init__(self, existing_roles: set[str], existing_databases: set[str]) -> None:  # noqa: D107
        self.existing_roles = existing_roles
        self.existing_databases = existing_databases
        self.statements: list[str] = []
        self._result: tuple[int] | None = None

    def execute(self, query: object, params: tuple[str, ...] | None = None) -> None:
        """Record the statement and prime `fetchone` for existence checks."""
        text = query if isinstance(query, str) else repr(query)
        self.statements.append(text)
        if "pg_roles" in text:
            self._result = (1,) if params and params[0] in self.existing_roles else None
        elif "pg_database" in text:
            self._result = (1,) if params and params[0] in self.existing_databases else None

    def fetchone(self) -> tuple[int] | None:
        """Return the result of the last existence check."""
        return self._result


@pytest.fixture
def settings_from_toml(tmp_path: Path) -> type[SetupSettings]:
    config = tmp_path / "setup.toml"
    config.write_text(CONFIG_TOML)

    class TomlSettings(SetupSettings):
        model_config = SettingsConfigDict(toml_file=config)

    return TomlSettings


def test_loads_databases_from_toml_and_passwords_from_env(
    settings_from_toml: type[SetupSettings], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SETUP_PASSWORDS__MARQUEZ", "marquez-pw")

    settings = settings_from_toml()  # ty: ignore[missing-argument]

    assert [t.name for t in settings.databases] == ["zitadel", "marquez", "ducklake"]
    assert settings.passwords["marquez"].get_secret_value() == "marquez-pw"


def test_missing_password_for_enabled_role_fails(settings_from_toml: type[SetupSettings]) -> None:
    with pytest.raises(ValidationError, match="SETUP_PASSWORDS__MARQUEZ"):
        settings_from_toml()  # ty: ignore[missing-argument]


def test_empty_password_for_enabled_role_fails(
    settings_from_toml: type[SetupSettings], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SETUP_PASSWORDS__MARQUEZ", "")

    with pytest.raises(ValidationError, match="SETUP_PASSWORDS__MARQUEZ"):
        settings_from_toml()  # ty: ignore[missing-argument]


@pytest.fixture(autouse=True)
def _superuser_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "superuser-pw")


def test_duplicate_database_names_fail() -> None:
    with pytest.raises(ValidationError, match="Duplicate"):
        SetupSettings(  # ty: ignore[missing-argument]
            databases=[DatabaseTarget(name="ducklake"), DatabaseTarget(name="ducklake")],
        )


def _settings(*targets: DatabaseTarget) -> SetupSettings:
    return SetupSettings(  # ty: ignore[missing-argument]
        databases=list(targets),
        passwords={"marquez": SecretStr("marquez-pw")},
    )


def test_existing_role_gets_password_reconciled() -> None:
    target = DatabaseTarget(name="marquez", role="marquez")
    cur = FakeCursor(existing_roles={"marquez"}, existing_databases={"marquez"})

    ensure_target(cur, target, _settings(target))

    assert any("ALTER ROLE" in s for s in cur.statements)
    assert not any("CREATE" in s for s in cur.statements)


def test_missing_role_and_database_are_created() -> None:
    target = DatabaseTarget(name="marquez", role="marquez")
    cur = FakeCursor(existing_roles=set(), existing_databases=set())

    ensure_target(cur, target, _settings(target))

    assert any("CREATE ROLE" in s for s in cur.statements)
    assert any("CREATE DATABASE" in s for s in cur.statements)


def test_roleless_target_is_owned_by_superuser() -> None:
    target = DatabaseTarget(name="ducklake")
    cur = FakeCursor(existing_roles=set(), existing_databases=set())

    ensure_target(cur, target, _settings(target))

    assert not any("ROLE" in s for s in cur.statements)
    assert any("CREATE DATABASE" in s and "'postgres'" in s for s in cur.statements)
