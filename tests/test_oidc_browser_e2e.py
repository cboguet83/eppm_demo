"""Opt-in real Keycloak and Streamlit browser workflows, using an isolated database.

Build eppm-demo:local first, install the browser-tests extra, and run with
EPPM_RUN_OIDC_E2E=1. Credentials are generated in memory for this test deployment;
no existing environment file, identity cookie, or development database is read.
"""

from contextlib import closing
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

import pytest

from app.infrastructure.database.connection import get_db
from app.infrastructure.database.schema_init import init_db
from scripts.configure_local_oidc import local_environment


pytestmark = pytest.mark.skipif(os.environ.get("EPPM_RUN_OIDC_E2E") != "1", reason="Requires the opt-in local Keycloak browser deployment")
ROOT = Path(__file__).resolve().parents[1]


@dataclass
class BrowserDeployment:
    """Keep generated credentials out of test representations and command output."""

    origin: str
    database: Path
    compose: list[str]
    environment: dict[str, str] = field(repr=False)

    def command(self, *arguments: str) -> None:
        """Run bounded commands for this isolated Compose project without credential output."""
        result = subprocess.run(self.compose + list(arguments), cwd=ROOT, env=self.environment,
                                capture_output=True, timeout=180, check=False)
        if result.returncode:
            raise RuntimeError("The isolated browser deployment command failed: " + arguments[0])


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
    """Start a disposable real provider with exact callbacks and a dedicated SQLite file."""
    origin = "http://localhost:18501"
    values = local_environment(origin, provider_port=18080)
    identity = uuid4().hex[:12]
    directory = ROOT / ".local" / "oidc-e2e" / identity
    data = directory / "data"
    data.mkdir(parents=True)
    values["EPPM_DATA_DIRECTORY"] = data.as_posix()
    environment_path = directory / "compose.env"
    descriptor = os.open(environment_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
        target.writelines(f"{key}={value}\n" for key, value in values.items())
    image_override = directory / "image-only.yml"
    image_override.write_text(
        "services:\n  app:\n    volumes: !override\n      - type: bind\n"
        "        source: ${EPPM_DATA_DIRECTORY}\n        target: /app/data\n",
        encoding="utf-8",
    )
    database = data / "ppm_mock.db"
    init_db(str(database))
    with closing(get_db(str(database))) as connection, connection:
        connection.execute("INSERT INTO project(id,name) VALUES(1,'Visible browser project'),(2,'Hidden browser project')")
        connection.execute("INSERT INTO project_task(project_id,task_name,start_date,end_date) VALUES(1,'Visible browser task','2026-01-01','2026-01-05'),(2,'Hidden browser task','2026-01-01','2026-01-05')")
    server = BrowserDeployment(origin, database,
        ["docker", "compose", "--project-name", "eppm-e2e-" + identity,
         "--env-file", str(environment_path), "-f", "docker-compose.yml", "-f", "docker-compose.oidc.yml",
         "-f", str(image_override)],
        os.environ | values)
    try:
        server.command("up", "-d", "--no-build")
        wait_for_server(values["OIDC_ISSUER"] + "/.well-known/openid-configuration")
        wait_for_server(origin + "/_stcore/health")
        yield server
    finally:
        # Only the unique Compose project's resources are removed; host fixtures remain ignored.
        if os.environ.get("EPPM_KEEP_E2E") != "1":
            server.command("down", "--volumes", "--remove-orphans")


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
        page.get_by_role("combobox", name=label, exact=True).click()
        if label == "Projects":
            page.get_by_role("combobox", name=label, exact=True).fill("Visible browser project")
        stage = "selecting option"
        page.get_by_role("option", name=name, exact=isinstance(name, str)).click()
        if label == "Projects":
            stage = "closing dropdown"
            page.get_by_role("combobox", name=label, exact=True).press("Tab")
        stage = "waiting for rendered selection"
        expect(page.get_by_test_id("stApp")).to_have_attribute("data-test-script-state", "notRunning")
    except Error:
        # This helper is used only on post-login fields in the fictional test database.
        raise AssertionError(f"Unable to select {label} while {stage}.\n" + page.locator("body").aria_snapshot()) from None


def wait_for_audit(server: BrowserDeployment, action: str, count: int) -> None:
    """Wait for the real UI transaction before refreshing its transport runtime."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with closing(get_db(str(server.database))) as connection:
            actual = connection.execute("SELECT count(*) FROM app_security_audit WHERE action=?", (action,)).fetchone()[0]
        if actual >= count:
            return
        time.sleep(0.1)
    raise AssertionError("The browser action did not persist its required audit: " + action)


def exercise_scoped_user(browser, admin_page, server: BrowserDeployment) -> None:
    """Activate and scope a viewer through the administration UI, then revoke across tabs."""
    from playwright.sync_api import Error, expect

    viewer_context = browser.new_context()
    try:
        viewer = viewer_context.new_page()
        sign_in(viewer, server, "robin.viewer", "KEYCLOAK_ROBIN_PASSWORD")
        expect(viewer.get_by_text("Your account is awaiting activation.", exact=False)).to_be_visible()
        admin_page.reload()
        select_option(admin_page, "Application account", re.compile("Robin Example"))
        select_option(admin_page, "Account status", "active")
        admin_page.get_by_role("button", name="Save account status", exact=True).click()
        wait_for_audit(server, "user.status", 1)
        admin_page.reload()
        select_option(admin_page, "Application account", re.compile("Robin Example.*active"))
        select_option(admin_page, "Projects", re.compile("Visible browser project"))
        expect(admin_page.get_by_test_id("stMultiSelect").get_by_text(re.compile("Visible browser project")).first).to_be_visible()
        expect(admin_page.get_by_role("button", name="Grant access", exact=True)).to_be_visible()
        admin_page.get_by_role("button", name="Grant access", exact=True).click()
        wait_for_audit(server, "role.grant", 1)
        admin_page.reload()
        select_option(admin_page, "Application account", re.compile("Robin Example.*active"))
        expect(admin_page.get_by_role("button", name="Revoke assignment", exact=True)).to_be_visible()
        viewer.reload()
        expect(viewer.get_by_role("button", name="Open project Visible browser project", exact=True)).to_be_visible()
        expect(viewer.get_by_role("button", name="Open project Hidden browser project", exact=True)).to_have_count(0)
        expect(viewer.get_by_role("button", name="Create new project", exact=True)).to_have_count(0)
        export = viewer_context.request.get(server.origin + "/downloads/projects/1/template.csv")
        assert export.status == 200
        assert "Visible browser task" in export.text() and "Hidden browser task" not in export.text()
        assert viewer_context.request.get(server.origin + "/downloads/projects/2/template.csv").status == 403
        viewer.get_by_role("button", name="Open project Visible browser project", exact=True).click()
        viewer.get_by_role("button", name=re.compile("View project details")).click()
        expect(viewer.get_by_role("dialog")).to_be_visible()
        expect(viewer.get_by_role("button", name="Edit project", exact=True)).to_have_count(0)
        second_tab = viewer_context.new_page()
        second_tab.goto(server.origin)
        expect(second_tab.get_by_role("button", name="Open project Visible browser project", exact=True)).to_be_visible()
        admin_page.get_by_role("button", name="Revoke assignment", exact=True).click()
        wait_for_audit(server, "role.revoke", 1)
        admin_page.reload()
        select_option(admin_page, "Application account", re.compile("Robin Example.*active"))
        expect(admin_page.get_by_role("button", name="Revoke assignment", exact=True)).to_have_count(0)
        assert viewer_context.request.get(server.origin + "/downloads/projects/1/template.csv").status == 403
        second_tab.reload()
        expect(second_tab.get_by_text("Your account has no assigned application access.", exact=False)).to_be_visible()
        viewer.reload()
        viewer.get_by_role("button", name="Sign out", exact=True).click()
        expect(viewer.get_by_role("link", name="Sign in", exact=True)).to_be_visible()
        expect(second_tab.get_by_role("link", name="Sign in", exact=True)).to_be_visible()
        assert viewer_context.request.get(server.origin + "/auth/session").status == 401
    except (AssertionError, Error) as error:
        with closing(get_db(str(server.database))) as connection:
            counts = connection.execute("SELECT action,count(*) FROM app_security_audit GROUP BY action").fetchall()
        error.add_note("Fictional test audit action counts: " + repr(counts))
        error.add_note("Post-login administrator UI:\n" + admin_page.locator("body").aria_snapshot())
        raise
    finally:
        viewer_context.close()


def test_real_keycloak_login_pending_bootstrap_and_access_administration(deployment):
    """The first verified identity stays pending until an exact deployment bootstrap."""
    from playwright.sync_api import expect, sync_playwright

    expect.set_options(timeout=30000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.environ.get("EPPM_BROWSER_CHANNEL", "chrome"))
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
            deployment.command("exec", "-T", "app", "python", "-m", "scripts.access_admin", "bootstrap-admin", "--user-id", user_id)
            page.reload()
            expect(page.get_by_role("heading", name="Application access", exact=True)).to_be_visible()
            expect(page.get_by_label("Search accounts", exact=True)).to_be_visible()
            # Bootstrap grants access administration, never implicit business access.
            assert context.request.get(deployment.origin + "/downloads/projects/1/template.csv").status == 403
            expect(page.get_by_role("button", name="Open project Visible browser project", exact=True)).to_have_count(0)
            exercise_scoped_user(browser, page, deployment)
        finally:
            context.close()
            browser.close()
