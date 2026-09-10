"""Frame-level checks against a real local Streamlit server, without business data."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest

_playwright = pytest.importorskip("playwright.sync_api")
expect, sync_playwright = _playwright.expect, _playwright.sync_playwright


_APP = '''
import time
import streamlit as st
from app.presentation.components.dialog import dialog, install_dialog_presentation

install_dialog_presentation()
st.write("Retained page")

@dialog("Complete popup")
def popup(mode):
    st.text_input("First field", key="first")
    time.sleep(.4)
    if mode == "stop":
        st.error("Access denied")
        st.stop()
    st.multiselect("Choices", ["One", "Two"], key="choices")
    time.sleep(.4)
    st.text_area("Last field", key="last")
    st.button("Save")

if st.button("Open"):
    popup("normal")
if st.button("Denied"):
    popup("stop")
'''

_SAMPLE = """
window.popupFrames = [];
function sample() {
    const dialog = document.querySelector('[data-testid="stDialog"] [role="dialog"]');
    if (dialog) {
        const style = getComputedStyle(dialog);
        if (style.visibility !== 'hidden' && style.display !== 'none') {
            window.popupFrames.push({
                fields: dialog.querySelectorAll('input, textarea').length,
                complete: Boolean(dialog.querySelector('textarea')),
                error: Boolean(dialog.querySelector('[data-testid="stAlert"]')),
                ready: dialog.hasAttribute('data-eppm-ready'),
            });
        }
    }
    requestAnimationFrame(sample);
}
requestAnimationFrame(sample);
"""


@pytest.fixture(scope="module")
def popup_server(tmp_path_factory, request):
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip("Install the optional Playwright Chromium browser")
    directory = tmp_path_factory.mktemp("dialog-browser")
    script = directory / "popup_app.py"
    script.write_text(getattr(request, "param", _APP), encoding="utf-8")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    with (directory / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([
            sys.executable, "-m", "streamlit", "run", str(script),
            "--server.address=127.0.0.1", f"--server.port={port}",
            "--server.headless=true", "--browser.gatherUsageStats=false",
            "--server.fileWatcherType=none",
        ], env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            origin = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 30
            while True:
                try:
                    with urlopen(origin + "/_stcore/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError):
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("The isolated popup server failed to start") from None
                    time.sleep(.1)
            yield origin
        finally:
            process.terminate()
            process.wait(timeout=10)


@pytest.mark.parametrize("dismiss", ["escape", "close", "backdrop"])
def test_first_visible_frame_is_complete_and_reopening_and_dismissal_work(popup_server, dismiss):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1300, "height": 1000})
            page.add_init_script(_SAMPLE)
            page.goto(popup_server)
            for _ in range(2):
                page.evaluate("window.popupFrames = []")
                page.get_by_role("button", name="Open", exact=True).click()
                modal = page.get_by_role("dialog")
                expect(modal.get_by_role("button", name="Save", exact=True)).to_be_visible()
                expect(modal).to_have_attribute("data-eppm-ready", "true")
                frames = page.evaluate("window.popupFrames")
                assert frames and all(frame["complete"] for frame in frames), frames
                assert all(frame["fields"] == 3 for frame in frames), frames
                modal.get_by_role("textbox", name="First field").fill("Retained draft")
                modal.get_by_role("textbox", name="Last field").click()
                expect(modal.get_by_role("textbox", name="First field")).to_have_value("Retained draft")
                if dismiss == "escape":
                    page.keyboard.press("Escape")
                elif dismiss == "close":
                    modal.get_by_role("button", name="Close", exact=True).click()
                else:
                    page.mouse.click(5, 5)
                expect(modal).to_have_count(0)
        finally:
            browser.close()


def test_stopped_permission_error_is_visible_without_showing_partial_content(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.add_init_script(_SAMPLE)
            page.goto(popup_server)
            page.get_by_role("button", name="Denied", exact=True).click()
            expect(page.get_by_role("dialog").get_by_text("Access denied")).to_be_visible()
            frames = page.evaluate("window.popupFrames")
            assert frames and all(frame["error"] for frame in frames), frames
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog")).to_have_count(0)
        finally:
            browser.close()
