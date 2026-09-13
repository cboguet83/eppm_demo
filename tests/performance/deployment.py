"""Disposable authenticated deployments for equivalent database comparisons."""

from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from secrets import token_hex, token_urlsafe
import shutil
import socket
import subprocess
from uuid import uuid4

from scripts.configure_local_oidc import local_environment
from tests.postgresql.recovery_support import operator_json
from tests.test_oidc_browser_e2e import BrowserDeployment, ROOT, wait_for_server


IMAGES = {
    "postgresql": "eppm-demo:postgresql-load-candidate",
    "sqlite": "eppm-demo:sqlite-migration-baseline",
}
COUNTS = {
    "project": 10001, "project_task": 73929, "task_dependencies": 66173,
    "resource_pool": 103, "resource_pool_group": 31,
    "resource_pool_assignment": 10201,
}


def docker_json(*arguments: str) -> dict[str, object]:
    """Read explicitly selected numeric/image metadata without container environments."""
    result = subprocess.run(["docker", *arguments], capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise RuntimeError("Benchmark Docker metadata inspection failed.")
    return json.loads(result.stdout)


def deployment_metadata(server: BrowserDeployment, backend: str) -> dict[str, object]:
    """Record actual images and host/container limits for each measured deployment."""
    host = docker_json("info", "--format",
                       '{"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}},"engine":{{json .ServerVersion}}}')
    containers = {}
    for service in (("app", "postgres", "keycloak") if backend == "postgresql" else ("app", "keycloak")):
        identity = server.command("ps", "--quiet", service).decode().strip()
        containers[service] = docker_json("inspect", "--format",
            '{"image_id":{{json .Image}},"nano_cpus":{{.HostConfig.NanoCpus}},'
            '"memory_bytes":{{.HostConfig.Memory}},"cpu_quota":{{.HostConfig.CpuQuota}},'
            '"cpu_period":{{.HostConfig.CpuPeriod}},"cpuset":{{json .HostConfig.CpusetCpus}},'
            '"source_commit":{{json (index .Config.Labels "org.opencontainers.image.revision")}}}', identity)
    versions = operator_json(server, """
import platform, streamlit
print(json.dumps({'python':platform.python_version(),'streamlit':streamlit.__version__}))
""", stage="comparison versions")
    return {"host": host, "containers": containers, "application_versions": versions}
SEED = """
import os
import psycopg
from app.application.ports.maintenance import SeedRequest
from app.operator_services import create_maintenance_service
create_maintenance_service().seed_projects(SeedRequest(
    projects=10001, min_tasks=0, max_tasks=15, clean_first=True, random_seed=42))
tables = ('project','project_task','task_dependencies','resource_pool',
          'resource_pool_group','resource_pool_assignment','app_user')
with psycopg.connect(os.environ['DATABASE_OPERATOR_URL']) as connection:
    counts = {name: connection.execute('SELECT count(*) FROM eppm.' + name).fetchone()[0] for name in tables}
    assert connection.execute("SELECT reltuples FROM pg_class WHERE oid='eppm.project'::regclass").fetchone()[0] == counts['project']
print(json.dumps(counts))
"""
GRANT = """
import os
from app.application.services.business_access import BusinessAccess
from app.security import create_access_service
from app.shared.config.authentication import AuthenticationConfig
from app.runtime import RuntimeResources
resources = RuntimeResources.from_environment(os.environ)
resources.database.open()
try:
    access = create_access_service(resources, AuthenticationConfig.from_environment(os.environ))
    actor = access.actor(os.environ['LOAD_ADMIN_COOKIE'])
    access.grant(actor, actor.user_id, 'business_admin', {'kind':'all'})
    viewer = int(os.environ['LOAD_VIEWER_ID'])
    access.set_status(actor, viewer, 'active')
    access.grant(actor, viewer, 'project_viewer', {'kind':'all'})
    print(json.dumps({'granted': True}))
finally:
    resources.database.close()
"""


def baseline_source(action: str) -> str:
    """Read code used only by the preserved SQLite image, outside active packages."""
    path = ROOT / "docs/archive/sqlite/benchmarks" / (action + ".py")
    return path.read_text(encoding="utf-8")


def grant_accounts(server: BrowserDeployment, backend: str, admin_cookie: str, viewer_id: int) -> None:
    """Grant real verified identities through their image's original access service."""
    source = GRANT if backend == "postgresql" else baseline_source("grant")
    result = operator_json(server, source, stage="load account grants", variables={
        "LOAD_ADMIN_COOKIE": admin_cookie, "LOAD_VIEWER_ID": str(viewer_id),
    })
    assert result == {"granted": True}


@contextmanager
def load_deployment(backend: str, image: str | None = None, *, profile: bool = False) -> Iterator[tuple[BrowserDeployment, Path, dict[str, object]]]:
    """Provision and remove only a newly named deployment and its own volumes.

    Args:
        backend: Explicit comparison image family; no runtime database fallback.
        image: Optional explicitly built image tag for a new native candidate.
        profile: Collect diagnostic thread profiles; these are not acceptance timings.
    """
    if backend not in IMAGES:
        raise ValueError("Choose the PostgreSQL candidate or preserved SQLite baseline.")
    with socket.socket() as app_port, socket.socket() as oidc_port:
        app_port.bind(("127.0.0.1", 0))
        oidc_port.bind(("127.0.0.1", 0))
        origin = f"http://localhost:{app_port.getsockname()[1]}"
        values = local_environment(origin, provider_port=oidc_port.getsockname()[1])
    operator_password, runtime_password = token_urlsafe(36), token_urlsafe(36)
    values.update(
        POSTGRES_PASSWORD=operator_password, EPPM_RUNTIME_PASSWORD=runtime_password,
        DATABASE_CONTEXT_KEY=token_hex(32),
        DATABASE_URL=f"postgresql://eppm_app:{runtime_password}@postgres:5432/eppm",
        DATABASE_OPERATOR_URL=f"postgresql://eppm_operator:{operator_password}@postgres:5432/eppm",
        EPPM_APP_IMAGE=image or IMAGES[backend], APP_RUN_MODE="demo", LOAD_PROFILE='1' if profile else '0',
    )
    identity = uuid4().hex[:12]
    directory = ROOT / ".local/browser-load" / identity
    data = directory / "data"
    data.mkdir(parents=True)
    values["EPPM_DATA_DIRECTORY"] = data.as_posix()
    source = ROOT / ".local/migration-baseline/baseline.db"
    source_hash = None
    if backend == "sqlite":
        with source.open("rb") as handle:
            source_hash = hashlib.file_digest(handle, "sha256").hexdigest()
        shutil.copy2(source, data / "benchmark.db")
    environment_path = directory / "compose.env"
    descriptor = os.open(environment_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
        target.writelines(f"{key}={value}\n" for key, value in values.items())
    override = directory / "image-only.yml"
    observer_directory = (ROOT / "tests/performance").as_posix()
    baseline_observer = (ROOT / "docs/archive/sqlite/benchmarks").as_posix()
    observer_mounts = (
        f"      - type: bind\n        source: {observer_directory}\n        target: /benchmark\n        read_only: true\n"
        f"      - type: bind\n        source: {baseline_observer}\n        target: /baseline-observer\n        read_only: true\n"
    )
    postgres_observation = (
        "  postgres:\n    command: [postgres, -c, max_connections=100, -c, shared_preload_libraries=pg_stat_statements, -c, track_io_timing=on]\n"
        if backend == "postgresql" else ""
    )
    override.write_text(
        "services:\n  app:\n    environment:\n      DB_NAME: /app/data/benchmark.db\n"
        f"      APP_RUN_MODE: demo\n      LOAD_BACKEND: {backend}\n      PYTHONPATH: /app:/benchmark\n"
        "      LOAD_PROFILE: ${LOAD_PROFILE}\n"
        "    entrypoint: [python, /benchmark/launch.py]\n    volumes: !override\n      - type: bind\n"
        "        source: ${EPPM_DATA_DIRECTORY}\n        target: /app/data\n" + observer_mounts + postgres_observation,
        encoding="utf-8",
    )
    server = BrowserDeployment(origin, [
        "docker", "compose", "--project-name", "eppm-load-" + identity,
        "--env-file", str(environment_path), "-f", "docker-compose.yml",
        "-f", "docker-compose.postgresql.yml", "-f", "docker-compose.oidc.yml",
        "-f", str(override),
    ], os.environ | values)
    try:
        services = ["postgres", "keycloak"] if backend == "postgresql" else ["keycloak"]
        server.command("up", "-d", "--no-build", "--wait", *services)
        wait_for_server(values["OIDC_ISSUER"] + "/.well-known/openid-configuration")
        if backend == "postgresql":
            for action in ("provision", "migrate", "configure-security"):
                server.operator("-m", "scripts.postgresql_admin", action)
            counts = operator_json(server, SEED, stage="load fixture seed")
            operator_json(server, """
import os, psycopg
with psycopg.connect(os.environ['DATABASE_OPERATOR_URL']) as connection:
    connection.execute('CREATE EXTENSION pg_stat_statements')
print(json.dumps({'installed':True}))
""", stage="test-only PostgreSQL statistics")
            server.command("run", "--detach", "--rm", "--no-deps", "--entrypoint", "python",
                           "-e", "DATABASE_OPERATOR_URL", "app", "/benchmark/pg_monitor.py")
        else:
            server.operator("-m", "scripts.access_admin", "migrate")
            counts = operator_json(server, baseline_source("inspect"), stage="baseline fixture verification")
        assert {name: counts[name] for name in COUNTS} == COUNTS
        assert counts["app_user"] == 0, "Load fixtures must start without imported accounts."
        server.command("up", "-d", "--no-build", "--no-deps", "app")
        wait_for_server(origin + "/_stcore/health")
        print(json.dumps({"stage":"deployment_ready", "backend":backend, "directory":str(directory)}), flush=True)
        yield server, directory, {
            "backend": backend, "image": values["EPPM_APP_IMAGE"], "counts": counts,
            "fixture_seed": 42, "min_tasks": 0, "max_tasks": 15,
            "sqlite_source_sha256": source_hash,
            "statistics_preparation": ("Native operator seed refreshes application statistics" if backend == "postgresql"
                                       else "Explicit ANALYZE of the disposable SQLite copy"),
            "deployment": deployment_metadata(server, backend),
            "diagnostic_profiling": profile,
        }
    finally:
        (data / "monitor.stop").touch()
        server.command("down", "--volumes", "--remove-orphans")
        if source_hash is not None:
            with source.open("rb") as handle:
                assert hashlib.file_digest(handle, "sha256").hexdigest() == source_hash
