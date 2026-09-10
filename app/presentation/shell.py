"""Streamlit application shell with injected services and page renderers."""

import streamlit as st

from app.presentation.components.application_workspace import ApplicationWorkspace
from app.presentation.components.dialog import install_dialog_presentation
from app.presentation.i18n import SUPPORTED_LOCALES, get_current_locale, set_current_locale, t
from app.presentation.navigation import (
    PAGE_PORTFOLIO,
    PAGE_PLANNING,
    PAGE_SETTINGS,
    PAGE_SCHEMA_DEF,
    PAGE_ACCESS,
)


def render_application(workspace: ApplicationWorkspace) -> None:
    """Main routing and execution entrypoint for Streamlit UI."""
    st.set_page_config(
        page_title=t("app.title", default="PPM Studio Pro"),
        page_icon="🏗️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Clean Streamlit UI elements without breaking sidebar controls
    st.markdown(
        """
        <style>
        button[data-testid^="stBaseButton-primary"],
        button[data-testid^="stBaseButton-secondary"],
        [data-testid="stDownloadButton"] button,
        [data-testid="stFormSubmitButton"] button,
        [data-testid="stPopoverButton"] {
            background-color: #C41039 !important;
            border-color: #C41039 !important;
            color: white !important;
        }
        button:disabled { opacity: .5; }
        .stDeployButton, [data-testid="stDeployButton"], .stAppDeployButton, [data-testid="stDecoration"] {
            display: none !important;
            visibility: hidden !important;
        }
        #MainMenu { visibility: hidden; }
        footer { visibility: hidden; }

        /* Reduce top whitespace across all views */
        .block-container {
            padding-top: 1.5rem !important;
        }

        /* Ensure native Streamlit sidebar collapse/expand controls are always accessible */
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="collapsedControl"],
        [data-testid="stSidebarCollapseButton"] {
            visibility: visible !important;
            display: flex !important;
            opacity: 1 !important;
            z-index: 1000 !important;
            pointer-events: auto !important;
        }

        /* Multiselect selected tag pills styled with #C41039 */
        div[data-baseweb="tag"],
        span[data-baseweb="tag"],
        [data-testid="stMultiSelect"] div[data-baseweb="tag"],
        [data-testid="stMultiSelect"] span[data-baseweb="tag"],
        [data-testid="stMultiSelectTag"],
        [data-baseweb="tag"] {
            background-color: #FDE8EC !important;
            background: #FDE8EC !important;
            border: 1px solid #C41039 !important;
            border-radius: 6px !important;
        }
        div[data-baseweb="tag"] *,
        span[data-baseweb="tag"] *,
        [data-testid="stMultiSelect"] div[data-baseweb="tag"] *,
        [data-testid="stMultiSelect"] span[data-baseweb="tag"] *,
        [data-testid="stMultiSelectTag"] * {
            color: #C41039 !important;
            fill: #C41039 !important;
        }
        div[data-baseweb="tag"] span,
        span[data-baseweb="tag"] span,
        [data-testid="stMultiSelect"] [data-baseweb="tag"] span {
            color: #C41039 !important;
            font-weight: 600 !important;
        }
        div[data-baseweb="tag"] svg,
        span[data-baseweb="tag"] svg,
        [data-baseweb="tag"] svg path {
            fill: #C41039 !important;
            color: #C41039 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    install_dialog_presentation()
    render_language_selector()

    st.sidebar.title(f"📌 {t('app.title', default='PPM Demo Portal')}")

    nav_map = {
        PAGE_PORTFOLIO: f"1. 📊 {t('nav.portfolio')}",
        PAGE_PLANNING: f"2. 📅 {t('nav.planning')}",
        PAGE_SETTINGS: f"3. ⚙️ {t('nav.settings', default='Settings')}",
    }

    nav_map[PAGE_ACCESS] = t("access.title", default="Application access")
    page_keys = [page for page in (PAGE_PORTFOLIO, PAGE_PLANNING, PAGE_SETTINGS, PAGE_ACCESS) if page in workspace.pages]
    if not page_keys:
        st.info(t("auth.no_access", default="Your account has no assigned application access. Contact an access administrator."))
        return

    # Deep-link routing via URL query parameters (e.g. ?nav=planning&project_id=123)
    if "nav" in st.query_params:
        target_nav = st.query_params.get("nav")
        target_proj_id = st.query_params.get("project_id")
        target_task_id = st.query_params.get("task_id")

        if target_nav in ("planning", PAGE_PLANNING):
            st.session_state["app_sidebar_nav"] = PAGE_PLANNING
            project_id = _positive_identifier(target_proj_id)
            task_id = _positive_identifier(target_task_id)
            if project_id is not None:
                st.session_state["target_planning_project_id"] = project_id
                st.session_state["ms_multi_projects"] = [project_id]
            if task_id is not None:
                st.session_state["target_planning_task_id"] = task_id
        elif target_nav in ("schema", PAGE_SCHEMA_DEF):
            st.session_state["app_sidebar_nav"] = PAGE_SETTINGS
            st.session_state["settings_active_section"] = "parameters"
            st.session_state["rb_settings_section"] = "param_def"
        elif target_nav in page_keys:
            st.session_state["app_sidebar_nav"] = target_nav

        st.query_params.clear()

    if "nav_redirect" in st.session_state and st.session_state["nav_redirect"]:
        st.session_state["app_sidebar_nav"] = st.session_state.pop("nav_redirect")
    if st.session_state.get("app_sidebar_nav") not in page_keys:
        st.session_state["app_sidebar_nav"] = page_keys[0]

    st.sidebar.radio(
        t("app.sidebar_nav", default="Navigation"),
        page_keys,
        format_func=lambda k: nav_map.get(k, k),
        key="app_sidebar_nav",
        on_change=lambda: st.rerun("application_page"),
    )

    if workspace.totals is not None:
        totals = workspace.totals()
        with st.sidebar:
            st.divider()
            st.caption(t("planning_totals.visible", default="Planning totals: accessible projects"))
            for first, second in (("projects", "tasks"), ("dependencies", "pools")):
                left, right = st.columns(2)
                left.caption(f"{t('planning_totals.' + first, default=first.title())}  \n{totals[first]:,}")
                right.caption(f"{t('planning_totals.' + second, default=second.title())}  \n{totals[second]:,}")

    _render_application_page(workspace)


@st.fragment(key="application_page")
def _render_application_page(workspace: ApplicationWorkspace) -> None:
    """Switch the main page while retaining navigation, account controls and totals."""
    render_page = workspace.pages.get(st.session_state.get("app_sidebar_nav"))
    if render_page is None:
        st.info(t("auth.no_access", default="Your account has no assigned application access. Contact an access administrator."))
        return
    render_page()


def render_language_selector() -> None:
    """Offer the same session-local language choice on public and protected screens."""
    current = get_current_locale()
    codes = list(SUPPORTED_LOCALES)

    def on_change() -> None:
        set_current_locale(st.session_state.get("app_language_selector", "en"))

    selected = st.sidebar.selectbox(
        t("app.language_selector", default="🌐 Language"), codes,
        format_func=SUPPORTED_LOCALES.get, index=codes.index(current),
        key="app_language_selector", on_change=on_change,
    )
    if selected != current:
        set_current_locale(selected)
        st.rerun()


def _positive_identifier(value: str | None) -> int | None:
    """Ignore malformed or nonpositive deep-link identifiers at the UI boundary."""
    try:
        identifier = int(value) if value is not None else 0
    except (ValueError, TypeError):
        return None
    return identifier if identifier > 0 else None
