"""Mounted resource headers are independent from vertical body scrolling."""

from tests.test_eppm_planning_browser import (
    api, eppm_component, eppm_component_origin, expect,
)  # noqa: F401 - register shared browser fixtures


def test_resource_headers_have_a_separate_fixed_row(eppm_component: api.Page) -> None:
    """Headers are siblings of both bodies and retain their vertical position."""
    page = eppm_component
    for part in ('resource-left-header', 'resource-header'):
        header = page.locator('[data-part=' + part + ']')
        assert header.evaluate("node=>node.parentElement.dataset.part") == 'resource-panel'
        assert header.evaluate("node=>!node.closest('[data-part=resource-body],[data-part=resource-left]')")
    for part in ('resource-left', 'resource-body'):
        body = page.locator('[data-part=' + part + ']')
        assert body.evaluate("node=>node.parentElement.dataset.part") == 'resource-panel'
        assert body.evaluate("node=>!node.closest('[data-part=resource-header],[data-part=resource-left-header]')")
    before = page.locator('[data-part=resource-header]').bounding_box()['y']
    page.locator('[data-part=resource-body]').evaluate('node=>node.scrollTop=750')
    assert page.locator('[data-part=resource-header]').bounding_box()['y'] == before
