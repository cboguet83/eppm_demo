"""Blank the main workspace immediately while a navigation rerun loads."""

import streamlit as st


_JS = """
export default function({parentElement}) {
    const doc = parentElement.ownerDocument;
    let loading = false, ran = false, frame = 0;
    const overlay = doc.createElement('div');
    overlay.id = 'eppm-page-transition';
    overlay.setAttribute('role', 'progressbar');
    overlay.setAttribute('aria-label', 'Loading');
    overlay.innerHTML = '<span></span>';
    doc.body.append(overlay);
    const finish = () => {
        const app = doc.querySelector('[data-testid="stApp"]');
        if (!loading) return;
        if (app?.getAttribute('data-test-script-state') === 'running') ran = true;
        if (!ran || app?.getAttribute('data-test-script-state') !== 'notRunning') return;
        if (doc.querySelector('[data-testid="stMain"] [data-testid="stSkeleton"]')) return;
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => requestAnimationFrame(() => {
            if (app.getAttribute('data-test-script-state') !== 'notRunning') return;
            loading = false;
            doc.body.classList.remove('eppm-page-loading');
        }));
    };
    const begin = event => {
        const label = event.target.closest?.('.st-key-app_sidebar_nav label');
        const input = label?.querySelector('input[type="radio"]')
            || event.target.closest?.('.st-key-app_sidebar_nav input[type="radio"]');
        if (!input || input.checked) return;
        const main = doc.querySelector('[data-testid="stMain"]');
        if (!main) return;
        const bounds = main.getBoundingClientRect();
        overlay.style.left = `${bounds.left}px`;
        overlay.style.top = `${bounds.top}px`;
        loading = true; ran = false;
        doc.body.classList.add('eppm-page-loading');
    };
    doc.addEventListener('click', begin, true);
    const keyboard = event => {
        if (event.key === ' ' || event.key.startsWith('Arrow')) begin(event);
    };
    doc.addEventListener('keydown', keyboard, true);
    const observer = new MutationObserver(finish);
    observer.observe(doc.body, {subtree:true, childList:true, attributes:true,
        attributeFilter:['data-test-script-state']});
    return () => {
        observer.disconnect(); cancelAnimationFrame(frame);
        doc.removeEventListener('click', begin, true);
        doc.removeEventListener('keydown', keyboard, true);
        doc.body.classList.remove('eppm-page-loading'); overlay.remove();
    };
}
"""


def install_page_transition() -> None:
    """Keep navigation responsive and reveal the destination after rendering."""
    st.html('''<style>
    #eppm-page-transition {display:none;position:fixed;right:0;bottom:0;z-index:990;
        background:var(--st-background-color,#fff);align-items:center;justify-content:center}
    body.eppm-page-loading #eppm-page-transition {display:flex}
    body.eppm-page-loading [data-testid="stMain"] {visibility:hidden}
    #eppm-page-transition span {width:42px;height:42px;border:4px solid #ddd;
        border-top-color:#C41039;border-radius:50%;animation:eppm-spin .8s linear infinite}
    @keyframes eppm-spin {to {transform:rotate(360deg)}}
    </style>''')
    component = st.components.v2.component(
        'eppm_page_transition', html='<span></span>', js=_JS,
    )
    component(key='eppm_page_transition', height=0)
