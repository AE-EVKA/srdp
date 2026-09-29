"""Idempotent Postgres database/role bootstrap for a fresh or existing SRDP deployment.

The databases to create are declared in the ``[setup]`` table of ``srdp.toml``
(``CONFIG_PATH``), the central platform config (#42). On Compose that is the
repo-root ``srdp.toml``, mounted into the container. On Kubernetes the chart
renders the same table from its ``setup.databases`` value. Only the ``[setup]``
table is read, so the rest of the file can grow without touching this service.
Role passwords come from ``SETUP_PASSWORDS__<ROLE>`` env vars, keyed by role
name, since ``srdp.toml`` never holds secrets.

This is the only mechanism that creates these databases on either target.
On Compose it runs before every service that needs Postgres, gated with
``depends_on: condition: service_completed_successfully``. On Kubernetes it's
a ``post-install``/``post-upgrade`` hook Job, and each consumer's
``wait-for-*-db`` init container blocks until its database exists.

Every run reconciles role passwords too, so rotating a password (or migrating
a deployment whose role predates the configured password) only needs a rerun.
"""

import logging
import time
from pathlib import Path

import psycopg2
import psycopg2.extensions
from psycopg2 import sql
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("/etc/srdp/srdp.toml")


class DatabaseTarget(BaseModel):
    """One database (and optionally its own role) the setup service ensures exists."""

    name: str
    # None reuses the superuser as owner (DuckLake connects as the superuser).
    role: str | None = None
    # False leaves the target to another owner, e.g. the Bitnami subchart's
    # auth.* fields own zitadel's role/database on Kubernetes.
    enabled: bool = True


class SetupSettings(BaseSettings):
    """Superuser connection, database targets, and per-role passwords."""

    model_config = SettingsConfigDict(
        env_prefix="SETUP_",
        env_nested_delimiter="__",
        toml_file=CONFIG_PATH,
        toml_table_header=("setup",),
        extra="ignore",
    )

    pg_host: str = Field(default="postgres")
    pg_port: int = Field(default=5432)
    pg_user: str = Field(default="postgres")
    pg_password: SecretStr = Field(validation_alias="POSTGRES_PASSWORD")
    databases: list[DatabaseTarget]
    # Keyed by role name, e.g. SETUP_PASSWORDS__MARQUEZ -> passwords["marquez"].
    passwords: dict[str, SecretStr] = Field(default_factory=dict)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003 -- fixed hook signature
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003 -- fixed hook signature
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read init kwargs, then env vars, then the TOML config file."""
        return (init_settings, env_settings, TomlConfigSettingsSource(settings_cls))

    @model_validator(mode="after")
    def _check_targets(self) -> "SetupSettings":
        names = [target.name for target in self.databases]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            msg = f"Duplicate database names in setup config: {', '.join(duplicates)}."
            raise ValueError(msg)

        missing = sorted(
            target.role
            for target in self.databases
            if target.enabled
            and target.role is not None
            and not (target.role in self.passwords and self.passwords[target.role].get_secret_value())
        )
        if missing:
            env_vars = ", ".join(f"SETUP_PASSWORDS__{role.upper()}" for role in missing)
            msg = f"No password set for enabled role(s) {', '.join(missing)}. Set {env_vars}."
            raise ValueError(msg)
        return self


def _role_exists(cur: psycopg2.extensions.cursor, role: str) -> bool:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    return cur.fetchone() is not None


def _database_exists(cur: psycopg2.extensions.cursor, database: str) -> bool:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
    return cur.fetchone() is not None


def ensure_target(cur: psycopg2.extensions.cursor, target: DatabaseTarget, settings: SetupSettings) -> None:
    """Idempotently create one target's role (if any) and database, and reconcile the role's password.

    Args:
        cur: An autocommit cursor connected as the Postgres superuser.
        target: The database (and optional role) to ensure exists.
        settings: Validated settings, holding the role's password.
    """
    if target.role is not None:
        password = settings.passwords[target.role].get_secret_value()
        role = sql.Identifier(target.role)
        if _role_exists(cur, target.role):
            cur.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD %s").format(role), (password,))
            logger.info("Role '%s' already exists, password reconciled.", target.role)
        else:
            cur.execute(sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD %s").format(role), (password,))
            logger.info("Created role '%s'.", target.role)

    if _database_exists(cur, target.name):
        logger.info("Database '%s' already exists.", target.name)
        return

    owner = target.role or settings.pg_user
    cur.execute(
        sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(target.name), sql.Identifier(owner)),
    )
    logger.info("Created database '%s' (owner '%s').", target.name, owner)


def _connect_with_retry(
    settings: SetupSettings, max_attempts: int = 10, delay_seconds: float = 3.0
) -> psycopg2.extensions.connection:
    """Connect to Postgres, retrying while it's still starting up.

    On Kubernetes this Job runs as a post-install/post-upgrade hook: the
    Postgres resource exists by then, but its pod may not be accepting
    connections yet. Retrying here (rather than relying solely on the Job's
    own `backoffLimit`/pod restarts) avoids CrashLoopBackOff noise and is
    more forgiving of slow-starting clusters (PVC provisioning, cold pulls).

    Args:
        settings: Superuser connection settings.
        max_attempts: How many times to try before giving up.
        delay_seconds: Delay between attempts.

    Returns:
        An open connection.
    """
    last_error: psycopg2.OperationalError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return psycopg2.connect(
                host=settings.pg_host,
                port=settings.pg_port,
                user=settings.pg_user,
                password=settings.pg_password.get_secret_value(),
                dbname="postgres",
            )
        except psycopg2.OperationalError as exc:
            last_error = exc
            logger.warning("Postgres not ready yet (attempt %d/%d): %s", attempt, max_attempts, exc)
            time.sleep(delay_seconds)
    assert last_error is not None  # noqa: S101 -- loop always sets it before exhausting attempts
    raise last_error


def bootstrap_databases(settings: SetupSettings | None = None) -> None:
    """Ensure every enabled target database (and its role) exists, idempotently.

    Settings are validated before connecting, so a missing password fails the
    run before anything is created.

    Args:
        settings: Setup settings. Loaded from the environment and the TOML
            config file if not provided.
    """
    if settings is None:
        settings = SetupSettings()  # ty: ignore[missing-argument]

    conn = _connect_with_retry(settings)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for target in settings.databases:
                if not target.enabled:
                    logger.info("Skipping '%s', disabled in setup config.", target.name)
                    continue
                ensure_target(cur, target, settings)
    finally:
        conn.close()
