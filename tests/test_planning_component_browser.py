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
                  projects:[{id:'same-project',name:'Project'},...Array.from({length:100},(_,i)=>({id:'project-'+i,name:'Project '+i}))],
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
    owned_ids = page.locator(".planning-view [id]").evaluate_all("nodes=>nodes.map(n=>n.id)")
    assert len(owned_ids) == len(set(owned_ids))
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
    expect(page.locator("#first [data-sort=name]")).to_have_text("Projet")
    assert page.locator("#first [data-part=timeline-body]").evaluate("n=>n.scrollLeft") == 500
    assert page.evaluate("""() => {try{instances[0].update({...snapshot,version:2});return false;}catch(e){return e.name==='ContractError';}}""")
    expect(page.locator("#first [data-sort=name]")).to_have_text("Projet")
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


def test_timeline_virtualization_pairing_inclusive_bars_and_safe_text(planning_page: Page) -> None:
    """Render bounded rows, distinct lanes and date geometry from the public contract."""
    page = planning_page
    page.evaluate("""() => {
      const tasks=Array.from({length:1000},(_,i)=>({id:'task-'+i,stableId:'stable-'+i,projectId:'same-project',
        name:i===0?'<img src=x onerror=alert(1)>':'Task '+i,start:'2028-02-28',end:i===1?'2028-02-28':'2028-03-01',progress:50}));
      tasks[999].end='2028-12-31';
      instances[0].update({...snapshot,scope:'large',projects:snapshot.projects.slice(0,1),tasks,
        overlays:[{id:'old',kind:'baseline',projectId:'same-project',tasks:[{...tasks[0],id:'renamed',name:'Previous'},
          {...tasks[0],id:'removed',stableId:'removed',name:'Removed'}]},
          {id:'other',kind:'alternative',projectId:'same-project',tasks:[{...tasks[0],id:'alternative-id',name:'New name'}]}]});
    }""")
    page.locator("#first [data-mode=Day]").click()
    page.get_by_role("button", name="Expand Project", exact=True).first.click()
    task = page.locator("#first .planning-bar[data-target-id=task-0]")
    expect(task).to_be_attached()
    assert task.evaluate("n=>parseFloat(n.style.width)") == 114
    assert task.locator(".planning-progress").evaluate("n=>n.style.width") == "50%"
    assert page.locator("#first .planning-milestone[data-target-id=task-1]").count() == 1
    row = task.locator("..")
    assert row.locator(".planning-bar").count() == 3
    assert row.locator(".planning-alternative").get_attribute("data-target-id") == "alternative-id"
    expect(page.locator("#first .planning-frozen-row").filter(has_text="Removed")).to_be_attached()
    assert page.locator("#first .planning-frozen-row img").count() == 0
    expect(page.locator("#first .planning-frozen-row").filter(has_text="<img")).to_contain_text("<img src=x onerror=alert(1)>")
    assert page.locator("#first .planning-timeline-row").count() <= 39
    original = task.evaluate("n=>{window.originalBar=n;return true}")
    assert original
    page.locator("#first [data-part=timeline-body]").evaluate("n=>n.scrollLeft=38")
    page.wait_for_timeout(50)
    assert page.evaluate("originalBar.isConnected")
    page.locator("#first [data-part=timeline-body]").evaluate("n=>n.scrollTop=20000")
    page.wait_for_function("Number(document.querySelector('#first .planning-timeline-row').dataset.rowIndex)>400")
    assert page.locator("#first .planning-timeline-row").count() <= 39
    page.locator("#first [data-part=timeline-body]").evaluate("n=>n.scrollTop=100000")
    expect(page.locator("#first .planning-bar[data-target-id=task-999]")).to_be_attached()


def test_visible_lazy_reads_are_injected_and_destroy_aborts_pending_work(planning_page: Page) -> None:
    """The mounted window uses the host provider and owns cancellation of its request."""
    page = planning_page
    page.evaluate("""() => {
      instances[0].destroy();window.reads=[];window.loadErrors=[];
      instances[0]=mount(document.getElementById('first'),{snapshot:{...snapshot,tasks:[],loadedProjectIds:[]},today:'2026-01-01',
        load:request=>new Promise((resolve,reject)=>reads.push({request,resolve,reject})),onLoadError:e=>loadErrors.push(e)});
    }""")
    page.wait_for_function("reads.length===1")
    assert page.evaluate("reads[0].request.projectIds.length") <= 25
    page.evaluate("instances[0].destroy();window.readAborted=reads[0].request.signal.aborted;reads[0].reject(new Error('late'))")
    page.wait_for_timeout(100)
    assert page.evaluate("readAborted")
    assert page.evaluate("loadErrors.length") == 0


def test_dependency_bundles_inspect_individual_members_without_hidden_metadata(planning_page: Page) -> None:
    """Collapsed paths retain members, keyboard inspection and instance-safe SVG IDs."""
    page = planning_page
    page.evaluate("""() => {
      const data={...snapshot,scope:'links',projects:[{id:'p',name:'First'},{id:'q',name:'Second'}],
        tasks:[{id:'a',projectId:'p',name:'A',start:'2026-01-01',end:'2026-01-03'},
          {id:'b',projectId:'q',name:'B',start:'2026-01-05',end:'2026-01-08'}],
        dependencies:Array.from({length:100},(_,i)=>({id:'link-'+i,type:'FS',lagDays:i,
          diagnostics:['Issue '+i],predecessor:{kind:'task',id:'a'},successor:{kind:'task',id:'b'}}))};
      instances[0].update(data);instances[1].update(data);
    }""")
    expect(page.locator("#first .planning-link")).to_have_count(1)
    assert page.locator("#first .planning-link").get_attribute("data-member-count") == "100"
    page.locator("#first .planning-link").press("Enter")
    inspector = page.locator("#first [data-part=dependency-inspector]")
    expect(inspector).to_be_visible()
    expect(page.locator("#second [data-part=dependency-inspector]")).to_be_hidden()
    inspector.get_by_role("combobox").select_option("99")
    expect(inspector).to_contain_text("Issue 99")
    expect(inspector).to_contain_text("99")
    inspector.get_by_role("button", name="Close", exact=True).click()
    page.evaluate("""instances[0].update({version:1,kind:'patch',scope:'links',revision:'r1',dependencies:[
      {id:'hidden',type:'SS',predecessor:{kind:'unavailable',name:'SECRET-METADATA'},successor:{kind:'task',id:'b'}}]})""")
    hidden = page.locator("#first .planning-link").filter(has=page.locator("path"))
    expect(hidden).to_have_count(2)
    page.locator("#first .planning-link").filter(has=page.locator("path")).nth(1).press("Enter")
    expect(inspector).to_contain_text("Unavailable")
    expect(inspector).not_to_contain_text("SECRET-METADATA")
    inspector.get_by_role("combobox").press("Escape")
    expect(inspector).to_be_hidden()
    ids = page.locator("clipPath").evaluate_all("nodes=>nodes.map(n=>n.id)")
    assert len(ids) == len(set(ids)) == 2
