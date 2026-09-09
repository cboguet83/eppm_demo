"""Start a CSV download in response to a Gantt export action."""

import streamlit as st

_DOWNLOAD_JS = """export default function(component) {
      const {data, parentElement} = component;
      const root = parentElement.querySelector('span');
      if (!data || !root || root.dataset.downloadNonce === data.nonce) return;
      root.dataset.downloadNonce = data.nonce;
      const url = URL.createObjectURL(new Blob(['\\ufeff', data.content], {type:'text/csv;charset=utf-8'}));
      const link = document.createElement('a');
      link.href = url; link.download = data.filename;
      root.appendChild(link); link.click(); link.remove();
      const timer = setTimeout(() => URL.revokeObjectURL(url), 1000);
      return () => {clearTimeout(timer); URL.revokeObjectURL(url);};
    }"""


def download_project_csv(content: str, project_id: int, nonce: str) -> None:
    """Download the selected project's editable template without opening a dialog."""
    component = st.components.v2.component("project_csv_download", html="<span></span>", js=_DOWNLOAD_JS)
    component(data={"content": content, "filename": f"project_{project_id}_template.csv", "nonce": nonce},
              key="project_csv_download", height=0)
