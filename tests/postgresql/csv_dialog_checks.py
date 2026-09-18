"""Browser assertions for independent CSV import dialog sessions."""

from playwright.sync_api import Page, expect


def check_fresh_import_dialog(page: Page, filename: str, submit_label: str, content: bytes) -> None:
    """Check reset after success and dismissal, preserving uploads within a session."""
    page.get_by_role('button', name='Import CSV').click()
    dialog = page.get_by_role('dialog')
    expect(dialog.locator('input[type="file"]')).to_have_value('')
    expect(dialog.get_by_text(filename, exact=True)).to_have_count(0)
    expect(dialog.get_by_role('button', name=submit_label, exact=True)).to_have_count(0)
    dialog.locator('input[type="file"]').set_input_files({
        'name': filename, 'mimeType': 'text/csv', 'buffer': content,
    })
    expect(dialog.get_by_text(filename, exact=True)).to_be_visible()
    checkbox = dialog.get_by_role('checkbox')
    dialog.get_by_text(checkbox.get_attribute('aria-label'), exact=True).click()
    expect(checkbox).to_be_checked()
    expect(dialog.get_by_text(filename, exact=True)).to_be_visible()
    expect(dialog.get_by_role('button', name=submit_label, exact=True)).to_be_visible()
    page.keyboard.press('Escape')
    expect(dialog).not_to_be_visible()
    page.get_by_role('button', name='Import CSV').click()
    expect(dialog.locator('input[type="file"]')).to_have_value('')
    expect(dialog.get_by_text(filename, exact=True)).to_have_count(0)
    expect(dialog.get_by_role('button', name=submit_label, exact=True)).to_have_count(0)
    page.keyboard.press('Escape')
    expect(dialog).not_to_be_visible()
