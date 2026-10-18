"""Exercise the independent module through its mounted browser interface."""

from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from threading import Thread

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
Page = playwright_api.Page
expect = playwright_api.expect


@pytest.fixture(scope="module")
def planning_module_origin() -> Iterator[str]:
    """Serve only standalone browser sources from a loopback origin."""
    directory = Path(__file__).resolve().parents[1] / "packages/planning-view"
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.fixture
def planning_page(planning_module_origin: str) -> Iterator[Page]:
    """Mount overlapping identities twice, retaining surrounding host content."""
    with playwright_api.sync_playwright() as playwright:
        executable = os.environ.get("EPPM_BENCHMARK_BROWSER")
        browser = playwright.chromium.launch(executable_path=executable)
        errors: list[str] = []
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1600})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(planning_module_origin)
            page.evaluate("""async () => {
                document.body.innerHTML='<button id="outside" style="padding:19px;user-select:text">Outside</button><div id="first"><span>Retained</span></div><div id="second"></div>';
                const {mountPlanningView}=await import('/src/index.js');
                window.mount=mountPlanningView;
                window.snapshot={version:1,kind:'snapshot',scope:'scope',revision:'r1',
                  projects:[{id:'same-project',name:'Project'}],
                  tasks:[{id:'same-task',projectId:'same-project',name:'<script>unsafe</script>',start:'2026-01-01',end:'2026-12-31'}],
                  resources:[{id:'same-pool',name:'Pool',capacity:5}]};
                window.heights=[[],[]];
                window.instances=['first','second'].map((id,index)=>mount(document.getElementById(id),{
                    snapshot,today:'2026-01-01',mode:'Day',onHeight:h=>heights[index].push(h)}));
            }""")
            expect(page.locator("#first [data-mode=Day]")).to_have_attribute("aria-pressed", "true")
            page.wait_for_function("document.querySelector('#first [data-part=timeline-body]').clientHeight===280")
            yield page
            assert errors == []
        finally:
            browser.close()


def test_mounts_have_independent_modes_scoped_css_and_unique_ownership(planning_page: Page) -> None:
    """Changing one instance leaves the other and surrounding host styles intact."""
    page = planning_page
    page.locator("#first [data-mode=Month]").click()
    expect(page.locator("#first [data-mode=Month]")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#second [data-mode=Day]")).to_have_attribute("aria-pressed", "true")
    assert page.locator("#outside").evaluate("n=>getComputedStyle(n).padding") == "19px"
    assert page.locator("#outside").evaluate("n=>getComputedStyle(n).userSelect") == "text"
    ids = page.locator(".planning-view").evaluate_all("nodes=>nodes.map(n=>n.dataset.instanceId)")
    assert len(set(ids)) == 2
    assert page.locator(".planning-view [id]").count() == 0
    expect(page.locator("#first > span")).to_have_text("Retained")


def test_scroll_coordination_and_splitter_stay_inside_the_instance(planning_page: Page) -> None:
    """Both pane directions share horizontal geometry and independent vertical offsets."""
    page = planning_page
    page.evaluate("""() => {
      for(const n of document.querySelectorAll('#first .planning-canvas'))n.style.height='2000px';
      const body=document.querySelector('#first [data-part=timeline-body]');body.scrollLeft=900;body.scrollTop=300;
    }""")
    page.wait_for_function("document.querySelector('#first [data-part=resource-body]').scrollLeft===900")
    assert page.locator("#first [data-part=timeline-left]").evaluate("n=>n.scrollTop") == 300
    assert page.locator("#second [data-part=timeline-body]").evaluate("n=>n.scrollLeft") == 0
    page.locator("#first [data-part=resource-body]").evaluate("n=>{n.scrollLeft=1400;n.scrollTop=150}")
    page.wait_for_function("document.querySelector('#first [data-part=timeline-header]').scrollLeft===1400")
    assert page.locator("#first [data-part=resource-left]").evaluate("n=>n.scrollTop") == 150
    first = page.locator("#first [data-part=timeline-left]")
    width = first.bounding_box()["width"]
    page.locator("#first [role=separator]").press("ArrowRight")
    page.wait_for_function("document.querySelector('#first [data-part=timeline-left]').clientWidth===435")
    assert first.bounding_box()["width"] == width + 10
    assert page.locator("#second [data-part=timeline-left]").bounding_box()["width"] == width
    splitter = page.locator("#first [role=separator]").bounding_box()
    page.mouse.move(splitter["x"] + 4, splitter["y"] + 10)
    page.mouse.down()
    page.mouse.move(splitter["x"] + 54, splitter["y"] + 10)
    page.mouse.up()
    page.wait_for_function("document.querySelector('#first [data-part=timeline-left]').clientWidth===485")
    assert page.locator("#first [data-part=resource-left]").bounding_box()["width"] == width + 60
    page.locator("#first").evaluate("n=>n.style.width='900px'")
    page.wait_for_function("document.querySelector('#first .planning-view').clientWidth===898")
    assert page.locator("#first [data-part=timeline-header-inner]").bounding_box()["width"] == page.locator("#first [data-part=resource-header-inner]").bounding_box()["width"]


def test_updates_are_atomic_reset_scope_and_hide_absent_resources(planning_page: Page) -> None:
    """The lifecycle update contract preserves same-scope geometry and rejects bad data."""
    page = planning_page
    page.locator("#first [data-part=timeline-body]").evaluate("n=>n.scrollLeft=500")
    page.wait_for_function("document.querySelector('#first [data-part=resource-header]').scrollLeft===500")
    page.evaluate("instances[0].update({...snapshot,revision:'r2',labels:{projectTask:'Projet'}})")
    expect(page.locator("#first [data-part=timeline-left-header]")).to_have_text("Projet")
    assert page.locator("#first [data-part=timeline-body]").evaluate("n=>n.scrollLeft") == 500
    assert page.evaluate("""() => {try{instances[0].update({...snapshot,version:2});return false;}catch(e){return e.name==='ContractError';}}""")
    expect(page.locator("#first [data-part=timeline-left-header]")).to_have_text("Projet")
    page.evaluate("instances[0].update({...snapshot,scope:'new',resources:[]})")
    expect(page.locator("#first [data-part=resource-panel]")).to_be_hidden()
    assert page.locator("#first [data-part=timeline-body]").evaluate("n=>n.scrollLeft") == 0


def test_destroy_cancels_scheduled_work_and_remount_has_one_handler_set(planning_page: Page) -> None:
    """Disposal is repeatable, retains host children, and isolates a surviving instance."""
    page = planning_page
    page.evaluate("""() => {
      document.querySelector('#first [data-mode=Month]').click();
      instances[0].destroy();instances[0].destroy();
      window.afterDestroy=heights[0].length;
      window.dispatchEvent(new Event('resize'));
    }""")
    page.wait_for_timeout(100)
    assert page.evaluate("heights[0].length===afterDestroy")
    expect(page.locator("#first > span")).to_have_text("Retained")
    assert page.locator("#first .planning-view").count() == 0
    assert page.evaluate("instances[0].update(null)") is False
    page.evaluate("instances[0]=mount(document.getElementById('first'),{snapshot,today:'2026-01-01'})")
    page.locator("#first [role=separator]").press("ArrowRight")
    page.wait_for_function("document.querySelector('#first [data-part=timeline-left]').clientWidth===435")
    expect(page.locator("#second [data-mode=Day]")).to_have_attribute("aria-pressed", "true")


def test_invalid_mount_and_failed_callback_leave_no_partial_display(planning_page: Page) -> None:
    """Validate mount boundaries before DOM changes and unwind failed setup."""
    assert planning_page.evaluate("""() => {
      const host=document.createElement('div');document.body.append(host);
      for(const options of [null,{}, {snapshot,onHeight:1},{snapshot,today:'bad'}]) {
        try{mount(host,options);return false;}catch(e){if(e.name!=='ContractError')return false;}
      }
      try{mount(host,{snapshot,onHeight:()=>{throw new Error('host');}});return false;}catch(e){}
      return host.children.length===0;
    }""")
