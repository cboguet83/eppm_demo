"""Browser session controls and public account-state views."""

import streamlit as st

from app.application.services.access import AccessService
from app.domain.access.models import AccessDenied, Actor
from app.presentation.i18n import t


_SESSION_JS = """
export default function({data, parentElement}) {
    const root = parentElement.querySelector('.session-controls');
    const logout = document.createElement('button');
    logout.textContent = data.logout;
    root.replaceChildren(logout);
    let lastActivity = 0, disposed = false;
    const documents = new Set(), frames = new Set();
    const expire = () => { if (!disposed) window.location.replace('/'); };
    const activity = async event => {
        if (!event.isTrusted || Date.now() - lastActivity < 10000) return;
        lastActivity = Date.now();
        try {
            const response = await fetch('/auth/activity', {method:'POST', credentials:'same-origin',
                headers:{'X-Eppm-Activity':'user-interaction'}, cache:'no-store'});
            if (!response.ok) expire();
        } catch { expire(); }
    };
    const attachDocument = doc => {
        if (!doc || documents.has(doc)) return;
        documents.add(doc);
        doc.addEventListener('pointerdown', activity, true);
        doc.addEventListener('keydown', activity, true);
    };
    const attachFrame = frame => {
        try { attachDocument(frame.contentDocument); } catch { /* Cross-origin embedded content is isolated. */ }
    };
    const scanFrames = () => {
        for (const frame of document.querySelectorAll('iframe')) {
            if (frames.has(frame)) continue;
            frames.add(frame);
            frame.addEventListener('load', onFrameLoad);
            attachFrame(frame);
        }
    };
    const onFrameLoad = event => attachFrame(event.target);
    attachDocument(document); scanFrames();
    const observer = new MutationObserver(scanFrames);
    observer.observe(document.body, {childList:true, subtree:true});
    logout.onclick = async () => {
        logout.disabled = true;
        try {
            const response = await fetch('/auth/logout', {method:'POST', credentials:'same-origin'});
            if (response.ok) { localStorage.setItem('eppm-logout', String(Date.now())); expire(); }
            else { logout.disabled = false; }
        } catch { logout.disabled = false; }
    };
    const otherTabLogout = event => { if (event.key === 'eppm-logout') expire(); };
    window.addEventListener('storage', otherTabLogout);
    const poll = setInterval(async () => {
        try {
            const response = await fetch('/auth/session', {credentials:'same-origin', cache:'no-store'});
            if (!response.ok) { expire(); return; }
            const session = await response.json();
            if (session.status !== data.status) expire();
        } catch { expire(); }
    }, 15000);
    return () => {
        disposed = true; clearInterval(poll); observer.disconnect();
        window.removeEventListener('storage', otherTabLogout);
        for (const doc of documents) {
            doc.removeEventListener('pointerdown', activity, true);
            doc.removeEventListener('keydown', activity, true);
        }
        for (const frame of frames) frame.removeEventListener('load', onFrameLoad);
    };
}
"""


def account_gate(service: AccessService, cookie: str) -> Actor | None:
    """Render only public or own-account information until an active identity exists."""
    try:
        actor = service.actor(cookie)
        account = service.account(actor)
    except AccessDenied:
        st.title(t("auth.title", default="Sign in to EPPM"))
        st.link_button(t("auth.sign_in", default="Sign in"), "/auth/login", type="primary")
        return None
    with st.sidebar:
        st.caption(t("auth.signed_in", default="Signed in as"))
        st.text(account["display_name"])
        st.caption(t("auth.reference", default="Application user reference: {user_id}", user_id=account["id"]))
        component = st.components.v2.component(
            "eppm_session_controls", html='<div class="session-controls"></div>', js=_SESSION_JS,
            css="button {background:#C41039;color:white;border:0;border-radius:6px;padding:8px 14px;font:inherit;cursor:pointer}",
        )
        component(data={"logout": t("auth.sign_out", default="Sign out"), "status": account["status"]},
                  key="eppm_session_controls", height="content")
    if account["status"] != "active":
        message = (t("auth.disabled", default="Your application account is disabled. Contact an access administrator.")
                   if account["status"] == "disabled" else
                   t("auth.pending", default="Your account is awaiting activation. Give your application user reference to an access administrator."))
        st.info(message)
        st.caption(t("auth.reference", default="Application user reference: {user_id}", user_id=account["id"]))
        return None
    return actor
