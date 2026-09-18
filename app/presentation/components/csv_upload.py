"""Bounded CSV selection over the authenticated component WebSocket."""

import streamlit as st

MAX_CSV_BYTES = 2 * 1024 * 1024

_UPLOAD_JS = """
export default function({data, parentElement, setStateValue}) {
    const root = parentElement.querySelector('.csv-upload');
    const label = document.createElement('label');
    const input = document.createElement('input');
    const status = document.createElement('span');
    label.textContent = data.label;
    input.type = 'file'; input.accept = '.csv,text/csv';
    label.appendChild(input); root.replaceChildren(label, status);
    let disposed = false;
    input.onchange = async () => {
        const file = input.files[0];
        if (!file) { setStateValue('upload', null); return; }
        if (file.size > data.max_bytes) {
            setStateValue('upload', {error: 'size'}); return;
        }
        try {
            const buffer = await file.arrayBuffer();
            const content = new TextDecoder('utf-8', {fatal:true}).decode(buffer);
            if (!disposed) setStateValue('upload', {content, name: file.name});
        } catch {
            if (!disposed) setStateValue('upload', {error: 'encoding'});
        }
    };
    return () => { disposed = true; input.onchange = null; };
}
"""


def validated_csv_upload(payload: object) -> tuple[str, str] | None:
    """Validate untrusted component data independently of the browser's file checks."""
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("Select a UTF-8 CSV file.")
    if payload.get("error") == "size":
        raise ValueError("The CSV file must be no larger than 2 MiB.")
    content, name = payload.get("content"), payload.get("name")
    if not isinstance(content, str) or not isinstance(name, str) or not name.lower().endswith(".csv"):
        raise ValueError("Select a UTF-8 CSV file.")
    if len(content) > MAX_CSV_BYTES:
        raise ValueError("The CSV file must be no larger than 2 MiB.")
    try:
        size = len(content.encode("utf-8"))
    except UnicodeError:
        raise ValueError("Select a valid UTF-8 CSV file.") from None
    if size > MAX_CSV_BYTES:
        raise ValueError("The CSV file must be no larger than 2 MiB.")
    if len(name) > 255 or "\x00" in content:
        raise ValueError("Select a valid UTF-8 CSV file.")
    return content.lstrip("\ufeff"), name


def reset_csv_upload(key: str) -> None:
    """Start a fresh upload when opening a dialog, not on its fragment reruns."""
    epoch_key = f'{key}_epoch'
    st.session_state[epoch_key] = st.session_state.get(epoch_key, 0) + 1


def project_csv_upload(label: str, *, key: str) -> str | None:
    """Select a file without creating an unauthenticated upload URL or server file."""
    component = st.components.v2.component(
        "eppm_csv_upload", html='<div class="csv-upload"></div>', js=_UPLOAD_JS,
        css="label {display:grid; gap:8px; font:inherit;} input {font:inherit;}",
    )
    result = component(data={"label": label, "max_bytes": MAX_CSV_BYTES},
                       key=f'{key}_{st.session_state.get(f"{key}_epoch", 0)}',
                       height="content", on_upload_change=lambda: None)
    upload = validated_csv_upload(getattr(result, "upload", None))
    if upload is None:
        return None
    content, filename = upload
    st.text(filename)
    return content
