"""Exercise EPPM's mounted adapter through its real Streamlit message boundary."""

from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from threading import Thread

import pytest

api = pytest.importorskip("playwright.sync_api")
expect = api.expect


@pytest.fixture(scope="module")
def eppm_component_origin() -> Iterator[str]:
    """Serve the assembled application component without a persistence service."""
    directory = Path(__file__).resolve().parents[1] / "app/presentation/assets/components/gantt"
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
def eppm_component(eppm_component_origin: str) -> Iterator[api.Page]:
    """Mount a small authorized portfolio and capture application events."""
    with api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get("EPPM_BENCHMARK_BROWSER"))
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 1200})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(eppm_component_origin)
            page.evaluate("""() => {
              window.events=[];window.send=args=>window.postMessage({type:'streamlit:render',args},location.origin);
              window.addEventListener('message',event=>{if(event.data?.type==='streamlit:setComponentValue')events.push(event.data.value);});
              window.host={tasks:[{id:'7',project_id:'1',name:'Build',start:'2027-01-01',end:'2027-01-05',progress:50,description:'Description',dependenciesList:[]}],
                project_summaries:[{id:1,name:'Editable',taskCount:1,start:'2027-01-01',end:'2027-01-05',projectDependencies:[]}],
                all_projects:[{id:'1',name:'Editable'},{id:'2',name:'Predecessor'}],scope_token:'server',view_scope:'selected',task_revision:'r1',data_revision:'server',loaded_project_ids:[1],
                permissions:{edit_all:true,baseline_all:true,baseline_projects:[1]},edit_enabled:false,filter_reset:0,alternatives:{},baseline_tasks:{},show_baseline:false,
                resource_pools:[{id:2,name:'Team',capacity:5,theoretical_capacity:5,has_assigned_resources:true,daily_usage_intervals:[['2027-01-01','2027-01-05',6]],selected_projects_daily_usage_intervals:[['2027-01-01','2027-01-05',3]]}],resource_pool_hierarchy:[]};
              send(host);
            }""")
            expect(page.locator(".planning-bar[data-target-kind=tasks]")).to_be_visible()
            yield page
            assert errors == []
        finally:
            browser.close()


def enable_edit(page: api.Page) -> None:
    """Acknowledge the real mode event as the Python callback does on a rerun."""
    page.get_by_role("checkbox", name="Enable edit mode", exact=True).check()
    page.wait_for_function("events.at(-1)?.action==='toggle_edit'")
    page.evaluate("send({edit_enabled:true,ack_nonce:events.at(-1).nonce})")
    expect(page.locator(".planning-bar[data-target-kind=tasks]")).to_have_attribute("data-editable", "true")


def test_eppm_current_editor_preserves_rejected_draft_and_routes_one_full_update(eppm_component: api.Page) -> None:
    """Task saves use existing Python fields and retain a failed user draft."""
    page = eppm_component
    enable_edit(page)
    page.locator(".planning-bar[data-target-kind=tasks]").dblclick()
    editor = page.locator(".planning-editor")
    editor.get_by_label("Step name", exact=True).fill("Changed")
    editor.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("events.at(-1)?.action==='update_task_full'")
    assert page.evaluate("events.at(-1).task_name") == "Changed"
    assert page.evaluate("events.filter(event=>event.action==='update_task_full').length") == 1
    page.evaluate("send({ack_nonce:events.at(-1).nonce,adapter_error:'Changed by another editor.'})")
    expect(editor.get_by_role("alert")).to_have_text("Changed by another editor.")
    expect(editor.get_by_label("Step name", exact=True)).to_have_value("Changed")
    page.evaluate("send({edit_enabled:false})")
    expect(editor.get_by_role("button", name="Save", exact=True)).to_be_disabled()


def test_eppm_project_dependency_batch_retains_failed_rows_and_explicitly_reloads(eppm_component: api.Page) -> None:
    """Project-only form, authorized choices, stale-save draft, and reload correlate."""
    page = eppm_component
    enable_edit(page)
    page.locator(".planning-frozen-row[data-target-kind=projects]").click(button="right")
    page.get_by_role("menuitem", name="Manage dependencies", exact=True).click()
    page.wait_for_function("events.at(-1)?.action==='load_project_dependencies'")
    page.evaluate("send({ack_nonce:events.at(-1).nonce,project_dependency_response:{project_id:'1',nonce:events.at(-1).nonce,panel:{revision:'panel-r1',dependencies:[]}}})")
    editor = page.locator("[data-part=project-dependency-editor]")
    expect(editor.get_by_role("heading")).to_have_text("Manage dependencies — Editable")
    expect(editor.locator("input[type=date]")).to_have_count(0)
    editor.get_by_role("button", name="Add predecessor", exact=True).click()
    page.wait_for_function("events.at(-1)?.action==='load_dependency_tasks'")
    assert page.evaluate("events.at(-1).project_id") == 2
    page.evaluate("send({ack_nonce:events.at(-1).nonce,dependency_response:{project_id:'2',nonce:events.at(-1).nonce,tasks:[{id:8,task_name:'External step'}]}})")
    expect(editor.get_by_label("Predecessor", exact=True)).to_be_enabled()
    expect(editor.get_by_label("Predecessor project", exact=True).locator("option")).to_have_count(1)
    editor.get_by_label("Lag", exact=True).fill("-2")
    editor.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("events.at(-1)?.action==='save_project_dependencies'")
    assert page.evaluate("events.at(-1).upserts[0].predecessor_project_id") == 2
    assert page.evaluate("events.at(-1).revision") == "panel-r1"
    page.evaluate("send({ack_nonce:events.at(-1).nonce,project_dependency_response:{project_id:'1',nonce:events.at(-1).nonce,action:'save_project_dependencies',error:'Source changed.'}})")
    expect(editor.get_by_role("alert")).to_contain_text("Source changed.")
    expect(editor.get_by_label("Lag", exact=True)).to_have_value("-2")
    editor.get_by_role("button", name="Reload dependencies (discard edits)", exact=True).click()
    page.wait_for_function("events.at(-1)?.action==='load_project_dependencies'")
    page.evaluate("send({ack_nonce:events.at(-1).nonce,project_dependency_response:{project_id:'1',nonce:events.at(-1).nonce,panel:{revision:'panel-r2',dependencies:[]}}})")
    expect(editor.locator(".planning-dependency-field")).to_have_count(0)
    expect(editor.get_by_role("button", name="Save", exact=True)).to_be_enabled()


def test_eppm_baseline_confirmation_and_alternative_colors_permissions_and_revision(eppm_component: api.Page) -> None:
    """Cancelled baseline commands emit nothing; comparisons target captured plan revision."""
    page = eppm_component
    enable_edit(page)
    page.locator(".planning-frozen-row[data-target-kind=projects]").click(button="right")
    page.get_by_role("menuitem", name="Scenario management", exact=False).click()
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("menuitem", name="Delete baseline", exact=True).click()
    assert page.evaluate("events.some(event=>event.action==='delete_project_baseline')") is False
    page.evaluate("""send({alternatives:{1:{id:21,revision:4,name:'Option A',editable:true,new_scenario:true,status:'draft',tasks:[
      {id:99,stable_id:7,task_name:'Renamed',start_date:'2027-01-02',end_date:'2027-01-06',progress_pct:50}],dependencies:[]}}})""")
    alternative = page.locator(".planning-bar[data-target-kind=tasks][data-lane=alternative]")
    expect(alternative).to_have_css("background-color", "rgb(125, 211, 252)")
    expect(alternative.locator(".planning-progress")).to_have_css("background-color", "rgb(56, 189, 248)")
    expect(page.locator(".planning-frozen-row[data-target-kind=tasks]")).to_have_css("background-color", "rgb(224, 242, 254)")
    expect(page.locator(".planning-bar[data-target-kind=tasks][data-lane=current]")).to_have_attribute("data-editable", "false")
    alternative.dblclick()
    editor = page.locator(".planning-editor")
    editor.get_by_label("Step name", exact=True).fill("Alternative edit")
    editor.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("events.at(-1)?.action==='alternative_action'")
    assert page.evaluate("[events.at(-1).plan_id,events.at(-1).revision,events.at(-1).id]") == [21, 4, 7]


def test_eppm_resource_period_drillthrough_and_retained_mode(eppm_component: api.Page) -> None:
    """Resource actions retain delivered pool/period/scope across ordinary reruns."""
    page = eppm_component
    page.locator("[data-mode=Day]").click()
    cell = page.locator(".planning-resource-cell[data-scope=selected]").first
    cell.click(button="right")
    page.get_by_role("menuitem", name="Show resource allocations", exact=True).click()
    page.wait_for_function("events.at(-1)?.action==='show_pool_allocations'")
    assert page.evaluate("events.at(-1).pool_id") == 2
    assert page.evaluate("events.at(-1).allocation_scope") == "selected"
    assert page.evaluate("events.at(-1).start_date===events.at(-1).end_date") is True
    page.evaluate("send({ack_nonce:events.at(-1).nonce})")
    expect(page.locator("[data-mode=Day]")).to_have_attribute("aria-pressed", "true")


def test_eppm_creation_and_cancelled_predecessor_read_keep_the_host_protocol(eppm_component: api.Page) -> None:
    """Create sends a project-owned task request; closed choice drafts stay closed."""
    page = eppm_component
    enable_edit(page)
    page.locator(".planning-frozen-row[data-target-kind=projects]").click(button="right")
    page.get_by_role("menuitem", name="Add step", exact=True).click()
    editor = page.locator(".planning-editor")
    editor.get_by_label("Step name", exact=True).fill("New step")
    editor.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("events.at(-1)?.action==='create_step_full'")
    assert page.evaluate("events.at(-1).project_id") == 1
    assert page.evaluate("events.at(-1).id ?? null") is None
    assert page.evaluate("events.at(-1).task_name") == "New step"
    page.evaluate("send({ack_nonce:events.at(-1).nonce,adapter_error:'Creation rejected safely.'})")
    expect(editor.get_by_role("alert")).to_have_text("Creation rejected safely.")
    editor.get_by_role("button", name="Add predecessor", exact=True).click()
    page.wait_for_function("events.at(-1)?.action==='load_dependency_tasks'")
    page.evaluate("window.choiceNonce=events.at(-1).nonce")
    editor.get_by_role("button", name="Cancel", exact=True).click()
    page.evaluate("send({ack_nonce:choiceNonce,dependency_response:{project_id:'1',nonce:choiceNonce,tasks:[{id:7,task_name:'Build'}]}})")
    expect(editor).to_be_hidden()
    assert page.evaluate("events.filter(event=>event.action==='create_step_full').length") == 1


def test_eppm_malformed_rebuild_keeps_valid_rows_and_a_safe_error(eppm_component: api.Page) -> None:
    """Bad internal DTO dates cannot replace a mounted valid display or expose input."""
    page = eppm_component
    page.evaluate("send({...host,scope_token:'next',tasks:[{...host.tasks[0],start:'SECRET-INVALID-DATE'}]})")
    expect(page.locator("[data-eppm-error]")).to_have_text("The planning display received invalid data.")
    expect(page.locator(".planning-bar[data-target-kind=tasks]")).to_have_attribute("data-start", "2027-01-01")
    expect(page.locator("[data-eppm-error]")).not_to_contain_text("SECRET")


def test_failed_predecessor_read_retains_choice_and_fields_until_explicit_retry(eppm_component: api.Page) -> None:
    """Failed choices retain selected identity, lag and other unsaved task fields."""
    page = eppm_component
    enable_edit(page)
    page.evaluate("""send({...host,edit_enabled:true,scope_token:'choices-source',tasks:[{...host.tasks[0],dependenciesList:[
      {id:9,predecessor_task_id:8,predecessor_owner_id:2,predecessor_task_name:'External step',link_type:'SS',lag_days:2}]}]})""")
    page.locator(".planning-bar[data-target-kind=tasks]").dblclick()
    page.wait_for_function("events.at(-1)?.action==='load_dependency_tasks'")
    editor = page.locator(".planning-editor")
    row = editor.locator(".planning-dependency-field")
    endpoint = row.get_by_role("combobox", name="Predecessor", exact=True)
    assert endpoint.input_value() and page.evaluate("JSON.parse(document.querySelector('.planning-editor [data-field=predecessor]').value).id") == "8"
    editor.get_by_label("Step name", exact=True).fill("Retained draft")
    row.locator("[data-field=lagDays]").fill("-2")
    page.evaluate("send({ack_nonce:events.at(-1).nonce,dependency_response:{project_id:'2',nonce:events.at(-1).nonce,error:'SECRET backend failure'}})")
    expect(row.get_by_role("alert")).to_contain_text("retry")
    expect(row.get_by_role("alert")).not_to_contain_text("SECRET")
    expect(endpoint).to_be_disabled()
    expect(endpoint.locator("option:checked")).to_have_text("External step")
    expect(editor.get_by_label("Step name", exact=True)).to_have_value("Retained draft")
    expect(row.locator("[data-field=lagDays]")).to_have_value("-2")
    editor.get_by_role("button", name="Save", exact=True).click()
    assert page.evaluate("events.some(event=>event.action==='update_task_full')") is False
    row.get_by_role("combobox", name="Predecessor project", exact=True).select_option("2")
    page.wait_for_function("events.filter(event=>event.action==='load_dependency_tasks').length===2")
    page.evaluate("send({ack_nonce:events.at(-1).nonce,dependency_response:{project_id:'2',nonce:events.at(-1).nonce,tasks:[{id:8,task_name:'External step'},{id:9,task_name:'Other'}]}})")
    expect(endpoint).to_be_enabled()
    expect(row.get_by_role("alert")).to_be_hidden()
    expect(endpoint.locator("option:checked")).to_have_text("External step")
    expect(editor.get_by_label("Step name", exact=True)).to_have_value("Retained draft")


def test_resource_badges_hover_extrema_and_comparison_commands_keep_their_meaning(eppm_component: api.Page) -> None:
    """Capacity deviations color badges; concise tooltips and comparison actions retain scope."""
    page = eppm_component
    page.evaluate("""send({...host,scope_token:'capacity-source',permissions:{...host.permissions,manage_shared:true},resource_pools:[
      {id:2,name:'Pool <A>',capacity:2,theoretical_capacity:2,has_assigned_resources:true,
       daily_assigned_capacity_intervals:[['2027-01-01','2027-01-01',1],['2027-01-02','2027-01-02',4]],
       daily_usage_intervals:[['2027-01-02','2027-01-02',5.2]],selected_projects_daily_usage_intervals:[['2027-01-02','2027-01-02',1.5]]}]})""")
    page.locator("[data-mode=Day]").click()
    expect(page.locator("[data-capacity-status=under]")).to_have_css("background-color", "rgb(255, 237, 213)")
    expect(page.locator("[data-capacity-status=over]")).to_have_css("background-color", "rgb(243, 232, 255)")
    capacity = page.locator(".planning-resource-cell[data-scope=assigned][data-start='2027-01-01']")
    expect(capacity).to_have_css("background-color", "rgba(0, 0, 0, 0)")
    expect(capacity).to_have_css("box-shadow", "none")
    page.locator(".planning-resource-left[data-scope=assigned]").hover()
    tooltip = page.get_by_role("tooltip")
    expect(tooltip).to_contain_text("Defined capacity: 2.0 FTE", timeout=1500)
    expect(tooltip).to_contain_text("Min assigned capacity: 1.0 FTE")
    expect(tooltip).to_contain_text("Max assigned capacity: 4.0 FTE")
    page.mouse.move(1490, 1190)
    selected = page.locator(".planning-resource-cell[data-scope=selected][data-start='2027-01-02']")
    selected.hover()
    expect(tooltip).to_contain_text("Available: 2.5 FTE", timeout=1500)
    expect(tooltip.locator(".planning-tooltip-status")).to_have_css("color", "rgb(74, 222, 128)")
    expect(tooltip).not_to_contain_text("Demand:")
    expect(tooltip).not_to_contain_text("2027-")
    assert tooltip.locator("a").count() == 0
    page.mouse.move(1490, 1190)
    page.locator(".planning-resource-cell[data-scope=total][data-start='2027-01-02']").hover()
    expect(tooltip).to_contain_text("Overallocated: 1.2 FTE", timeout=1500)
    expect(tooltip.locator(".planning-tooltip-status")).to_have_css("color", "rgb(248, 113, 113)")
    page.evaluate("send({alternative_pool_usage:{2:{selected:{'2027-01-02':2.5}}}})")
    comparison = page.locator(".planning-resource-cell[data-scope=alternative_selected][data-start='2027-01-02']")
    comparison.click(button="right")
    expect(page.locator("[data-command=go_to_pool_details]")).to_be_disabled()
    expect(page.locator("[data-command=show_pool_allocations]")).to_be_disabled()
    parent = page.locator("[data-command=filter_pool]")
    expect(parent).to_be_enabled()
    parent.focus()
    page.keyboard.press("Tab")
    expect(page.locator("[data-command=filter_pool_this]")).to_be_focused()


def test_task_resource_command_has_a_person_icon_and_retains_its_target(eppm_component: api.Page) -> None:
    """The application action retains its user-facing icon and task/project identity."""
    page = eppm_component
    enable_edit(page)
    page.locator(".planning-bar[data-target-kind=tasks]").click(button="right")
    command = page.locator("[data-command=manage_task_pools]")
    expect(command).to_have_accessible_name("Assign Resource")
    expect(command.locator("[aria-hidden=true]")).to_have_text("👤")
    command.click()
    page.wait_for_function("events.at(-1)?.action==='manage_task_pools'")
    assert page.evaluate("[events.at(-1).id,events.at(-1).project_id]") == [7, 1]
