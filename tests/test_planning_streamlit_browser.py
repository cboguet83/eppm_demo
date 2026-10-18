"""Run the standalone Python/browser adapter in an isolated native Streamlit app."""

from collections.abc import Iterator
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
expect = playwright_api.expect

_APP = '''
"""Fixture host using only Streamlit and the independent planning package."""
import sys
import streamlit as st
from streamlit_planning_view import planning_view

st.set_page_config(layout="wide")

def initial(scope: str) -> dict[str, object]:
    """Provide independent fixture data with overlapping task IDs."""
    return {"version":1,"kind":"snapshot","scope":scope,"revision":"r1",
        "projects":[{"id":"p","name":"Project"}],"capabilities":{"edit":True},
        "tasks":[{"id":"same-task","projectId":"p","name":"Task",
            "start":"2026-01-01","end":"2026-01-05","progress":0},
            {"id":"long","projectId":"p","name":"Long",
            "start":"2026-02-01","end":"2026-12-31"}],
        "resources":[{"id":"pool","name":"Pool","capacity":5,
            "usage":{"2026-01-01":2}}]}

for key in ("first", "second", "lazy"):
    if key+"-snapshot" not in st.session_state:
        data=initial(key)
        if key=="lazy":
            data["tasks"]=[]
            data["loadedProjectIds"]=[]
            data["projects"]=[{"id":"p"+str(i),"name":"Project "+str(i),
                "start":"2026-01-01","end":"2026-12-31","taskCount":1}
                for i in range(3)]
        st.session_state[key+"-snapshot"]=data
        st.session_state[key+"-updates"]=[]
        st.session_state[key+"-count"]=0
    st.subheader(key)
    data=st.session_state[key+"-snapshot"]
    event=planning_view(data,key=key,lazy=key=="lazy",
        updates=st.session_state[key+"-updates"],
        options={"mode":"Day","grouped":False,"editEnabled":True})
    if event:
        st.session_state[key+"-count"]+=1
        updates=[]
        if event["type"]=="load":
            tasks=[{"id":"task-"+pid,"projectId":pid,"name":"Loaded "+pid,
                "start":"2026-01-01","end":"2026-01-05"}
                for pid in event["projectIds"]]
            updates=[{"version":1,"kind":"patch","scope":key,
                "revision":"r1","requestId":event["requestId"],
                "replaceProjectIds":event["projectIds"],"tasks":tasks}]
        elif event["type"] in ("task","dates","progress"):
            values=event.get("values",event)
            accepted=values.get("name")!="Reject"
            if accepted:
                data["tasks"]=[{**row,**{field:values[field] for field in
                    ("name","start","end","progress","description","phase")
                    if field in values}} if row["id"]==event["targetId"]
                    else row for row in data["tasks"]]
            updates=[{"version":1,"kind":"response","scope":key,
                "revision":"r1","requestId":event["requestId"],
                "accepted":accepted,"error":"Host rejected the name"}]
        st.session_state[key+"-updates"]=updates
        st.rerun()
    st.caption(key+" events: "+str(st.session_state[key+"-count"]))

if any(name=="app" or name.startswith("app.") for name in sys.modules):
    raise RuntimeError("Fixture imported an EPPM module")
'''


@pytest.fixture(scope="module")
def standalone_streamlit_origin(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[str]:
    """Prepare a development frontend and serve a source-independent test host."""
    root = Path(__file__).resolve().parents[1]
    directory = tmp_path_factory.mktemp("planning-streamlit")
    package = directory / "streamlit_planning_view"
    shutil.copytree(
        root / "packages/streamlit-planning-view/src/streamlit_planning_view",
        package, ignore=shutil.ignore_patterns("__pycache__", "frontend"),
    )
    frontend = package / "frontend"
    shutil.copytree(root / "packages/planning-view/src", frontend / "src")
    shutil.copyfile(
        root / "packages/planning-view/streamlit.html", frontend / "index.html",
    )
    script = directory / "consumer.py"
    script.write_text(_APP, encoding="utf-8")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(directory)
    with (directory / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([
            sys.executable, "-m", "streamlit", "run", str(script),
            "--server.address=127.0.0.1", f"--server.port={port}",
            "--server.headless=true", "--browser.gatherUsageStats=false",
            "--server.fileWatcherType=none",
        ], cwd=directory, env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            origin = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 30
            while True:
                try:
                    with urlopen(origin + "/_stcore/health", timeout=1) as reply:
                        if reply.status == 200:
                            break
                except (URLError, TimeoutError):
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Standalone Streamlit host failed") from None
                    time.sleep(.1)
            yield origin
        finally:
            process.terminate()
            process.wait(timeout=10)


def test_native_wrapper_reruns_keys_lazy_reads_and_safe_edit_responses(
    standalone_streamlit_origin: str,
) -> None:
    """Real component reruns retain separate view state and deliver intentions once."""
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("EPPM_BENCHMARK_BROWSER"),
        )
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 2200})
            page.goto(standalone_streamlit_origin)
            frames = page.frame_locator(
                'iframe[title="streamlit_planning_view.planning_view"]',
            )
            first = frames.nth(0)
            second = frames.nth(1)
            lazy = frames.nth(2)
            expect(first.locator('.planning-bar[data-target-id="same-task"]')).to_be_visible(timeout=20000)
            expect(lazy.locator('.planning-bar[data-target-id="task-p0"]')).to_be_attached(timeout=20000)
            expect(page.get_by_text("lazy events: 1", exact=True)).to_be_visible()
            second.locator('[data-mode="Month"]').click()
            first.locator('.planning-bar[data-target-id="same-task"]').press("Enter")
            editor = first.locator(".planning-editor")
            editor.locator('[data-field="name"]').fill("Reject")
            editor.get_by_role("button", name="Save", exact=True).click()
            expect(editor.get_by_role("alert")).to_have_text("Host rejected the name", timeout=10000)
            expect(editor.locator('[data-field="name"]')).to_have_value("Reject")
            editor.locator('[data-field="name"]').fill("Accepted")
            editor.get_by_role("button", name="Save", exact=True).click()
            expect(editor).to_be_hidden(timeout=10000)
            expect(first.locator('.planning-bar[data-target-id="same-task"]')).to_have_attribute("aria-label", "Accepted · 2026-01-01 → 2026-01-05")
            expect(page.get_by_text("first events: 2", exact=True)).to_be_visible()
            expect(second.locator('[data-mode="Month"]')).to_have_attribute("aria-pressed", "true")
            expect(second.locator('.planning-bar[data-target-id="same-task"]')).to_have_attribute("aria-label", "Task · 2026-01-01 → 2026-01-05")
            expect(page.get_by_text("second events: 0", exact=True)).to_be_visible()
            for frame in (first, second, lazy):
                assert frame.locator(".planning-view").evaluate("n=>Math.ceil(n.getBoundingClientRect().height)<=innerHeight+1")
            assert page.locator('[data-testid="stException"]').count() == 0
        finally:
            browser.close()
