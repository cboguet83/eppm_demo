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
    st.session_state.form = dict(token="draft", title="Project form", tabs=["General", "More"],
        fields=[dict(key=k,label=k,kind=kind,tab=tab,options=options,disabled=False)
                for k,kind,tab,options in [
                    ("name","text",None,[]), ("amount","number",None,[]),
                    ("due","date","General",[]), ("tags","tags","General",[]),
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
        st.session_state.form.update(values=event["values"],links=event["links"],error="Name is required")
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
            assert page.evaluate("window.openedForms") == [{"fields": 5, "buttons": 8, "title": "Project form"}]
            assert modal.bounding_box()["height"] <= 800 * .9 + 2
            modal.get_by_label("name", exact=True).fill("")
            modal.get_by_label("amount").fill("123.45")
            modal.get_by_label("due").fill("2028-05-19")
            modal.get_by_label("tags").fill("One\nTwo")
            modal.get_by_role("tab", name="More").click()
            modal.get_by_label("choices").select_option(["one", "two"])
            modal.get_by_role("button", name="Add link").click()
            modal.get_by_label("Display alias").fill("Documentation")
            modal.get_by_label("URL", exact=True).fill("https://example.com")
            expect(page.locator("pre")).to_have_text("[]")
            modal.get_by_role("button", name="Save", exact=True).click()
            expect(modal.get_by_role("alert")).to_have_text("Name is required")
            expect(modal.get_by_label("amount")).to_have_value("123.45")
            expect(modal.get_by_role("tab", name="More")).to_have_attribute("aria-selected", "true")
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
