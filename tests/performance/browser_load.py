"""Run actual OIDC/browser workloads against disposable comparison deployments.

Run explicitly with ``python -m tests.performance.browser_load --help``.
Short pilots verify the harness; they never satisfy the migration's load gate.
"""

from argparse import ArgumentParser
import asyncio
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
from time import monotonic, time
import traceback
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urlsplit

from app.infrastructure.authentication.http import SESSION_COOKIE
from app.presentation.navigation import PAGE_PLANNING
from tests.performance.deployment import grant_accounts, load_deployment
from tests.performance.diagnostics import summarize_phases
from tests.performance.planning_explain import SOURCE as PLANNING_EXPLAIN
from tests.performance.resource_monitor import sample_containers
from tests.postgresql.recovery_support import operator_json
from tests.test_oidc_browser_e2e import BrowserDeployment

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Frame, Page


@dataclass(frozen=True)
class Options:
    """Record the offered workload separately from measured successful latency."""

    readers: int = 40
    editors: int = 10
    rounds: int = 3
    warmup_seconds: float = 120
    measurement_seconds: float = 600
    cadence_seconds: float = 2


@dataclass
class Session:
    """One independently authenticated browser context and assigned workflow."""

    index: int
    scenario: str
    context: "BrowserContext"
    page: "Page"
    frame: "Frame | None" = None
    project_id: int | None = None
    sequence: int = 0


ARM = """({predicate, values, click}) => {
    const ready = new Function('values', 'return (' + predicate + ')');
    const timing = window.__loadTiming = {started:null, finished:null};
    const start = () => {timing.started = performance.now();};
    if (click) document.addEventListener('pointerdown', start, {capture:true, once:true});
    else start();
    function sample() {
        if (window.__loadTiming !== timing) return;
        if (timing.started !== null && ready(values)) {
            requestAnimationFrame(() => {timing.finished = performance.now();});
        } else requestAnimationFrame(sample);
    }
    requestAnimationFrame(sample);
}"""


async def _arm(area: "Page | Frame", predicate: str, values: dict[str, object], *, click: bool) -> None:
    script = ARM.replace("new Function('values', 'return (' + predicate + ')')", f"values => ({predicate})")
    await area.evaluate(script, {"values": values, "click": click})


async def _elapsed(area: "Page | Frame") -> float:
    await area.wait_for_function("window.__loadTiming?.finished !== null && window.__loadTiming?.finished !== undefined",
                                 timeout=30000, polling="raf")
    return await area.evaluate("window.__loadTiming.finished - window.__loadTiming.started")


async def _login(page: "Page", server: BrowserDeployment, editor: bool) -> None:
    from playwright.async_api import Error

    try:
        await page.goto(server.origin + "/auth/login")
        await page.get_by_label("Username", exact=True).fill("alex.admin" if editor else "robin.viewer")
        key = "KEYCLOAK_ALEX_PASSWORD" if editor else "KEYCLOAK_ROBIN_PASSWORD"
        await page.get_by_label("Password", exact=True).fill(server.environment[key])
        await page.get_by_role("button", name="Sign In", exact=True).click()
        await page.wait_for_url(server.origin + "/", timeout=60000)
    except Error:
        # Never emit the provider URL, field values, cookies or callback state.
        raise RuntimeError("Real OIDC login failed during load preparation.") from None


async def _reference(page: "Page") -> int:
    text = await page.get_by_text(re.compile(r"Application user reference: \d+")).first.inner_text()
    return int(re.search(r"\d+", text).group())


async def _prepare(session: Session, server: BrowserDeployment) -> None:
    from playwright.async_api import expect

    page = session.page
    if session.scenario == "visible_task_loading":
        await page.goto(server.origin + "/?" + urlencode({"nav": PAGE_PLANNING}))
        iframe = page.locator('iframe[title*="interactive_gantt"]')
        ready = asyncio.create_task(iframe.wait_for(state="visible", timeout=120000))
        failed = asyncio.create_task(page.get_by_test_id("stAlert").filter(
            has_text="Planning data could not be accessed").wait_for(state="visible", timeout=120000))
        done, pending = await asyncio.wait((ready, failed), return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            await task
        if failed in done:
            raise RuntimeError("The application reported a planning storage failure.")
        session.frame = await (await iframe.element_handle()).content_frame()
        await session.frame.wait_for_function("typeof masterRenderItems !== 'undefined' && masterRenderItems.length >= 10001",
                                              timeout=120000)
        return
    await page.goto(server.origin + "/?nav=portfolio")
    rows = page.locator(".st-key-portfolio_master_table tbody tr[data-project-id]")
    await expect(rows.first).to_be_visible(timeout=120000)
    if session.scenario == "simple_save":
        row = rows.nth(session.index)
        session.project_id = int(await row.get_attribute("data-project-id"))
        await row.click()
        await expect(page.locator(f".st-key-project_details_panel_{session.project_id}")) \
            .to_have_attribute("data-eppm-details-ready", "true", timeout=60000)


async def _portfolio(session: Session) -> float:
    root = session.page.locator("#portfolio-project-table")
    offset = ((session.sequence * 7 + session.index * 13 + 1) % 99) * 100
    # A real scrollbar action loads uncached pages; inspect the component's public
    # DOM and existing model only to verify that the requested rows are usable.
    await _arm(session.page, "window.__loadPortfolioRoot?._portfolio?.pending === null && "
               "window.__loadPortfolioRoot._portfolio.pages.has(values.offset) && "
               "window.__loadPortfolioRoot.querySelectorAll('tbody tr[data-project-id]').length >= 10",
               {"offset": offset}, click=False)
    await root.evaluate("(root, top) => {window.__loadPortfolioRoot=root; root.querySelector('.table-scroll').scrollTop=top;}",
                        (offset + 25) * 40 + 44)
    return await _elapsed(session.page)


async def _tasks(session: Session) -> float:
    frame = session.frame
    assert frame is not None
    await frame.locator("#btn-collapse-all").click()
    target = await frame.evaluate("""index => {
        const headers=masterRenderItems.filter(row => row.type==='project_header' && row.taskCount>0);
        const project=headers[(index*131)%headers.length];
        return {project:String(project.project_id), row:masterRenderItems.indexOf(project)};
    }""", session.sequence + session.index * 47)
    await frame.locator("#timeline-body-scroller").evaluate("(node, row) => {node.scrollTop=row*46;}", target["row"])
    toggle = frame.locator(f"#frozen-row-proj-{target['project']} .collapse-toggle-icon")
    await toggle.wait_for(state="visible")
    await _arm(frame, "loadedProjectIds.has(values.project) && tasksData.some(task => "
               "String(task.project_id)===values.project && document.getElementById('frozen-row-'+task.id))",
               target, click=True)
    await toggle.click()
    return await _elapsed(frame)


async def _save(session: Session) -> float:
    from playwright.async_api import expect

    page = session.page
    await page.get_by_role("button", name="Edit details", exact=True).click()
    dialog = page.get_by_role("dialog")
    value = f"Load editor {session.index:02d} save {session.sequence:05d}"
    await dialog.get_by_label("Project Title *", exact=True).fill(value)
    await _arm(page, "document.querySelector('.st-key-project_details_panel_'+values.project)?.textContent.includes(values.name) "
               "&& document.body.textContent.includes('Project details updated.')",
               {"project": session.project_id, "name": value}, click=True)
    await dialog.get_by_role("button", name=re.compile("Update Project")).click()
    elapsed = await _elapsed(page)
    await expect(dialog).not_to_be_visible()
    return elapsed


OPERATIONS = {"portfolio_paging": _portfolio, "visible_task_loading": _tasks, "simple_save": _save}


def summarize(samples: list[dict[str, object]]) -> dict[str, object]:
    """Keep each scenario and measurement period separate, including failures."""
    result = {}
    for scenario in OPERATIONS:
        selected = [sample for sample in samples if sample["scenario"] == scenario]
        durations = sorted(sample["elapsed_ms"] for sample in selected if sample["ok"])
        result[scenario] = {
            "attempts": len(selected), "failures": sum(not sample["ok"] for sample in selected),
            "successes": len(durations),
            "p95_ms": durations[math.ceil(len(durations) * .95) - 1] if durations else None,
            "max_ms": max(durations) if durations else None,
        }
    return result


async def _period(sessions: list[Session], options: Options, seconds: float,
                  round_index: int, warmup: bool, samples: list[dict[str, object]]) -> dict[str, object]:
    start = monotonic()
    started_epoch = time()
    deadline = start + seconds

    async def worker(session: Session) -> None:
        due = start + options.cadence_seconds * sessions.index(session) / len(sessions)
        while due < deadline:
            await asyncio.sleep(max(0, due - monotonic()))
            began = monotonic()
            entry = {"session": session.index, "scenario": session.scenario, "round": round_index,
                     "warmup": warmup, "started_epoch": time()}
            try:
                elapsed = await OPERATIONS[session.scenario](session)
                entry.update(ok=True, elapsed_ms=round(elapsed, 3))
            except Exception as error:
                # Boundary around fictional browser actions: preserve failure
                # category but never arbitrary browser URLs or identity payloads.
                location = traceback.extract_tb(error.__traceback__)[-1]
                entry.update(ok=False, error_type=type(error).__name__,
                             source_file=Path(location.filename).name, source_line=location.lineno)
                if session.scenario == "portfolio_paging":
                    try:
                        entry["viewport_diagnostic"] = await session.page.locator("#portfolio-project-table").evaluate("""root => ({
                            sameRoot:root===window.__loadPortfolioRoot,
                            oldRootConnected:window.__loadPortfolioRoot?.isConnected,
                            pending:root._portfolio?.pending !== null,
                            pendingOffset:root._portfolio?.pending?.offset,
                            top:root._portfolio?.top,
                            offsets:[...(root._portfolio?.pages.keys() || [])],
                            renderedRows:root.querySelectorAll('tbody tr[data-project-id]').length,
                            timing:window.__loadTiming
                        })""")
                    except Exception as diagnostic_error:
                        # A broken viewport must not erase the original failed action.
                        entry['diagnostic_error_type'] = type(diagnostic_error).__name__
            entry["workflow_seconds"] = round(monotonic() - began, 3)
            samples.append(entry)
            session.sequence += 1
            # Keep this session in the offered workload after failures. Do not
            # reset its page, discard failures, or silently remove the worker.
            due = max(due + options.cadence_seconds, monotonic())

    await asyncio.gather(*(worker(session) for session in sessions))
    return {'round': round_index, 'warmup': warmup, 'started_epoch': started_epoch,
            'ended_epoch': time(), 'scheduled_seconds': seconds}


async def run_browser(server: BrowserDeployment, backend: str, options: Options,
                      report: dict[str, object], directory: Path) -> None:
    """Prepare genuine sessions, then record concurrent warm and measured actions."""
    from playwright.async_api import async_playwright

    samples, cold, http = [], [], []
    report.update(samples=samples, cold_loads=cold, http_responses=http, periods=[], phases=[])
    async with async_playwright() as playwright:
        arguments = ["--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                     "--disable-backgrounding-occluded-windows"]
        browser = await playwright.chromium.launch(channel=os.environ.get("EPPM_BROWSER_CHANNEL"), args=arguments)
        report["browser"] = {"version": browser.version, "arguments": arguments,
                             "load_generator": "Python/Playwright on the Windows Docker host", "viewport": [1500, 1100]}
        sessions = []

        async def new_session(index: int, scenario: str) -> Session:
            context = await browser.new_context(viewport={"width": 1500, "height": 1100})
            page = await context.new_page()
            page.set_default_timeout(60000)
            def response_seen(response) -> None:
                path = urlsplit(response.url).path
                if path in {"/api/planning/tasks", "/api/portfolio/allocations"}:
                    http.append({"session": index, "scenario": scenario, "path": path,
                                 "status": response.status, "epoch": time()})
            page.on("response", response_seen)
            session = Session(index, scenario, context, page)
            sessions.append(session)
            await _login(page, server, scenario == "simple_save")
            print(json.dumps({"stage":"logged_in", "session":index, "scenario":scenario}), flush=True)
            return session

        try:
            admin = await new_session(0, "simple_save")
            admin_id = await _reference(admin.page)
            viewer = await new_session(0, "portfolio_paging")
            viewer_id = await _reference(viewer.page)
            await asyncio.to_thread(server.operator, "-m", "scripts.access_admin", "bootstrap-admin", "--user-id", str(admin_id))
            cookie = next(item["value"] for item in await admin.context.cookies() if item["name"] == SESSION_COOKIE)
            await asyncio.to_thread(grant_accounts, server, backend, cookie, viewer_id)
            del cookie
            for index in range(1, options.readers):
                await new_session(index, "portfolio_paging" if index < options.readers // 2 else "visible_task_loading")
            for index in range(1, options.editors):
                await new_session(index, "simple_save")
            semaphore = asyncio.Semaphore(2)
            async def prepare(session: Session) -> None:
                async with semaphore:
                    started = monotonic()
                    try:
                        await _prepare(session, server)
                    except Exception:
                        report["failed_preparation_session"] = {"session":session.index, "scenario":session.scenario,
                            "alerts":await session.page.get_by_test_id("stAlert").all_text_contents()}
                        await session.page.screenshot(path=str(directory / "preparation-failure.png"))
                        if backend == "postgresql" and session.scenario == "visible_task_loading":
                            cookie = next(item["value"] for item in await session.context.cookies()
                                          if item["name"] == SESSION_COOKIE)
                            try:
                                plan = await asyncio.to_thread(operator_json, server, PLANNING_EXPLAIN,
                                    stage="planning query diagnosis", variables={"LOAD_QUERY_COOKIE":cookie})
                                (directory / "planning-explain.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
                            except RuntimeError:
                                report["planning_explain_failed"] = True
                            del cookie
                        raise
                    cold.append({"session": session.index, "scenario": session.scenario,
                                 "elapsed_seconds": round(monotonic() - started, 3)})
                    print(json.dumps({"stage":"workflow_ready", **cold[-1]}), flush=True)
            await asyncio.gather(*(prepare(session) for session in sessions))
            identities = [next(item["value"] for item in await session.context.cookies()
                               if item["name"] == SESSION_COOKIE) for session in sessions]
            assert len(set(identities)) == options.readers + options.editors
            del identities
            editor_projects = [session.project_id for session in sessions if session.scenario == "simple_save"]
            assert len(set(editor_projects)) == options.editors, "Editors must use distinct projects."
            report["independent_authenticated_sessions"] = len(sessions)
            print(json.dumps({"stage": "sessions_ready", "backend": backend, "count": len(sessions)}), flush=True)
            for number in range(1, options.rounds + 1):
                report['phases'].append(await _period(sessions, options, options.warmup_seconds, number, True, samples))
                report['phases'].append(await _period(sessions, options, options.measurement_seconds, number, False, samples))
                summary = summarize([sample for sample in samples if sample["round"] == number and not sample["warmup"]])
                report["periods"].append({"round": number, "scenarios": summary})
                print(json.dumps({"stage": "measurement", "round": number, "scenarios": summary}), flush=True)
        finally:
            await browser.close()


def main() -> int:
    """Run the explicitly selected backend and always retain safe partial evidence."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("postgresql", "sqlite"), required=True)
    parser.add_argument("--image")
    parser.add_argument("--profile", action="store_true", help="Collect diagnostic thread-stack samples; not acceptance timings.")
    parser.add_argument("--readers", type=int, default=40)
    parser.add_argument("--editors", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--warmup-seconds", type=float, default=120)
    parser.add_argument("--measurement-seconds", type=float, default=600)
    arguments = parser.parse_args()
    options = Options(arguments.readers, arguments.editors, arguments.rounds,
                      arguments.warmup_seconds, arguments.measurement_seconds)
    if options.readers < 2 or not 1 <= options.editors <= 10 or options.rounds < 1 \
            or not all(math.isfinite(value) and value > 0 for value in
                       (options.warmup_seconds, options.measurement_seconds)):
        parser.error("Require at least two readers, one to ten editors, and positive periods.")
    with load_deployment(arguments.backend, arguments.image, profile=arguments.profile) as (server, directory, fixture):
        report = {"fixture": fixture, "options": asdict(options), "acceptance_complete": False,
                  "diagnostics": {"runtime": "data/runtime-timings.jsonl", "postgresql": "data/postgresql-timings.jsonl",
                                  "containers": "container-timings.jsonl"},
                  "remaining_instrumentation": ["browser rendering breakdown", "full prescribed workload"]}
        result = 0
        try:
            services = ('app', 'postgres', 'keycloak') if arguments.backend == 'postgresql' else ('app', 'keycloak')
            identities = {service: server.command('ps', '--quiet', service).decode().strip() for service in services}
            with sample_containers(identities, directory / 'container-timings.jsonl'):
                asyncio.run(run_browser(server, arguments.backend, options, report, directory))
            if any(not sample["ok"] for sample in report["samples"]):
                result = 1
        except Exception as error:
            report["preparation_failure"] = type(error).__name__
            locations = traceback.extract_tb(error.__traceback__)
            report["failure_locations"] = [{"file": Path(item.filename).name, "line": item.lineno}
                                           for item in locations if "tests" in item.filename]
            logs = server.command("logs", "--no-color", "app").decode(errors="replace")
            report["application_error_locations"] = re.findall(
                r"application.operation_failed reference=[\w-]+ exception=(\w+) source=([\w.]+) line=(\d+)", logs)
            result = 1
        finally:
            report['diagnostic_phases'] = summarize_phases(directory, report.get('phases', []))
            path = directory / "browser-results.json"
            path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"stage": "report", "path": str(path), "workflow_exit_code": result,
                              "acceptance_complete": False}), flush=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
