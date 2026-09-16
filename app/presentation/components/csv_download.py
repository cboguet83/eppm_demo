"""Start a CSV download in response to a Gantt export action."""

from urllib.parse import quote

import streamlit as st

_DOWNLOAD_JS = """export default function(component) {
      const {data, parentElement} = component;
      const root = parentElement.querySelector('span');
      if (!data || !root || root.dataset.downloadNonce === data.nonce) return;
      root.dataset.downloadNonce = data.nonce;
      const link = document.createElement('a');
      link.href = data.url; link.download = data.filename;
      root.appendChild(link); link.click(); link.remove();
    }"""


def download_project_csv(project_id: int, nonce: str, *, content: str | None = None) -> None:
    """Download a current schedule or an already-authorized scenario CSV."""
    component = st.components.v2.component("project_csv_download", html="<span></span>", js=_DOWNLOAD_JS)
    url = (f"data:text/csv;charset=utf-8,{quote(content)}" if content is not None
           else f"/downloads/projects/{int(project_id)}/template.csv")
    component(data={"url": url,
                    "filename": f"project_{int(project_id)}_template.csv", "nonce": nonce},
              key="project_csv_download", height=0)
