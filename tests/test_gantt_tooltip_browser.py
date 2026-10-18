"""Mounted hover delay, cancellation and native-title restoration."""

from tests.test_eppm_planning_browser import (
    api, eppm_component, eppm_component_origin, expect,
)  # noqa: F401 - register shared browser fixtures


def test_gantt_hover_delay_and_native_title_restoration(eppm_component: api.Page) -> None:
    """Retain the one-second reveal and cancellation assertions through real DOM."""
    page = eppm_component
    bar = page.locator('.planning-bar[data-target-kind=tasks]')
    bar.hover()
    expect(bar).not_to_have_attribute('title')
    tooltip = page.get_by_role('tooltip')
    page.wait_for_timeout(600)
    expect(tooltip).to_be_hidden()
    expect(tooltip).to_be_visible(timeout=1000)
    expect(tooltip).to_contain_text('Build')
    page.mouse.move(1450, 1150)
    expect(tooltip).to_be_hidden()
    bar.hover()
    page.wait_for_timeout(200)
    page.mouse.move(1450, 1150)
    page.wait_for_timeout(1100)
    expect(tooltip).to_be_hidden()
    page.locator('[data-control=hover]').uncheck()
    expect(bar).to_have_attribute('title', 'Build · 2027-01-01 → 2027-01-05')
