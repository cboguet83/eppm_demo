"""Atomic calendar boundary regression for the supported year range."""

from tests.test_planning_component_browser import (
    Page,
    expect,
    planning_module_origin,
    planning_page,
)


def test_year_zero_rejects_before_changing_valid_mounted_state(
    planning_page: Page,
) -> None:
    """An unsupported year fails synchronously and preserves the prior display."""
    page = planning_page
    assert page.evaluate("""() => {
      try {
        instances[0].update({...snapshot,labels:{projectTask:'Invalid'},
          tasks:[{...snapshot.tasks[0],start:'0000-01-01',end:'0000-01-02'}]});
        return false;
      } catch(error) {return error.name==='ContractError';}
    }""")
    expect(page.locator("#first [data-sort=name]")).to_have_text("Project / task")
