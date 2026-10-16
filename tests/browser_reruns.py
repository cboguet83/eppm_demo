"""Wait for native Streamlit browser actions to complete their server rerun."""

from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Page, expect


@contextmanager
def completed_rerun(page: Page) -> Iterator[None]:
    """Observe the requested run starting and finishing around a browser action.

    Args:
        page: Browser page whose next action requests a Streamlit rerun.

    Raises:
        TimeoutError: The action does not complete a native rerun in 30 seconds.

    Yields:
        Control to the caller to perform the action under observation.
    """
    expect(page.get_by_test_id('stApp')).to_have_attribute(
        'data-test-script-state', 'notRunning',
    )
    page.evaluate('''() => {
        const app = document.querySelector('[data-testid="stApp"]');
        const state = {started: false, finished: false};
        state.observer = new MutationObserver(records => {
            state.started ||= records.some(record => record.oldValue === 'notRunning');
            state.finished = state.started
                && app.getAttribute('data-test-script-state') === 'notRunning';
        });
        state.observer.observe(app, {
            attributes: true, attributeOldValue: true,
            attributeFilter: ['data-test-script-state'],
        });
        window.eppmTestRerun = state;
    }''')
    try:
        yield
        page.wait_for_function('window.eppmTestRerun.finished', timeout=30000)
    finally:
        page.evaluate('''() => {
            window.eppmTestRerun.observer.disconnect();
            delete window.eppmTestRerun;
        }''')
