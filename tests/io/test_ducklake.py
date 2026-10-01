import duckdb
import pytest
from pydantic import ValidationError

from srdp.io.ducklake import DuckLakeSettings, LocalStorageBackend, S3StorageBackend, get_storage_backend

S3_SETTINGS = {
    "storage_backend": "s3",
    "s3_bucket": "lake",
    "s3_prefix": "dev",
    "s3_endpoint": "s3.nl-ams.scw.cloud",
    "s3_url_style": "path",
    "s3_region": "nl-ams",
    "s3_key_id": "SCWREADER",
    "s3_secret": "reader-secret",
}


def _settings(**overrides) -> DuckLakeSettings:
    return DuckLakeSettings(_env_file=None, pg_password="pw", **overrides)  # noqa: S106 — throwaway test value


def test_local_is_the_default_backend(tmp_path):
    backend = get_storage_backend(_settings(data_path=str(tmp_path / "lake")))

    assert isinstance(backend, LocalStorageBackend)
    assert backend.get_base_path() == str(tmp_path / "lake")


def test_s3_backend_stores_the_lake_under_bucket_and_prefix():
    backend = get_storage_backend(_settings(**S3_SETTINGS))

    assert isinstance(backend, S3StorageBackend)
    assert backend.get_base_path() == "s3://lake/dev/"


@pytest.mark.parametrize("field", ["s3_bucket", "s3_endpoint", "s3_url_style", "s3_region", "s3_key_id", "s3_secret"])
def test_s3_refuses_to_start_without_a_required_setting(field):
    incomplete = {k: v for k, v in S3_SETTINGS.items() if k != field}

    with pytest.raises(ValidationError, match=f"DUCKLAKE_{field.upper()}"):
        _settings(**incomplete)


@pytest.mark.parametrize("field", ["s3_bucket", "s3_endpoint", "s3_region", "s3_key_id", "s3_secret"])
def test_s3_treats_an_empty_setting_as_missing(field):
    """Compose's ``${VAR:-}`` passes an empty string; DuckDB would read it as "use the AWS default"."""
    with pytest.raises(ValidationError, match=f"DUCKLAKE_{field.upper()}"):
        _settings(**{**S3_SETTINGS, field: ""})


@pytest.mark.parametrize(("prefix", "base_path"), [("", "s3://lake/"), ("/dev/", "s3://lake/dev/")])
def test_s3_base_path_without_or_with_slashed_prefix(prefix, base_path):
    backend = get_storage_backend(_settings(**{**S3_SETTINGS, "s3_prefix": prefix}))

    assert backend.get_base_path() == base_path


def test_local_backend_needs_no_s3_settings(tmp_path):
    settings = _settings(data_path=str(tmp_path))

    assert settings.storage_backend == "local"


def _s3_secrets(conn) -> list[dict[str, str]]:
    rows = conn.execute("SELECT secret_string FROM duckdb_secrets() WHERE type = 's3'").fetchall()
    return [dict(pair.split("=", 1) for pair in row[0].split(";")) for row in rows]


def test_s3_connection_gets_a_secret_scoped_to_the_lake():
    conn = duckdb.connect()

    get_storage_backend(_settings(**S3_SETTINGS)).configure_duckdb(conn)

    [secret] = _s3_secrets(conn)
    assert secret["scope"] == "s3://lake/dev/"
    assert secret["endpoint"] == "s3.nl-ams.scw.cloud"
    assert secret["url_style"] == "path"
    assert secret["region"] == "nl-ams"
    assert secret["use_ssl"] == "true"
    assert secret["key_id"] == "SCWREADER"


def test_a_quote_in_a_credential_cannot_break_out_of_the_secret_sql():
    conn = duckdb.connect()

    get_storage_backend(
        _settings(**{**S3_SETTINGS, "s3_key_id": "a'b", "s3_secret": "x'); DROP TABLE t; --"})
    ).configure_duckdb(conn)

    [secret] = _s3_secrets(conn)
    assert secret["key_id"] == "a'b"


def test_dlt_gets_the_same_bucket_endpoint_and_key():
    backend = get_storage_backend(_settings(**{**S3_SETTINGS, "s3_endpoint": "minio:9000", "s3_use_ssl": False}))

    assert backend.dlt_filesystem_config() == {
        "bucket_url": "s3://lake/dev/",
        "credentials": {
            "aws_access_key_id": "SCWREADER",
            "aws_secret_access_key": "reader-secret",
            "endpoint_url": "http://minio:9000",
            "region_name": "nl-ams",
            "s3_url_style": "path",
        },
    }


def test_s3_endpoint_with_a_scheme_is_refused():
    with pytest.raises(ValidationError, match="DUCKLAKE_S3_USE_SSL"):
        _settings(**{**S3_SETTINGS, "s3_endpoint": "https://s3.nl-ams.scw.cloud"})
