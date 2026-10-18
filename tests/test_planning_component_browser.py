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
                  resources:[{id:'same-pool',name:'Pool',capacity:5},...Array.from({length:100},(_,i)=>({id:'pool-'+i,name:'Pool '+i,capacity:5}))]};
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


@pytest.fixture
def editable_page(planning_page: Page) -> Page:
    """Mount an opted-in host with a recorded event sink and opaque task IDs."""
    planning_page.evaluate("""() => {
      instances[0].destroy();window.events=[];
      window.editableSnapshot={version:1,kind:'snapshot',scope:'editable',revision:'r1',
        projects:[{id:'project',name:'Project'}],capabilities:{edit:true,manage:true},
        tasks:[{id:'alpha',stableId:'stable-alpha',projectId:'project',name:'Alpha',start:'2026-01-01',end:'2026-01-05',progress:20,description:'Safe details'},
          {id:'beta',stableId:'stable-beta',projectId:'project',name:'Beta',start:'2026-02-01',end:'2026-12-31',progress:0}],
        dependencies:[{id:'link',type:'FS',lagDays:2,predecessor:{kind:'task',id:'alpha'},successor:{kind:'task',id:'beta'}}]};
      instances[0]=mount(document.getElementById('first'),{snapshot:editableSnapshot,today:'2026-01-01',mode:'Day',grouped:false,editEnabled:true,
        onEvent:event=>events.push(event),contextActions:[{id:'group',label:'Host actions',children:[
          {id:'download',label:'Download',targetKinds:['tasks']},{id:'remove',label:'Delete',requiresEdit:true,capability:'manage'}]}]});
    }""")
    expect(planning_page.locator("#first .planning-bar[data-target-id=alpha]")).to_be_attached()
    return planning_page


@pytest.fixture
def resource_page(planning_page: Page) -> Page:
    """Mount hierarchical capacity/demand data with an ordinary web host event sink."""
    planning_page.evaluate("""() => {
      instances[0].destroy();window.events=[];
      const resources=[{id:'focus',name:'Capacity team',capacity:10,definedCapacity:10,hasAssignments:true,
        usage:{'2026-01-01':6,'2026-01-02':4},assignedCapacity:{'2026-01-02':2},selectedUsage:{'2026-01-02':3},
        comparisonUsage:{selected:{'2026-01-02':4}}},
        ...Array.from({length:1000},(_,i)=>({id:'pool-'+i,name:'Pool '+i,capacity:5}))];
      window.resourceSnapshot={...snapshot,scope:'resources',resources,
        hierarchy:[{id:'group',name:'Organization',children:resources.map(pool=>({id:'node-'+pool.id,resourceId:pool.id}))}],
        resourceFilter:{resourceId:'focus',name:'Capacity team',start:'2026-01-01',end:'2026-01-02',clearAction:'clear-filter'}};
      instances[0]=mount(document.getElementById('first'),{snapshot:resourceSnapshot,today:'2026-01-01',mode:'Month',onHeight:h=>heights[0].push(h),
        onEvent:e=>events.push(e),contextActions:[{id:'filter-period',label:'Filter consuming projects',targetKinds:['resources','hierarchy']},
          {id:'clear-filter',label:'Clear resource filter',targetKinds:['resources','hierarchy']}]});
    }""")
    expect(planning_page.locator("#first .planning-resource-cell").first).to_be_attached()
    return planning_page


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


def test_frozen_columns_resize_without_sorting_or_changing_another_instance(planning_page: Page) -> None:
    """Keyboard and pointer widths stay aligned with rows and belong to one view."""
    page = planning_page
    header = page.locator("#first [data-part=timeline-left-header] .planning-column-name")
    before = header.bounding_box()["width"]
    page.locator("#first [data-resize-column=name]").press("ArrowRight")
    expect(header).to_have_css("width", f"{int(before + 8)}px")
    row = page.locator("#first .planning-frozen-row .planning-column-name").first
    assert abs(header.bounding_box()["width"] - row.bounding_box()["width"]) < 1
    assert page.locator("#second [data-part=timeline-left-header] .planning-column-name").bounding_box()["width"] == before
    handle = page.locator("#first [data-resize-column=start]").bounding_box()
    page.mouse.move(handle["x"] + 2, handle["y"] + 10)
    page.mouse.down()
    page.mouse.move(handle["x"] + 22, handle["y"] + 10)
    page.mouse.up()
    expect(page.locator("#first [data-part=timeline-left-header] .planning-column-start")).to_have_css("width", "110px")
    page.locator("#first [data-resize-column=name]").press("Home")
    expect(header).to_have_css("width", "190px")


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
    page.locator("#first [data-part=splitter]").press("ArrowRight")
    page.wait_for_function("document.querySelector('#first [data-part=timeline-left]').clientWidth===435")
    assert first.bounding_box()["width"] == width + 10
    assert page.locator("#second [data-part=timeline-left]").bounding_box()["width"] == width
    splitter = page.locator("#first [data-part=splitter]").bounding_box()
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
    page.locator("#first [data-part=splitter]").press("ArrowRight")
    page.wait_for_function("document.querySelector('#first [data-part=timeline-left]').clientWidth===435")
    expect(page.locator("#second [data-mode=Day]")).to_have_attribute("aria-pressed", "true")


def test_invalid_mount_and_failed_callback_leave_no_partial_display(planning_page: Page) -> None:
    """Validate mount boundaries before DOM changes and unwind failed setup."""
    assert planning_page.evaluate("""() => {
      const host=document.createElement('div');document.body.append(host);
      for(const options of [null,{}, {snapshot,onHeight:1},{snapshot,today:'bad'},
        {snapshot,loading:null},{snapshot,loading:{batchSize:0}},{snapshot,resourceOptions:[]}]) {
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
    page.locator("#first [data-part=timeline-body]").evaluate("n=>{for(let top=0;top<=400;top+=10){n.scrollTop=top;n.dispatchEvent(new Event('scroll'));}}")
    page.wait_for_timeout(50)
    assert page.evaluate("originalBar.isConnected")
    page.locator("#first [data-part=timeline-body]").evaluate("n=>n.scrollTop=20000")
    page.wait_for_function("Number(document.querySelector('#first .planning-timeline-row').dataset.rowIndex)>400")
    assert page.locator("#first .planning-timeline-row").count() <= 39
    page.locator("#first [data-part=timeline-body]").evaluate("n=>n.scrollTop=100000")
    expect(page.locator("#first .planning-bar[data-target-id=task-999]")).to_be_attached()


def test_dependency_viewport_reuses_horizontal_clip_and_incoming_entry_markers(planning_page: Page) -> None:
    """SVG work is clipped, incoming members stay inspectable, and off-window stubs vanish."""
    page = planning_page
    page.evaluate("""() => {
      instances[0].update({...snapshot,scope:'entry-markers',projects:[{id:'p',name:'P'}],
        tasks:Array.from({length:1000},(_,i)=>({id:'task-'+i,projectId:'p',name:'Task '+i,start:'2026-01-01',end:'2026-12-31'})),
        dependencies:[0,1].map(i=>({id:'incoming-'+i,type:'FS',lagDays:i,predecessor:{kind:'task',id:'outside',projectId:'outside'},successor:{kind:'task',id:'task-1'}}))});
    }""")
    page.locator("#first [data-mode=Day]").click()
    page.get_by_role("button", name="Expand P", exact=True).click()
    expect(page.get_by_role("button", name="Collapse P", exact=True)).to_be_visible()
    marker = page.locator("#first .planning-entry-marker")
    expect(marker).to_have_count(1)
    expect(page.locator("#first .planning-link")).to_have_attribute("data-member-count", "2")
    marker.dispatch_event("click")
    inspector = page.locator("#first [data-part=dependency-inspector]")
    expect(inspector).to_be_visible()
    expect(inspector.get_by_role("combobox").locator("option")).to_have_count(2)
    inspector.get_by_role("button", name="Close", exact=True).click()
    body = page.locator("#first [data-part=timeline-body]")
    body.evaluate("n=>n.scrollLeft=3000")
    svg = page.locator("#first [data-part=dependencies]")
    page.wait_for_function("Number(document.querySelector('#first [data-part=dependencies]').getAttribute('viewBox').split(' ')[0])===2400")
    before = svg.get_attribute("viewBox")
    assert float(svg.get_attribute("width")) <= body.evaluate("n=>n.clientWidth") + 1200
    body.evaluate("n=>n.scrollLeft=3100")
    page.wait_for_timeout(50)
    expect(svg).to_have_attribute("viewBox", before)
    body.evaluate("n=>n.scrollLeft=8000")
    page.wait_for_function("Number(document.querySelector('#first [data-part=dependencies]').getAttribute('viewBox').split(' ')[0])===7400")
    body.evaluate("n=>n.scrollTop=20000")
    expect(marker).to_have_count(0)
    expect(page.locator("#first .planning-link")).to_have_count(0)
    assert page.locator("#first .planning-timeline-row").count() <= 39


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


def test_visible_read_failure_requires_explicit_retry(planning_page: Page) -> None:
    """The mounted loader keeps valid rows and exposes a safe nonrepeating retry."""
    page = planning_page
    page.evaluate("""() => {
      instances[0].destroy();window.reads=[];
      instances[0]=mount(document.getElementById('first'),{snapshot:{...snapshot,tasks:[],loadedProjectIds:[]},today:'2026-01-01',
        load:request=>new Promise((resolve,reject)=>reads.push({request,resolve,reject}))});
    }""")
    page.wait_for_function("reads.length===1")
    page.evaluate("reads[0].reject(new Error('private backend detail'))")
    retry = page.locator("#first [data-part=retry-load]")
    expect(retry).to_be_visible()
    expect(page.locator("#first .planning-status")).not_to_contain_text("private backend detail")
    page.wait_for_timeout(150)
    assert page.evaluate("reads.length") == 1
    retry.click()
    page.wait_for_function("reads.length===2")
    page.evaluate("""reads[1].resolve({version:1,kind:'patch',scope:reads[1].request.scope,revision:reads[1].request.revision,
      replaceProjectIds:reads[1].request.projectIds,tasks:[]})""")
    expect(retry).to_be_hidden()


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


def test_task_editor_preserves_draft_and_handles_rejection_and_revocation(editable_page: Page) -> None:
    """Draft values survive unrelated patches; a stale Save cannot bypass revoked hints."""
    page = editable_page
    page.locator("#first .planning-bar[data-target-id=alpha]").dblclick(position={"x": 30, "y": 10})
    editor = page.locator("#first .planning-editor")
    expect(editor).to_be_visible()
    editor.locator("[data-field=name]").fill("Unsaved name")
    page.evaluate("instances[0].update({version:1,kind:'patch',scope:'editable',revision:'r1',tasks:[{...editableSnapshot.tasks[1],name:'Updated Beta'}]})")
    expect(editor.locator("[data-field=name]")).to_have_value("Unsaved name")
    editor.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("events.filter(e=>e.type==='task').length===1")
    assert page.evaluate("events.length") == 1
    assert page.evaluate("events[0].values.name") == "Unsaved name"
    page.evaluate("instances[0].update({version:1,kind:'response',scope:'editable',revision:'r1',requestId:events[0].requestId,accepted:false,error:'Changed by another editor'})")
    expect(editor.get_by_role("alert")).to_have_text("Changed by another editor")
    expect(editor.locator("[data-field=name]")).to_have_value("Unsaved name")
    page.evaluate("instances[0].update({version:1,kind:'patch',scope:'editable',revision:'r1',capabilities:{edit:false}})")
    expect(editor.get_by_role("button", name="Save", exact=True)).to_be_disabled()
    page.evaluate("document.querySelector('#first .planning-editor').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}))")
    assert page.evaluate("events.length") == 1
    editor.get_by_role("button", name="Cancel", exact=True).click()
    expect(editor).to_be_hidden()


def test_pointer_dates_reconcile_rejection_acceptance_and_mid_drag_revocation(editable_page: Page) -> None:
    """A drag emits one request, rolls back rejection, and cancels after revocation."""
    page = editable_page
    bar = page.locator("#first .planning-bar[data-target-id=alpha]")
    bounds = bar.bounding_box()
    page.mouse.move(bounds["x"] + 20, bounds["y"] + 10)
    page.mouse.down()
    page.mouse.move(bounds["x"] + 96, bounds["y"] + 10, steps=3)
    page.mouse.up()
    page.wait_for_function("events.length===1")
    assert page.evaluate("events[0].type") == "dates"
    assert page.evaluate("events[0].start") == "2026-01-03"
    page.evaluate("instances[0].update({version:1,kind:'response',scope:'editable',revision:'r1',requestId:events[0].requestId,accepted:false,error:'No'})")
    page.wait_for_function("document.querySelector('#first .planning-bar[data-target-id=alpha]').style.left==='114px'")
    expect(page.locator("#first .planning-status")).to_have_text("No")
    bounds = bar.bounding_box()
    page.mouse.move(bounds["x"] + 20, bounds["y"] + 10)
    page.mouse.down()
    page.mouse.move(bounds["x"] + 58, bounds["y"] + 10)
    page.mouse.up()
    page.wait_for_function("events.filter(e=>e.type==='dates').length===2")
    page.evaluate("""() => {
      const event=events.findLast(e=>e.type==='dates');
      instances[0].update({version:1,kind:'patch',scope:'editable',revision:'r1',tasks:[{...editableSnapshot.tasks[0],start:event.start,end:event.end}]});
      instances[0].update({version:1,kind:'response',scope:'editable',revision:'r1',requestId:event.requestId,accepted:true});
    }""")
    expect(bar).to_have_attribute("data-start", "2026-01-02")
    bounds = bar.bounding_box()
    page.mouse.move(bounds["x"] + 20, bounds["y"] + 10)
    page.mouse.down()
    page.mouse.move(bounds["x"] + 58, bounds["y"] + 10)
    page.evaluate("instances[0].update({version:1,kind:'patch',scope:'editable',revision:'r1',capabilities:{edit:false}})")
    page.mouse.up()
    page.wait_for_timeout(260)
    assert page.evaluate("events.filter(e=>e.type==='dates').length") == 2
    assert page.locator("#first .planning-dragging").count() == 0


def test_menu_keyboard_tooltip_delay_and_dependency_editor(editable_page: Page) -> None:
    """Keyboard menus invoke one host command and hover state is scoped/cancellable."""
    page = editable_page
    bar = page.locator("#first .planning-bar[data-target-id=alpha]")
    bar.press("Shift+F10")
    menu = page.locator("#first [role=menu]")
    expect(menu).to_be_visible()
    menu.get_by_role("menuitem", name="Host actions").focus()
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Enter")
    page.wait_for_function("events.length===1")
    assert page.evaluate("events[0].command") == "download"
    bar.hover(position={"x": 20, "y": 10})
    tooltip = page.locator("#first [role=tooltip]")
    page.wait_for_timeout(600)
    expect(tooltip).to_be_hidden()
    expect(tooltip).to_contain_text("Safe details", timeout=1200)
    expect(tooltip).to_be_visible()
    page.mouse.move(1300, 1500)
    expect(tooltip).to_be_hidden()
    page.locator("#first [data-control=hover]").uncheck()
    expect(bar).to_have_attribute("title", "Alpha · 2026-01-01 → 2026-01-05")
    page.locator("#first .planning-link").press("Enter")
    inspector = page.locator("#first [data-part=dependency-inspector]")
    inspector.get_by_role("button", name="Edit", exact=True).click()
    editor = page.locator("#first .planning-editor")
    expect(editor).to_be_visible()
    editor.locator("[data-field=type]").select_option("SF")
    editor.locator("[data-field=lagDays]").fill("-2")
    editor.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("events.some(e=>e.type==='dependency')")
    assert page.evaluate("events.find(e=>e.type==='dependency').values.type") == "SF"
    assert page.evaluate("events.find(e=>e.type==='dependency').values.lagDays") == -2


def test_shared_menu_visual_standard_matches_host_context_menus(editable_page: Page) -> None:
    """Extracted menus retain the host menu's panel, item and focus appearance."""
    from app.presentation.components.context_menu import CONTEXT_MENU_CSS

    page = editable_page
    menu_css = CONTEXT_MENU_CSS[CONTEXT_MENU_CSS.index(".context-menu {"):]
    page.add_style_tag(content=menu_css)
    page.evaluate("""() => {
      const reference=document.createElement('div');reference.id='reference-menu';
      reference.className='context-menu';reference.style.font='12px system-ui,sans-serif';
      reference.innerHTML='<button class="context-menu-item">Reference</button>';
      document.body.append(reference);
    }""")
    page.locator("#first .planning-bar[data-target-id=alpha]").press("Shift+F10")
    panel = page.locator("#first [data-menu-depth='0']")
    item = panel.get_by_role("menuitem").first
    properties = [
        "position", "backgroundColor", "color", "border", "borderRadius",
        "boxShadow", "zIndex", "minWidth", "padding", "boxSizing", "maxWidth",
        "maxHeight", "overflowY", "display", "alignItems", "gap", "fontSize",
        "fontWeight", "textAlign", "margin", "cursor", "transition",
    ]
    measure = "(node, properties) => Object.fromEntries(properties.map(key=>[key,getComputedStyle(node)[key]]))"
    assert panel.evaluate(measure, properties) == page.locator("#reference-menu").evaluate(measure, properties)
    # Moving focus off the first item compares ordinary as well as focus styles.
    page.locator("#outside").focus()
    item.evaluate("node=>Promise.all(node.getAnimations().map(animation=>animation.finished))")
    assert item.evaluate(measure, properties) == page.locator("#reference-menu button").evaluate(measure, properties)
    item.focus()
    item.evaluate("node=>Promise.all(node.getAnimations().map(animation=>animation.finished))")
    actual = item.evaluate(measure, properties)
    page.locator("#reference-menu button").focus()
    page.locator("#reference-menu button").evaluate("node=>Promise.all(node.getAnimations().map(animation=>animation.finished))")
    assert actual == page.locator("#reference-menu button").evaluate(measure, properties)


def test_nested_menu_panels_fit_the_viewport_and_support_tab_and_back_navigation(editable_page: Page) -> None:
    """Nested panels remain outside root scrolling, inside the viewport, and keyboard reachable."""
    page = editable_page
    page.locator("#first .planning-bar[data-target-id=alpha]").dispatch_event("contextmenu", {"clientX": 1398, "clientY": 1598})
    root = page.locator("#first [data-menu-depth='0']")
    box = root.bounding_box()
    assert box["x"] + box["width"] <= 1390
    assert box["y"] + box["height"] <= 1590
    parent = root.get_by_role("menuitem", name="Host actions")
    parent.focus()
    child = page.locator("#first [data-menu-depth='1']")
    expect(child).to_be_visible()
    assert child.evaluate("node=>node.parentElement.matches('.planning-view')")
    box = child.bounding_box()
    assert box["x"] >= 10 and box["x"] + box["width"] <= 1390
    assert box["y"] >= 10 and box["y"] + box["height"] <= 1590
    page.keyboard.press("Tab")
    expect(child.get_by_role("menuitem", name="Download", exact=True)).to_be_focused()
    page.keyboard.press("ArrowLeft")
    expect(child).to_have_count(0)
    expect(parent).to_be_focused()
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Space")
    page.wait_for_function("events.length===1")
    assert page.evaluate("events[0].command") == "download"


def test_scroll_retains_unchanged_control_text_and_updates_host_labels(resource_page: Page) -> None:
    """Scrolling preserves static control nodes; actual label updates still render."""
    page = resource_page
    page.locator("#first [data-mode=Day]").click()
    expect(page.locator("#first [data-mode=Day]")).to_have_attribute("aria-pressed", "true")
    page.evaluate("() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
    page.evaluate("""() => {
      window.controlTextNodes=[document.querySelector('#first .planning-resource-count').firstChild,
        document.querySelector('#first [data-part=resource-left-header]').firstChild,
        document.querySelector('#first [data-mode=Day]').firstChild];
      document.querySelector('#first [data-part=timeline-body]').scrollLeft=20;
    }""")
    page.wait_for_function("document.querySelector('#first [data-part=resource-body]').scrollLeft===20")
    page.evaluate("() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
    assert page.evaluate("""() => controlTextNodes.every((node,index)=>node===
      document.querySelector(['#first .planning-resource-count','#first [data-part=resource-left-header]',
        '#first [data-mode=Day]'][index]).firstChild)""")
    page.evaluate("instances[0].update({version:1,kind:'patch',scope:'resources',revision:'r1',labels:{pools:'Teams',resource:'Capacity',day:'Daily'}})")
    expect(page.locator("#first .planning-resource-count")).to_contain_text("Teams")
    expect(page.locator("#first [data-part=resource-left-header]")).to_contain_text("Capacity")
    expect(page.locator("#first [data-mode=Day]")).to_have_text("Daily")


def test_creation_patch_expands_only_its_project_and_preserves_the_viewport(planning_page: Page) -> None:
    """A host creation patch must not jump away from a retained scroll position."""
    page = planning_page
    page.evaluate("""() => {
      instances[0].destroy();
      const projects=Array.from({length:100},(_,i)=>({id:'p'+i,name:'Project '+i,taskCount:1,start:'2026-01-01',end:'2026-12-31'}));
      const tasks=projects.map(project=>({id:'t'+project.id,projectId:project.id,name:'Task',start:project.start,end:project.end}));
      instances[0]=mount(document.getElementById('first'),{snapshot:{version:1,kind:'snapshot',scope:'creation',revision:'r1',projects,tasks},mode:'Day',today:'2026-01-01'});
    }""")
    body = page.locator("#first [data-part=timeline-body]")
    body.evaluate("node=>{node.scrollTop=1800;node.scrollLeft=920}")
    page.wait_for_function("document.querySelector('#first [data-part=timeline-header]').scrollLeft===920")
    page.evaluate("""instances[0].update({version:1,kind:'patch',scope:'creation',revision:'r1',replaceProjectIds:['p2'],
      tasks:[{id:'created',projectId:'p2',name:'Created',start:'2026-01-01',end:'2026-12-31'}],viewHints:{focusProjectId:'p2'}})""")
    page.wait_for_timeout(50)
    assert body.evaluate("node=>[node.scrollTop,node.scrollLeft]") == [1800, 920]
    body.evaluate("node=>node.scrollTop=0")
    expect(page.locator("#first").get_by_role("button", name="Collapse Project 2", exact=True)).to_be_visible()
    expect(page.locator("#first").get_by_role("button", name="Expand Project 3", exact=True)).to_be_visible()


def test_comparison_editing_targets_alternative_and_invalidates_removed_draft(editable_page: Page) -> None:
    """Baseline/current bars stay read-only while an alternative draft retains its identity."""
    page = editable_page
    page.evaluate("""() => {
      window.alternative={...editableSnapshot.tasks[0],id:'alternative-alpha',name:'Alternative'};
      instances[0].update({...editableSnapshot,overlays:[{id:'baseline',kind:'baseline',projectId:'project',tasks:[{...alternative,id:'baseline-alpha'}]},
        {id:'alternative',kind:'alternative',projectId:'project',tasks:[alternative]}]});
    }""")
    current = page.locator("#first .planning-current[data-target-id=alpha]")
    expect(current).to_have_attribute("data-editable", "false")
    current.press("Enter")
    expect(page.locator("#first .planning-editor")).to_be_hidden()
    page.locator("#first .planning-alternative[data-target-id=alternative-alpha]").press("Enter")
    editor = page.locator("#first .planning-editor")
    expect(editor).to_be_visible()
    editor.locator("[data-field=name]").fill("Alternative draft")
    editor.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("events.some(e=>e.type==='task')")
    assert page.evaluate("events.find(e=>e.type==='task').overlayId") == "alternative"
    page.evaluate("""() => {
      const event=events.find(e=>e.type==='task');
      instances[0].update({version:1,kind:'response',scope:'editable',revision:'r1',requestId:event.requestId,accepted:false,error:'Conflict'});
      instances[0].update({version:1,kind:'patch',scope:'editable',revision:'r1',overlays:[]});
    }""")
    expect(editor).to_be_hidden()
    expect(page.locator("#first .planning-status")).to_contain_text("no longer available")


def test_resize_progress_and_pending_tooltip_disposal(editable_page: Page) -> None:
    """Resize and progress handles produce separate single intentions and dispose safely."""
    page = editable_page
    bar = page.locator("#first .planning-bar[data-target-id=alpha]")
    handle = bar.locator(".planning-handle-progress").bounding_box()
    page.mouse.move(handle["x"] + 2, handle["y"] + handle["height"] / 2)
    page.mouse.down()
    page.mouse.move(handle["x"] + 40, handle["y"] + handle["height"] / 2)
    page.mouse.up()
    page.wait_for_function("events.length===1")
    assert page.evaluate("events[0].type") == "progress"
    assert page.evaluate("events[0].progress") == 40
    page.evaluate("instances[0].update({version:1,kind:'response',scope:'editable',revision:'r1',requestId:events[0].requestId,accepted:false})")
    expect(page.locator("#first .planning-status")).to_be_visible()
    handle = bar.locator(".planning-handle-start").bounding_box()
    page.mouse.move(handle["x"] + 2, handle["y"] + 8)
    page.mouse.down()
    page.mouse.move(handle["x"] + 40, handle["y"] + 8)
    page.mouse.up()
    page.wait_for_function("events.length===2")
    assert page.evaluate("events[1].type") == "dates"
    assert page.evaluate("events[1].start") == "2026-01-02"
    assert page.evaluate("events[1].end") == "2026-01-05"
    page.evaluate("instances[0].update({version:1,kind:'response',scope:'editable',revision:'r1',requestId:events[1].requestId,accepted:false})")
    bar.hover(position={"x": 20, "y": 10})
    page.wait_for_timeout(100)
    page.evaluate("instances[0].destroy();instances[0].destroy()")
    page.wait_for_timeout(1100)
    assert page.locator("#first [role=tooltip]").count() == 0
    assert page.evaluate("events.length") == 2


def test_task_dependency_fields_and_invalid_date_edits(editable_page: Page) -> None:
    """Incoming link edits stay in one task intention; malformed dates never leave the view."""
    page = editable_page
    page.locator("#first .planning-bar[data-target-id=beta]").press("Enter")
    editor = page.locator("#first .planning-editor")
    editor.locator("[data-field=type]").select_option("FF")
    editor.locator("[data-field=lagDays]").fill("3")
    editor.locator("[data-field=predecessor]").select_option('{"kind":"project","id":"project"}')
    editor.locator("[data-field=start]").fill("2027-01-01")
    editor.get_by_role("button", name="Save", exact=True).click()
    expect(editor.get_by_role("alert")).to_have_text("Check the dates and values before saving.")
    assert page.evaluate("events.length") == 0
    editor.locator("[data-field=start]").fill("2026-02-01")
    editor.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("events.length===1")
    assert page.evaluate("events[0].type") == "task"
    assert page.evaluate("events[0].values.dependencies[0].type") == "FF"
    assert page.evaluate("events[0].values.dependencies[0].lagDays") == 3
    assert page.evaluate("events[0].values.dependencies[0].predecessor.kind") == "project"


def test_single_selection_and_destroy_during_active_drag(editable_page: Page) -> None:
    """A single selection emits once and active pointer capture cannot survive unmount."""
    page = editable_page
    bar = page.locator("#first .planning-bar[data-target-id=alpha]")
    bar.click(position={"x": 20, "y": 10})
    page.wait_for_function("events.length===1")
    assert page.evaluate("events[0].type") == "select"
    expect(bar).to_have_class("planning-bar planning-current planning-selected")
    bounds = bar.bounding_box()
    page.mouse.move(bounds["x"] + 20, bounds["y"] + 10)
    page.mouse.down()
    page.mouse.move(bounds["x"] + 58, bounds["y"] + 10)
    page.evaluate("instances[0].destroy();instances[0].destroy()")
    page.mouse.up()
    page.wait_for_timeout(260)
    assert page.evaluate("events.length") == 1
    assert page.locator("#first .planning-view").count() == 0


def test_resource_period_extrema_comparison_warning_and_header_alignment(resource_page: Page) -> None:
    """Actual mounted cells expose distinct demand, minimum capacity and daily excess."""
    page = resource_page
    selector = '#first .planning-resource-cell[data-target-id=focus][data-start="2026-01-01"]'
    total = page.locator(selector + '[data-scope=total]')
    expect(total).to_have_text("6.0")
    expect(total).to_have_attribute("data-capacity", "2")
    expect(total).to_have_attribute("data-excess", "2")
    expect(total).to_have_attribute("data-overallocated", "true")
    expect(page.locator(selector + '[data-scope=assigned]')).to_have_text("2.0")
    expect(page.locator(selector + '[data-scope=selected]')).to_have_attribute("data-excess", "1")
    expect(page.locator(selector + '[data-scope=alternative_selected]')).to_have_text("4.0")
    expect(page.locator('#first [data-part=resource-header-inner] [data-start="2026-01-01"]')).to_have_class("planning-header-cell planning-current planning-resource-overallocated")
    header_x = page.locator('#first [data-part=timeline-header-inner] [data-start="2026-01-01"]').bounding_box()["x"]
    assert abs(total.bounding_box()["x"] - header_x) <= 1
    assert page.locator("#first .planning-resource-right").count() <= 40
    assert page.locator("#first .planning-resource-cell").count() < 40 * 30
    expect(page.locator("#first [data-part=resource-filter]")).to_contain_text("Capacity team")
    assert page.evaluate("heights[0].at(-1)===Math.ceil(document.querySelector('#first .planning-view').getBoundingClientRect().height)")


def test_resource_period_actions_single_double_click_and_keyboard(resource_page: Page) -> None:
    """Allocation selection and host commands retain periods; double-click expands/collapses."""
    page = resource_page
    cell = page.locator('#first .planning-resource-cell[data-target-id=focus][data-start="2026-01-01"][data-scope=total]')
    cell.click()
    page.wait_for_function("events.length===1")
    assert page.evaluate("events[0].type") == "select"
    assert page.evaluate("events[0].context.start") == "2026-01-01"
    assert page.evaluate("events[0].context.scope") == "total"
    cell.press("Shift+F10")
    page.get_by_role("menuitem", name="Filter consuming projects", exact=True).click()
    page.wait_for_function("events.length===2")
    assert page.evaluate("events[1].command") == "filter-period"
    assert page.evaluate("events[1].context.end") == "2026-01-31"
    page.locator("#first [data-part=resource-filter]").get_by_role("button", name="Clear resource filter").click()
    page.wait_for_function("events.length===3")
    assert page.evaluate("events[2].command") == "clear-filter"
    page.locator('#first .planning-resource-left[data-target-id=focus][data-scope=assigned]').dblclick(position={"x": 180, "y": 10})
    page.wait_for_timeout(350)
    assert page.evaluate("events.length") == 3
    expect(page.locator('#first .planning-resource-left[data-target-id=focus][data-scope=assigned]')).to_have_count(0)
    page.locator('#first .planning-resource-left[data-target-id=focus][data-scope=total]').get_by_role("button", name="Expand Capacity team").press("Enter")
    expect(page.locator('#first .planning-resource-left[data-target-id=focus][data-scope=assigned]')).to_have_count(1)
    cell.focus()
    page.keyboard.press("ArrowRight")
    assert page.evaluate("document.activeElement.dataset.start") == "2026-02-01"
    page.keyboard.press("ArrowDown")
    assert page.evaluate("document.activeElement.dataset.scope") == "selected"


def test_resource_filters_scroll_virtualization_and_optional_layout(resource_page: Page) -> None:
    """Both dimensions remain bounded and grid controls resize the complete frame."""
    page = resource_page
    page.locator("#first [data-mode=Day]").click()
    page.locator("#first [data-part=resource-body]").evaluate("n=>{n.scrollTop=10000;n.scrollLeft=4000}")
    page.wait_for_function("document.querySelector('#first [data-part=timeline-body]').scrollLeft===4000")
    page.wait_for_function("Number(document.querySelector('#first .planning-resource-right').dataset.rowIndex)>400")
    assert page.locator("#first .planning-resource-right").count() <= 40
    assert page.locator("#first .planning-resource-cell").count() < 40 * 30
    assert page.locator("#first [data-part=resource-left]").evaluate("n=>n.scrollTop") == 10000
    page.locator("#first [data-resource-control=onlyOverallocated]").check()
    expect(page.locator("#first .planning-resource-count")).to_have_text("1 Pool")
    page.locator("#first [data-resource-control=showSelected]").uncheck()
    expect(page.locator('#first .planning-resource-cell[data-scope=selected]')).to_have_count(0)
    page.locator("#first [data-resource-control=collapse]").click()
    expect(page.locator("#first [data-part=resource-panel]")).to_be_hidden()
    expect(page.locator("#first [data-part=resource-heading]")).to_be_visible()
    page.evaluate("instances[0].update({...resourceSnapshot,scope:'no-resources',resources:[]})")
    expect(page.locator("#first [data-part=resource-heading]")).to_be_hidden()
    assert page.locator("#first [data-part=resource-body]").evaluate("n=>n.scrollTop") == 0


def test_baseline_pairing_preserves_row_height_bar_proportions_and_former_task_color(planning_page: Page) -> None:
    """Baseline overlays retain compact rows, smaller current bars and former tasks."""
    page = planning_page
    page.evaluate("""() => {
      instances[0].destroy();window.baselineHost={version:1,kind:'snapshot',scope:'baseline',revision:'r1',
        projects:[{id:'p',name:'Project'}],tasks:[{id:'live',projectId:'p',name:'Live',start:'2026-01-01',end:'2026-01-05'}],
        viewHints:{expandedProjectIds:['p']}};
      instances[0]=mount(document.getElementById('first'),{snapshot:baselineHost,mode:'Day',today:'2026-01-01'});
    }""")
    current = page.locator('#first .planning-bar[data-target-kind=tasks][data-lane=current]')
    summary = page.locator('#first .planning-bar[data-target-kind=projects][data-lane=current]')
    before = current.bounding_box()['height']
    project_before = summary.bounding_box()['height']
    row_height = page.locator('#first .planning-frozen-row[data-target-id=live]').bounding_box()['height']
    page.evaluate("""instances[0].update({...baselineHost,overlays:[{id:'baseline',kind:'baseline',projectId:'p',tasks:[
      baselineHost.tasks[0],{id:'former',projectId:'p',name:'Former task',start:'2026-01-06',end:'2026-01-07'}]}]})""")
    baseline = page.locator('#first .planning-bar[data-target-id=live][data-lane=baseline]')
    expect(baseline).to_be_visible()
    assert current.bounding_box()['height'] == pytest.approx(before * .7, abs=.1)
    assert summary.bounding_box()['height'] == pytest.approx(project_before * .7, abs=.1)
    assert page.locator('#first .planning-frozen-row[data-target-id=live]').bounding_box()['height'] == row_height
    assert baseline.bounding_box()['y'] > current.bounding_box()['y'] + current.bounding_box()['height']
    former = page.locator('#first .planning-frozen-row[data-target-id=former]')
    expect(former).to_have_attribute('data-lane', 'baseline')
    expect(former.locator('.planning-column-name')).to_have_css('color', 'rgb(147, 51, 234)')
    expect(page.locator('#first .planning-bar[data-target-id=former][data-lane=current]')).to_have_count(0)
    page.evaluate('instances[0].update(baselineHost)')
    expect(former).to_have_count(0)
    assert current.bounding_box()['height'] == before
