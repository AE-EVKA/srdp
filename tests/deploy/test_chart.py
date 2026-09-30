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


# Development credentials that used to live in values.yaml. They may only
# appear in the kind-only Secrets that templates/local-secrets.yaml renders.
DEV_CREDENTIALS = (
    "srdpTest123",
    "51a69a373f45c60d2ae08c48bb89d03e",
    "VQMve4Thh857uplEKmN5nlcgSedaGyYQySSDYyoMgfk4d1PS8k6zUDSdhOdo3IVW",
    "6wdizcEbBnztdVvVoFwbSzHBfWYdBJshIOP6VlsxrDe5c1zSUQMvgDa6PfnA24BT",
    "VcZnfAWYCgMfNjRLvM1byUaAUs2jSvSE",
)

LOCAL_SECRETS = {"srdp-postgres", "srdp-zitadel", "srdp-oauth2-proxy", "srdp-dagster-postgresql", "srdp-marquez"}


def test_values_yaml_holds_no_credentials() -> None:
    text = (CHART_DIR / "values.yaml").read_text()
    for credential in DEV_CREDENTIALS:
        assert credential not in text


def test_default_render_holds_no_credentials_and_no_local_secrets() -> None:
    manifests = render("values.yaml")
    text = yaml.safe_dump_all(manifests)
    for credential in DEV_CREDENTIALS:
        assert credential not in text
    secret_names = {m["metadata"]["name"] for m in manifests if m["kind"] == "Secret"}
    assert not secret_names & LOCAL_SECRETS


def test_local_render_holds_credentials_only_in_local_secrets(local: list[Manifest]) -> None:
    rest = [m for m in local if not (m["kind"] == "Secret" and m["metadata"]["name"] in LOCAL_SECRETS)]
    text = yaml.safe_dump_all(rest)
    for credential in DEV_CREDENTIALS:
        assert credential not in text
    assert {m["metadata"]["name"] for m in local if m["kind"] == "Secret"} >= LOCAL_SECRETS


def test_every_password_env_var_comes_from_a_secret(local: list[Manifest]) -> None:
    for name, spec in pod_specs(local):
        for container in containers(spec):
            for env in container.get("env", []):
                if "PASSWORD" in env["name"] or "SECRET" in env["name"]:
                    assert "secretKeyRef" in env.get("valueFrom", {}), f"{name}/{container['name']}: {env['name']}"


def test_setup_job_and_marquez_read_the_same_marquez_password(local: list[Manifest]) -> None:
    def ref(spec: Manifest, var: str) -> Manifest:
        env = {e["name"]: e for c in spec["containers"] for e in c.get("env", [])}
        return env[var]["valueFrom"]["secretKeyRef"]

    setup = find(local, "Job", "srdp-setup")["spec"]["template"]["spec"]
    marquez = find(local, "Deployment", "marquez")["spec"]["template"]["spec"]
    assert ref(setup, "SETUP_PASSWORDS__MARQUEZ") == ref(marquez, "MARQUEZ_DB_PASSWORD")


def srdp_images(manifests: list[Manifest], registry: str) -> list[str]:
    return [
        c["image"]
        for _, spec in pod_specs(manifests)
        for c in containers(spec)
        if c["image"].startswith(registry) or "srdp-registry" in c["image"]
    ]


def test_one_value_moves_every_srdp_image_to_another_registry() -> None:
    registry = "registry.example.com/acme"
    manifests = render(
        "values.yaml",
        "values-local.yaml",
        set_values=(
            f"global.srdpRegistry={registry}",
            # The Dagster code location image is a subchart value the chart cannot
            # template, so the Justfile's `registry` variable sets it alongside.
            f"dagster.dagster-user-deployments.deployments[0].image.repository={registry}/srdp-etl",
            "global.imagePullSecrets[0].name=registry-key",
        ),
    )
    images = srdp_images(manifests, registry)
    names = {image.rsplit("/", 1)[1].split(":")[0] for image in images}
    assert names >= {"marimo", "srdp-api", "duckdb-ui", "hub", "streamlit", "srdp-setup"}
    assert all(image.startswith(f"{registry}/") for image in images), images
    for name in ("marimo", "api", "streamlit", "srdp-setup"):
        spec = next(s for n, s in pod_specs(manifests) if n == name)
        assert spec["imagePullSecrets"] == [{"name": "registry-key"}]
