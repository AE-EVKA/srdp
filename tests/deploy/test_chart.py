"""Render the Helm chart with `helm template` and check its contract with the Compose stack."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

CHART_DIR = Path(__file__).resolve().parents[2] / "deploy" / "kubernetes" / "srdp-chart"

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None or not (CHART_DIR / "charts").is_dir(),
    reason="needs helm and the chart dependencies (helm dependency build)",
)

Manifest = dict[str, Any]


def render(*values_files: str, set_values: tuple[str, ...] = ()) -> list[Manifest]:
    """Render the chart with the given values files (relative to the chart) and --set overrides."""
    args = ["helm", "template", "srdp", str(CHART_DIR), "--namespace", "srdp"]
    for values_file in values_files:
        args += ["-f", str(CHART_DIR / values_file)]
    for set_value in set_values:
        args += ["--set", set_value]
    # Fixed argv, no shell: every argument comes from this test module.
    result = subprocess.run(args, capture_output=True, text=True, check=True)  # noqa: S603
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def find(manifests: list[Manifest], kind: str, name: str) -> Manifest:
    """Return the single manifest with this kind and name."""
    matches = [m for m in manifests if m["kind"] == kind and m["metadata"]["name"] == name]
    assert len(matches) == 1, f"expected one {kind}/{name}, found {len(matches)}"
    return matches[0]


def pod_specs(manifests: list[Manifest]) -> list[tuple[str, Manifest]]:
    """Return (name, pod spec) for every Deployment and Job."""
    return [
        (m["metadata"]["name"], m["spec"]["template"]["spec"]) for m in manifests if m["kind"] in {"Deployment", "Job"}
    ]


def containers(spec: Manifest) -> list[Manifest]:
    return spec.get("initContainers", []) + spec.get("containers", [])


@pytest.fixture(scope="module")
def local() -> list[Manifest]:
    return render("values.yaml", "values-local.yaml")


def test_streamlit_runs_behind_the_login(local: list[Manifest]) -> None:
    deployment = find(local, "Deployment", "streamlit")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert container["image"].endswith("/streamlit:v1.0")
    assert find(local, "Service", "streamlit")["spec"]["ports"][0]["targetPort"] == 8000

    ingress = find(local, "Ingress", "streamlit-ingress")
    assert ingress["spec"]["rules"][0]["host"] == "streamlit.srdp.localhost"
    assert "oauth-auth" in ingress["metadata"]["annotations"]["traefik.ingress.kubernetes.io/router.middlewares"]
    auth_hosts = [r["host"] for r in find(local, "Ingress", "auth-routes-ingress")["spec"]["rules"]]
    assert "streamlit.srdp.localhost" in auth_hosts


def test_setup_job_covers_all_four_databases(local: list[Manifest]) -> None:
    toml = find(local, "ConfigMap", "srdp-setup-config")["data"]["srdp.toml"]
    for database in ("zitadel", "dagster", "marquez", "ducklake"):
        assert f'name = "{database}"' in toml


def test_dagster_code_location_uses_the_compose_module_path(local: list[Manifest]) -> None:
    deployment = find(local, "Deployment", "srdp-dagster-user-deployments-srdp-etl")
    args = deployment["spec"]["template"]["spec"]["containers"][0]["args"]
    assert args[args.index("-m") + 1] == "etl.definitions"


def test_dagster_runs_one_run_at_a_time(local: list[Manifest]) -> None:
    instance = yaml.safe_load(find(local, "ConfigMap", "srdp-dagster-instance")["data"]["dagster.yaml"])
    coordinator = instance["run_coordinator"]
    assert coordinator["class"] == "QueuedRunCoordinator"
    assert coordinator["config"]["max_concurrent_runs"] == 1


@pytest.mark.parametrize(
    "name",
    ["srdp-dagster-user-deployments-srdp-etl", "api", "duckdb-ui", "marimo", "streamlit"],
)
def test_ducklake_readers_and_writers_share_one_data_volume(local: list[Manifest], name: str) -> None:
    spec = find(local, "Deployment", name)["spec"]["template"]["spec"]
    claims = [v["persistentVolumeClaim"]["claimName"] for v in spec.get("volumes", []) if "persistentVolumeClaim" in v]
    assert claims == ["ducklake-data"]
    container = spec["containers"][0]
    env = {e["name"]: e.get("value") for e in container.get("env", [])}
    mount_paths = [m["mountPath"] for m in container.get("volumeMounts", [])]
    assert env["DUCKLAKE_DATA_PATH"] in mount_paths

