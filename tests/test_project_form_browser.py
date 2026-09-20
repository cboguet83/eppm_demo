"""Real browser checks for atomic project forms and explicit server actions."""

import json

import pytest

from tests.test_dialog_browser import popup_server as popup_server, expect, sync_playwright


_APP = '''
import time
import streamlit as st
from app.presentation.components.project_form import project_form

st.session_state.shell_runs = st.session_state.get("shell_runs", 0) + 1
st.write(f"Shell runs: {st.session_state.shell_runs}")

def open_form():
    st.session_state.form = dict(token="draft", title="Project form", tabs=["General", "More", "Useful links", "WBS"],
        links_tab="Useful links", wbs_tab="WBS", wbs=[],
        wbs_options=[dict(id=1,code="FULL",description="Full capacity",available=100),dict(id=2,code="#SHARED",description="Shared capacity",available=40),dict(id=3,code="TAKEN",description="Fully allocated",available=0)],
        wbs_labels=dict(code="WBS code",allocation="Allocation (%)",available="Available: {percentage}%",add="Add WBS",remove="Remove WBS",select="Select a WBS",empty="No WBS"),
        fields=[dict(key=k,label=k,kind=kind,tab=tab,options=options,disabled=False)
                for k,kind,tab,options in [
                    ("name","text",None,[]), ("amount","number",None,[]),
                    ("due","date","General",[]), ("tags","tags","General",[("Initial","Initial"),("One","One"),("Two","Two")]),
                    ("choices","multi","More",[("one","One"),("two","Two")])]],
        values=dict(name="Draft",amount=100,due="2027-04-12",tags=["Initial"],choices=["one"]),
        links=[], messages={}, can_save=True,can_delete=True,error="",submit="Save",cancel="Cancel",
        links_label="Custom links",alias_label="Display alias")
    st.rerun("projectmodal")

def action():
    event=st.session_state.portfolio_project_form["action"]
    st.session_state.events=st.session_state.get("events",[])+[event]
    if event["kind"]=="save" and not event["values"]["name"]:
        time.sleep(.3)
        st.session_state.form.update(values=event["values"],links=event["links"],wbs=event["wbs"],error="Name is required")
    else:
        st.session_state.form=None

st.button("Open project",on_click=open_form)
@st.fragment(key="projectmodal")
def modal():
    project_form(st.session_state.get("form"),on_action=action)
    st.code(__import__("json").dumps(st.session_state.get("events",[])))
modal()
'''

_SAMPLE = """
window.openedForms=[];
const show=HTMLDialogElement.prototype.showModal;
HTMLDialogElement.prototype.showModal=function() {
    window.openedForms.push({fields:this.querySelectorAll('input,textarea,select').length,
        buttons:this.querySelectorAll('button').length, title:this.querySelector('h2')?.textContent});
    return show.call(this);
};
"""


@pytest.mark.parametrize("popup_server", [_APP.replace('choices=["one"]', 'choices=["two","one"]')],
                         indirect=True, ids=["stored-selection-order"])
@pytest.mark.parametrize("change_selection", [False, True])
def test_untouched_selection_order_survives_save_and_validation_retry(popup_server, change_selection):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1200, "height": 900})
            page.goto(popup_server)
            page.get_by_role("button", name="Open project").click()
            modal = page.get_by_role("dialog")
            if change_selection:
                modal.get_by_role("tab", name="More").click()
                modal.get_by_label("choices").select_option(["one"])
            expected = ["one"] if change_selection else ["two", "one"]
            modal.get_by_label("name", exact=True).fill("")
            modal.get_by_role("button", name="Save", exact=True).click()
            expect(modal.get_by_role("alert")).to_have_text("Name is required")
            first = json.loads(page.locator("pre").inner_text())[0]
            assert first["values"]["choices"] == expected
            assert ("choices" in first["dirty"]) is change_selection
            modal.get_by_label("name", exact=True).fill("Saved title")
            modal.get_by_role("button", name="Save", exact=True).click()
            expect(modal).not_to_be_visible()
            assert json.loads(page.locator("pre").inner_text())[-1]["values"]["choices"] == expected
        finally:
            browser.close()


_MONEY_APP = _APP.replace(
    '("name","text",None,[]),',
    '("planned_budget","money",None,[]),("actual_budget","money",None,[]),("name","text",None,[]),',
).replace(
    'values=dict(name="Draft",',
    'values=dict(planned_budget="9007199254740993.1234567890123456789",actual_budget="-0.000000000000000000123456789",name="Draft",',
)


@pytest.mark.parametrize("popup_server", [_MONEY_APP], indirect=True, ids=["exact-project-money"])
def test_project_money_remains_decimal_text_in_browser_events_and_validation_retries(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1200, "height": 1000})
            page.goto(popup_server)
            page.get_by_role("button", name="Open project").click()
            modal = page.get_by_role("dialog")
            planned, actual = modal.get_by_label("planned_budget"), modal.get_by_label("actual_budget")
            expect(planned).to_have_value("9007199254740993.1234567890123456789")
            expect(actual).to_have_value("-0.000000000000000000123456789")
            expect(planned).to_have_attribute("type", "text")
            expect(planned).to_have_attribute("inputmode", "decimal")
            values = {"planned_budget": "9007199254740999.987654321987654321", "actual_budget": "0.000000000000000001"}
            planned.fill(values["planned_budget"])
            actual.fill(values["actual_budget"])
            modal.get_by_label("name", exact=True).fill("")
            modal.get_by_role("button", name="Save", exact=True).click()
            expect(modal.get_by_role("alert")).to_have_text("Name is required")
            for key, value in values.items():
                expect(modal.get_by_label(key)).to_have_value(value)
            event = json.loads(page.locator("pre").inner_text())[0]
            assert {key: event["values"][key] for key in values} == values
            assert event["values"]["amount"] == 100  # Generic numeric properties keep their existing type.
            modal.get_by_label("name", exact=True).fill("Precise save")
            modal.get_by_role("button", name="Save", exact=True).click()
            expect(modal).not_to_be_visible()
            saved = json.loads(page.locator("pre").inner_text())[-1]
            assert {key: saved["values"][key] for key in values} == values
            expect(page.get_by_text("Shell runs: 1", exact=True)).to_be_visible()
        finally:
            browser.close()


@pytest.mark.parametrize("popup_server", [_APP], indirect=True, ids=["project-form"])
def test_project_fields_tabs_and_links_are_local_and_save_retries_without_page_refresh(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1200, "height": 800})
            page.add_init_script(_SAMPLE)
            page.goto(popup_server)
            page.get_by_role("button", name="Open project").click()
            modal = page.get_by_role("dialog")
            expect(modal.get_by_role("button", name="Save", exact=True)).to_be_visible()
            assert page.evaluate("window.openedForms") == [{"fields": 8, "buttons": 11, "title": "Project form"}]
            assert modal.bounding_box()["height"] <= 800 * .9 + 2
            modal.get_by_label("name", exact=True).fill("")
            modal.get_by_label("amount").fill("123.45")
            modal.get_by_label("due").fill("2028-05-19")
            tags = modal.locator('.tag-dropdown')
            expect(tags.locator('summary')).to_have_text('Initial')
            expect(tags.get_by_role('checkbox', name='One', exact=True)).not_to_be_visible()
            tags.locator('summary').click()
            tags.get_by_role('checkbox', name='Initial', exact=True).uncheck()
            tags.get_by_role('checkbox', name='One', exact=True).check()
            tags.get_by_role('checkbox', name='Two', exact=True).check()
            expect(tags.locator('summary')).to_have_text('One, Two')
            page.screenshot(path='.local/project-tag-dropdown.png')
            page.keyboard.press('Escape')
            expect(modal).to_be_visible()
            expect(tags.get_by_role('checkbox', name='One', exact=True)).not_to_be_visible()
            modal.get_by_role("tab", name="More").click()
            modal.get_by_label("choices").select_option(["one", "two"])
            expect(modal.get_by_role("button", name="Add link")).not_to_be_visible()
            modal.get_by_role("tab", name="Useful links").click()
            modal.get_by_role("button", name="Add link").click()
            modal.get_by_label("Display alias").fill("Documentation")
            modal.get_by_label("URL", exact=True).fill("https://example.com")
            expect(page.locator("pre")).to_have_text("[]")
            modal.get_by_role("button", name="Save", exact=True).click()
            expect(modal.get_by_role("alert")).to_have_text("Name is required")
            expect(modal.get_by_label("amount")).to_have_value("123.45")
            expect(modal.get_by_role("tab", name="Useful links")).to_have_attribute("aria-selected", "true")
            assert len(page.evaluate("window.openedForms")) == 1
            events = json.loads(page.locator("pre").inner_text())
            assert len(events) == 1
            assert events[0]["values"] == dict(name="", amount=123.45, due="2028-05-19", tags=["One", "Two"], choices=["one", "two"])
            assert events[0]["links"] == [{"alias": "Documentation", "url": "https://example.com"}]
            modal.get_by_label("name", exact=True).fill("Saved")
            modal.get_by_role("button", name="Save", exact=True).click()
            expect(modal).not_to_be_visible()
            expect(page.get_by_text("Shell runs: 1", exact=True)).to_be_visible()
            assert len(json.loads(page.locator("pre").inner_text())) == 2
        finally:
            browser.close()


@pytest.mark.parametrize("popup_server", [_APP], indirect=True, ids=["project-form"])
@pytest.mark.parametrize("dismiss", ["Cancel", "Escape", "delete"])
def test_project_cancel_reopen_and_delete_confirmation_are_local(popup_server, dismiss):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(popup_server)
            for count in range(1, 3):
                page.get_by_role("button", name="Open project").click()
                modal = page.get_by_role("dialog")
                expect(modal).to_be_visible()
                if dismiss == "Escape":
                    page.keyboard.press("Escape")
                elif dismiss == "delete":
                    modal.get_by_role("button", name="Delete project", exact=True).click()
                    modal.get_by_role("button", name="Cancel deletion").click()
                    modal.get_by_role("button", name="Delete project", exact=True).click()
                    modal.get_by_role("button", name="Confirm delete project").click()
                else:
                    modal.get_by_role("button", name=dismiss, exact=True).click()
                expect(modal).not_to_be_visible()
                expect(page.locator("pre")).to_contain_text('"kind": "delete"' if dismiss == "delete" else '"kind": "cancel"')
                page.wait_for_function("count => {const text=document.querySelector('pre')?.textContent; return text && JSON.parse(text).length===count;}", arg=count)
            expect(page.get_by_text("Shell runs: 1", exact=True)).to_be_visible()
        finally:
            browser.close()


@pytest.mark.parametrize("popup_server", [_APP], indirect=True, ids=["project-form"])
def test_wbs_rows_default_to_100_show_remaining_and_survive_tabs_and_validation(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1100, "height": 800})
            page.goto(popup_server)
            page.get_by_role("button", name="Open project").click()
            modal = page.get_by_role("dialog")
            modal.get_by_role("tab", name="WBS", exact=True).click()
            expect(modal.get_by_role("button", name="Add link")).not_to_be_visible()
            modal.get_by_role("button", name="Add WBS").click()
            expect(modal.get_by_label("Allocation (%)", exact=True)).to_have_value("100")
            modal.get_by_label("WBS code", exact=True).select_option("2")
            expect(modal.get_by_label("WBS code", exact=True).locator('option[value="3"]')).to_have_count(0)
            expect(modal.get_by_text("Available: 40%", exact=True)).to_be_visible()
            expect(modal.get_by_label("WBS code", exact=True).locator("option:checked")).to_have_text("#SHARED — Shared capacity")
            modal.get_by_label("Allocation (%)", exact=True).fill("35")
            modal.get_by_role("tab", name="General", exact=True).click()
            expect(modal.get_by_label("WBS code", exact=True)).not_to_be_visible()
            modal.get_by_role("tab", name="WBS", exact=True).click()
            expect(modal.get_by_label("Allocation (%)", exact=True)).to_have_value("35")
            modal.get_by_label("name", exact=True).fill("")
            modal.get_by_role("button", name="Save", exact=True).click()
            expect(modal.get_by_role("alert")).to_have_text("Name is required")
            assert json.loads(page.locator("pre").inner_text())[0]["wbs"] == [{"wbs_id": 2, "percentage": 35}]
            expect(modal.get_by_label("Allocation (%)", exact=True)).to_have_value("35")
            modal.get_by_role("button", name="Add WBS").click()
            modal.get_by_label("WBS code", exact=True).nth(1).select_option("1")
            modal.get_by_role("button", name="Remove WBS").first.click()
            modal.get_by_label("name", exact=True).fill("Saved")
            modal.get_by_role("button", name="Save", exact=True).click()
            expect(modal).not_to_be_visible()
            events = json.loads(page.locator("pre").inner_text())
            assert events[-1]["wbs"] == [{"wbs_id": 1, "percentage": 100}]
            expect(page.get_by_text("Shell runs: 1", exact=True)).to_be_visible()
        finally:
            browser.close()
