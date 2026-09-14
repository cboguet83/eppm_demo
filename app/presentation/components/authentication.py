"""Browser session controls and public account-state views."""

import html
from urllib.parse import urlencode

import streamlit as st

from app.application.services.access import AccessService
from app.domain.access.models import AccessDenied, Actor
from app.presentation.i18n import t
from app.presentation.shell import render_language_selector


_SESSION_JS = """
export default function({data, parentElement}) {
    // Streamlit can render the same mounted component many times before unmounting.
    const existing = parentElement.eppmSessionControls;
    if (existing) { existing.update(data); return existing.dispose; }
    let root = parentElement.querySelector('.session-controls'), currentData = data;
    const logout = document.createElement('button');
    logout.textContent = data.logout;
    root.replaceChildren(logout);
    let lastActivity = 0, disposed = false, activityPending = false, pollPending = false;
    let unsentActivity = false, activityTimer = null;
    const activityEvents = ["pointerdown", "pointermove", "keydown", "wheel", "touchstart", "touchmove"];
    const documents = new Set(), frames = new Set();
    const expire = () => { if (!disposed) window.location.replace('/'); };
    const retry = () => { lastActivity = 0; root.dataset.sessionConnection = 'retrying'; };
    const accepted = response => {
        if (disposed) return false;
        if (response.ok) { delete root.dataset.sessionConnection; return true; }
        if (response.status === 401 || response.status === 403) expire();
        else retry();
        return false;
    };
    const scheduleActivity = delay => {
        if (disposed || activityTimer !== null) return;
        activityTimer = setTimeout(() => { activityTimer = null; flushActivity(); }, delay);
    };
    const flushActivity = async () => {
        if (disposed || activityPending || !unsentActivity) return;
        const delay = 10000 - (Date.now() - lastActivity);
        if (delay > 0) { scheduleActivity(delay); return; }
        if (activityTimer !== null) { clearTimeout(activityTimer); activityTimer = null; }
        unsentActivity = false; lastActivity = Date.now(); activityPending = true;
        try {
            const response = await fetch('/auth/activity', {method:'POST', credentials:'same-origin',
                headers:{'X-Eppm-Activity':'user-interaction'}, cache:'no-store'});
            if (!accepted(response) && response.status !== 401 && response.status !== 403) unsentActivity = true;
        } catch { if (!disposed) { retry(); unsentActivity = true; } }
        finally {
            activityPending = false;
            if (unsentActivity) scheduleActivity(10000);
        }
    };
    const activity = event => {
        if (disposed || !event.isTrusted) return;
        unsentActivity = true;
        return flushActivity();
    };
    const attachDocument = doc => {
        if (!doc || documents.has(doc)) return;
        documents.add(doc);
        for (const type of activityEvents) doc.addEventListener(type, activity, {capture:true, passive:true});
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
        if (disposed || pollPending) return;
        pollPending = true;
        try {
            const response = await fetch('/auth/session', {credentials:'same-origin', cache:'no-store'});
            if (!accepted(response)) return;
            const session = await response.json();
            if (session.status !== currentData.status) expire();
        } catch { if (!disposed) retry(); }
        finally { pollPending = false; }
    }, 15000);
    const dispose = () => {
        if (disposed) return;
        disposed = true; clearInterval(poll); clearTimeout(activityTimer); observer.disconnect();
        delete parentElement.eppmSessionControls;
        window.removeEventListener('storage', otherTabLogout);
        for (const doc of documents) {
            for (const type of activityEvents) doc.removeEventListener(type, activity, true);
        }
        for (const frame of frames) frame.removeEventListener('load', onFrameLoad);
    };
    parentElement.eppmSessionControls = {dispose, update(next) {
        currentData = next;
        root = parentElement.querySelector('.session-controls');
        logout.textContent = next.logout;
        if (logout.parentElement !== root) root.replaceChildren(logout);
    }};
    return dispose;
}
"""


def account_gate(service: AccessService, cookie: str) -> Actor | None:
    """Render only public or own-account information until an active identity exists."""
    try:
        actor = service.actor(cookie)
        account = service.account(actor)
    except AccessDenied:
        render_language_selector()
        st.title(t("auth.title", default="Sign in to EPPM"))
        query = {key: st.query_params[key] for key in ('nav', 'project_id', 'task_id') if key in st.query_params}
        login_url = '/auth/login' + ('?' + urlencode(query) if query else '')
        st.html(
            '<a href="' + html.escape(login_url, quote=True) + '" target="_self" style="display:inline-block;'
            'background:#C41039;color:white;border-radius:6px;padding:8px 14px;'
            'font:inherit;text-decoration:none">'
            + html.escape(t("auth.sign_in", default="Sign in")) + '</a>'
        )
        return None
    with st.sidebar.container(key="account_footer", gap="xsmall"):
        st.caption(t("auth.signed_in", default="Signed in as") + " " + account["display_name"])
        st.caption(t("auth.reference", default="Application user reference: {user_id}", user_id=account["id"]))
        component = st.components.v2.component(
            "eppm_session_controls", html='<div class="session-controls"></div>', js=_SESSION_JS,
            css="button {background:#C41039;color:white;border:0;border-radius:6px;padding:4px 10px;font:inherit;font-size:12px;cursor:pointer}",
        )
        component(data={"logout": t("auth.sign_out", default="Sign out"), "status": account["status"]},
                  key="eppm_session_controls", height="content")
    if account["status"] != "active":
        render_language_selector()
        message = (t("auth.disabled", default="Your application account is disabled. Contact an access administrator.")
                   if account["status"] == "disabled" else
                   t("auth.pending", default="Your account is awaiting activation. Give your application user reference to an access administrator."))
        st.info(message)
        st.caption(t("auth.reference", default="Application user reference: {user_id}", user_id=account["id"]))
        return None
    return actor
