"""Exercise modal component callbacks using Streamlit's persistent fragment runner."""

from streamlit.testing.v1 import AppTest


def modal_state(app: AppTest, surface: str = "contacts") -> dict:
    """Read prepared display state for the isolated test project's modal."""
    return app.session_state[f"project_{surface}_1_modal_state"]


def submit_modal(app: AppTest, surface: str = "contacts", values: dict | None = None, *, cancel: bool = False):
    """Submit a real component event and assert that no application shell is redrawn."""
    from tests.test_fragment_reruns import FragmentRun

    def prepare():
        submitted = dict(modal_state(app, surface)["form"]["values"])
        submitted.update(values or {})
        rerun.widget_json = {"action": {"kind": "cancel" if cancel else "save", "values": submitted}}

    rerun = FragmentRun(f"project_{surface}_1_modal", prepare)
    rerun.run(app)
    rerun.assert_isolated()
    return rerun
