"""Opt-in real Keycloak and Streamlit browser workflows, using an isolated database.

Build eppm-demo:local first (or set EPPM_E2E_APP_IMAGE to an explicitly built image),
install the browser-tests extra, and run with EPPM_RUN_OIDC_E2E=1.
Credentials are generated in memory for this test deployment;
no existing environment file, identity cookie, or development database is read.
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from secrets import token_hex, token_urlsafe
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import uuid4

import pytest

from app.presentation.navigation import PAGE_ACCESS
from scripts.configure_local_oidc import local_environment


pytestmark = pytest.mark.skipif(os.environ.get("EPPM_RUN_OIDC_E2E") != "1", reason="Requires the opt-in local Keycloak browser deployment")
ROOT = Path(__file__).resolve().parents[1]


@dataclass
class BrowserDeployment:
    """Keep generated credentials out of test representations and command output."""

    origin: str
    compose: list[str]
    environment: dict[str, str] = field(repr=False)

    def command(self, *arguments: str) -> bytes:
        """Run bounded commands for this isolated Compose project without credential output."""
        result = subprocess.run(self.compose + list(arguments), cwd=ROOT, env=self.environment,
                                capture_output=True, timeout=180, check=False)
        if result.returncode:
            raise RuntimeError("The isolated browser deployment command failed: " + arguments[0])
        return result.stdout

    def operator(self, *arguments: str) -> bytes:
        """Pass separate credentials by name into an explicit disposable operator process."""
        return self.command(
            "run", "--rm", "-T", "--no-deps", "--entrypoint", "python",
            "-e", "DATABASE_OPERATOR_URL", "-e", "EPPM_RUNTIME_PASSWORD", "app", *arguments,
        )

    def audit_counts(self) -> dict[str, int]:
        """Read committed native audit through a separate operator process."""
        script = (
            "import json,os,psycopg; "
            "connection=psycopg.connect(os.environ['DATABASE_OPERATOR_URL']); "
            "rows=connection.execute('SELECT action,count(*) FROM eppm.app_security_audit GROUP BY action').fetchall(); "
            "connection.close(); print(json.dumps(dict(rows)))"
        )
        return json.loads(self.operator("-c", script))


def wait_for_server(url: str) -> None:
    """Wait for the local application/provider to become ready, without dumping responses."""
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(1)
    raise RuntimeError("The isolated application/provider did not become ready.")


@pytest.fixture(scope="module")
def deployment():
    """Start isolated provider/database volumes and explicitly provision the native app."""
    # Reserve different candidate ports together so concurrent test deployments
    # do not knowingly reuse each other's fixed application/provider ports.
    with socket.socket() as app_port, socket.socket() as provider_port:
        app_port.bind(("127.0.0.1", 0))
        provider_port.bind(("127.0.0.1", 0))
        origin = f"http://localhost:{app_port.getsockname()[1]}"
        values = local_environment(origin, provider_port=provider_port.getsockname()[1])
    operator_password, runtime_password = token_urlsafe(36), token_urlsafe(36)
    values.update(
        POSTGRES_PASSWORD=operator_password, EPPM_RUNTIME_PASSWORD=runtime_password,
        DATABASE_CONTEXT_KEY=token_hex(32),
        DATABASE_URL=f"postgresql://eppm_app:{runtime_password}@postgres:5432/eppm",
        DATABASE_OPERATOR_URL=f"postgresql://eppm_operator:{operator_password}@postgres:5432/eppm",
        EPPM_APP_IMAGE=os.environ.get("EPPM_E2E_APP_IMAGE", "eppm-demo:local"),
    )
    identity = uuid4().hex[:12]
    directory = ROOT / ".local" / "oidc-e2e" / identity
    directory.mkdir(parents=True)
    environment_path = directory / "compose.env"
    descriptor = os.open(environment_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
        target.writelines(f"{key}={value}\n" for key, value in values.items())
    image_override = directory / "image-only.yml"
    image_override.write_text(
        "services:\n  postgres:\n    ports: !reset []\n"
        "  app:\n    volumes: !override\n      - type: volume\n"
        "        source: browser-test-data\n        target: /app/data\n"
        "volumes:\n  browser-test-data:\n",
        encoding="utf-8",
    )
    server = BrowserDeployment(origin,
        ["docker", "compose", "--project-name", "eppm-e2e-" + identity,
         "--env-file", str(environment_path), "-f", "docker-compose.yml",
         "-f", "docker-compose.postgresql.yml", "-f", "docker-compose.oidc.yml",
         "-f", str(image_override)],
        os.environ | values)
    try:
        server.command("up", "-d", "--no-build", "--wait", "postgres", "keycloak")
        wait_for_server(values["OIDC_ISSUER"] + "/.well-known/openid-configuration")
        for action in ("provision", "migrate", "configure-security"):
            server.operator("-m", "scripts.postgresql_admin", action)
        server.operator("-c", NATIVE_FIXTURE)
        server.command("up", "-d", "--no-build", "--no-deps", "app")
        wait_for_server(origin + "/_stcore/health")
        server.command("exec", "-T", "app", "python", "-c",
                       "import os; assert 'DATABASE_OPERATOR_URL' not in os.environ; "
                       "assert 'EPPM_RUNTIME_PASSWORD' not in os.environ; "
                       "assert os.getuid() != 0; "
                       "from pathlib import Path; "
                       "probe = Path('/app/data/.runtime-write-probe'); "
                       "probe.touch(exist_ok=False); probe.unlink()")
        yield server
    finally:
        # Only the unique Compose project's resources are removed; host fixtures remain ignored.
        if os.environ.get("EPPM_KEEP_E2E") != "1":
            server.command("down", "--volumes", "--remove-orphans")


NATIVE_FIXTURE = """
import os
import psycopg
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.infrastructure.postgresql.seed_plan import ensure_operator_plan

with psycopg.connect(os.environ['DATABASE_OPERATOR_URL']) as connection:
    ensure_reference_catalog(connection)
    connection.execute("INSERT INTO eppm.project(id,name,status) VALUES(1,'Visible browser project','In Progress'),(2,'Hidden browser project','In Progress')")
    for project_id, label in ((1, 'Visible browser task'), (2, 'Hidden browser task')):
        plan_id = ensure_operator_plan(connection, project_id)
        connection.execute("INSERT INTO eppm.project_task(project_id,project_plan_id,task_name,start_date,end_date) VALUES(%s,%s,%s,'2026-01-01','2026-01-05')", (project_id, plan_id, label))
"""


def sign_in(page, server: BrowserDeployment, username: str, password_key: str) -> None:
    """Exercise the actual provider form without exposing credentials on failure."""
    from playwright.sync_api import Error

    stage = "opening provider login"
    try:
        page.goto(server.origin + "/auth/login")
        stage = "entering username"
        page.get_by_label("Username", exact=True).fill(username)
        stage = "entering password"
        page.get_by_label("Password", exact=True).fill(server.environment[password_key])
        stage = "submitting provider login"
        page.get_by_role("button", name="Sign In", exact=True).click()
        stage = "returning to the application"
        page.wait_for_url(server.origin + "/", timeout=30000)
    except Error:
        # Never include the Playwright error, field values, or callback query string.
        raise AssertionError("The real provider login failed while " + stage) from None


def select_option(page, label: str, name: str | re.Pattern[str]) -> None:
    """Choose a native Streamlit field through its accessible browser controls."""
    from playwright.sync_api import Error, expect

    stage = "opening field"
    try:
        from contextlib import nullcontext
        from tests.browser_reruns import completed_rerun

        action = nullcontext() if label == "Account status" else completed_rerun(page)
        with action:
            page.get_by_role("combobox", name=label, exact=True).click()
            if label == "Projects":
                page.get_by_role("combobox", name=label, exact=True).fill("Visible browser project")
            stage = "selecting option"
            page.get_by_role("option", name=name, exact=isinstance(name, str)).click()
            stage = "waiting for rendered selection"
        if label == "Projects":
            stage = "closing dropdown after selection is acknowledged"
            page.get_by_role("combobox", name=label, exact=True).press("Tab")
    except Error:
        # This helper is used only on post-login fields in the fictional test database.
        raise AssertionError(f"Unable to select {label} while {stage}.\n" + page.locator("body").aria_snapshot()) from None


def wait_for_audit(server: BrowserDeployment, action: str, count: int) -> None:
    """Wait for the real UI transaction before refreshing its transport runtime."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        actual = server.audit_counts().get(action, 0)
        if actual >= count:
            return
        time.sleep(0.1)
    raise AssertionError("The browser action did not persist its required audit: " + action)


def open_access_management(page, server: BrowserDeployment) -> None:
    """Reopen administration explicitly because a fresh session defaults to Dashboard."""
    from playwright.sync_api import expect

    page.goto(server.origin + "/?" + urlencode({"nav": PAGE_ACCESS}))
    expect(page.get_by_role("heading", name="Application access", exact=True)).to_be_visible()


def exercise_scoped_user(browser, admin_page, server: BrowserDeployment) -> None:
    """Activate and scope a viewer through the administration UI, then revoke across tabs."""
    from playwright.sync_api import Error, expect

    viewer_context = browser.new_context()
    try:
        viewer = viewer_context.new_page()
        sign_in(viewer, server, "robin.viewer", "KEYCLOAK_ROBIN_PASSWORD")
        expect(viewer.get_by_text("Your account is awaiting activation.", exact=False)).to_be_visible()
        open_access_management(admin_page, server)
        select_option(admin_page, "Application account", re.compile("Robin Example"))
        select_option(admin_page, "Account status", "active")
        admin_page.get_by_role("button", name="Save account status", exact=True).click()
        wait_for_audit(server, "user.status", 1)
        open_access_management(admin_page, server)
        select_option(admin_page, "Application account", re.compile("Robin Example.*active"))
        select_option(admin_page, "Projects", re.compile("Visible browser project"))
        expect(admin_page.get_by_test_id("stMultiSelect").get_by_text(re.compile("Visible browser project")).first).to_be_visible()
        expect(admin_page.get_by_role("button", name="Grant access", exact=True)).to_be_visible()
        admin_page.get_by_role("button", name="Grant access", exact=True).click()
        wait_for_audit(server, "role.grant", 1)
        open_access_management(admin_page, server)
        select_option(admin_page, "Application account", re.compile("Robin Example.*active"))
        expect(admin_page.get_by_role("button", name="Revoke assignment", exact=True)).to_be_visible()
        viewer.goto(server.origin + "/?nav=portfolio")
        visible_row = viewer.locator('.st-key-portfolio_master_table tbody tr[data-project-id="1"]')
        expect(visible_row).to_contain_text("Visible browser project")
        expect(viewer.locator('.st-key-portfolio_master_table tbody tr[data-project-id="2"]')).to_have_count(0)
        expect(viewer.get_by_role("button", name="Create new project", exact=True)).to_have_count(0)
        export = viewer_context.request.get(server.origin + "/downloads/projects/1/template.csv")
        assert export.status == 200
        assert "Visible browser task" in export.text() and "Hidden browser task" not in export.text()
        assert viewer_context.request.get(server.origin + "/downloads/projects/2/template.csv").status == 403
        visible_row.click()
        expect(viewer.locator('.st-key-project_details_panel_1')).to_have_attribute('data-eppm-details-ready', 'true')
        expect(viewer.get_by_role("button", name="Edit details", exact=True)).to_have_count(0)
        second_tab = viewer_context.new_page()
        second_tab.goto(server.origin + "/?nav=portfolio")
        expect(second_tab.locator('.st-key-portfolio_master_table tbody tr[data-project-id="1"]')).to_contain_text("Visible browser project")
        admin_page.get_by_role("button", name="Revoke assignment", exact=True).click()
        wait_for_audit(server, "role.revoke", 1)
        open_access_management(admin_page, server)
        select_option(admin_page, "Application account", re.compile("Robin Example.*active"))
        expect(admin_page.get_by_role("button", name="Revoke assignment", exact=True)).to_have_count(0)
        assert viewer_context.request.get(server.origin + "/downloads/projects/1/template.csv").status == 403
        second_tab.reload()
        expect(second_tab.get_by_role("radio", name="Dashboard", exact=True)).to_be_checked()
        expect(second_tab.get_by_role("radio", name=re.compile("Portfolio"))).to_have_count(0)
        expect(second_tab.locator('.st-key-portfolio_master_table')).to_have_count(0)
        viewer.reload()
        viewer.get_by_role("button", name="Sign out", exact=True).click()
        expect(viewer.get_by_role("link", name="Sign in", exact=True)).to_be_visible()
        expect(second_tab.get_by_role("link", name="Sign in", exact=True)).to_be_visible()
        assert viewer_context.request.get(server.origin + "/auth/session").status == 401
    except (AssertionError, Error) as error:
        counts = server.audit_counts()
        error.add_note("Fictional test audit action counts: " + repr(counts))
        logs = subprocess.run(
            server.compose + ["logs", "--no-log-prefix", "app"], cwd=ROOT, env=server.environment,
            capture_output=True, text=True, timeout=30, check=False,
        )
        safe_failures = re.findall(
            r"application\.operation_failed reference=[A-Za-z0-9_-]+ exception=[A-Za-z0-9_]+ "
            r"source=[A-Za-z0-9_.-]+ line=\d+", logs.stdout,
        )
        error.add_note("Sanitized application failure categories: " + repr(safe_failures))
        error.add_note("Post-login administrator UI:\n" + admin_page.locator("body").aria_snapshot())
        raise
    finally:
        viewer_context.close()


def test_real_keycloak_login_pending_bootstrap_and_access_administration(deployment):
    """The first verified identity stays pending until an exact deployment bootstrap."""
    from playwright.sync_api import expect, sync_playwright

    expect.set_options(timeout=30000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.environ.get("EPPM_BROWSER_CHANNEL"))
        context = browser.new_context()
        try:
            page = context.new_page()
            page.set_default_timeout(30000)
            page.goto(deployment.origin)
            expect(page.get_by_role("link", name="Sign in", exact=True)).to_be_visible()
            assert context.request.get(deployment.origin + "/downloads/projects/1/template.csv").status == 403
            sign_in(page, deployment, "alex.admin", "KEYCLOAK_ALEX_PASSWORD")
            expect(page.get_by_text("Your account is awaiting activation.", exact=False)).to_be_visible()
            expect(page.get_by_role("heading", name="Application access")).to_have_count(0)
            reference = page.get_by_text(re.compile(r"Application user reference: \d+")).first.inner_text()
            user_id = re.search(r"\d+", reference).group()
            assert context.request.get(deployment.origin + "/downloads/projects/1/template.csv").status == 403
            deployment.operator("-m", "scripts.access_admin", "bootstrap-admin", "--user-id", user_id)
            open_access_management(page, deployment)
            expect(page.get_by_label("Search accounts", exact=True)).to_be_visible()
            # Bootstrap grants access administration, never implicit business access.
            assert context.request.get(deployment.origin + "/downloads/projects/1/template.csv").status == 403
            expect(page.get_by_role("radio", name=re.compile("Portfolio"))).to_have_count(0)
            exercise_scoped_user(browser, page, deployment)
        finally:
            context.close()
            browser.close()
