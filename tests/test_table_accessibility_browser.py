"""Table headers and search/filter names remain accessible after translation."""

from pathlib import Path
import re

import pytest

api = pytest.importorskip('playwright.sync_api')
COMPONENTS = Path(__file__).resolve().parents[1] / 'app/presentation/assets/components'


@pytest.mark.parametrize('component', [
    'employee_table', 'function_table', 'function_type_table', 'team_table',
    'project_tag_table', 'task_tag_table', 'tag_dictionary_table', 'tag_group_table',
])
def test_table_filters_have_accessible_names_and_scoped_headers(component):
    with api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.set_content((COMPONENTS / component / 'index.html').read_text(encoding='utf-8'))
            page.evaluate('''() => window.dispatchEvent(new MessageEvent('message', {data:{
                type:'streamlit:render', args:{show_parent:true, translations:{
                    search_placeholder:'Rechercher dans le tableau', col_parent:'Parent traduit',
                    col_free_tag:'Texte libre', col_level:'Niveau', col_mobile:'Portable',
                    col_group_name:'Groupe traduit', search_values:'Rechercher des valeurs'
                }}
            }}))''')
            search = page.get_by_role('textbox', name='Rechercher dans le tableau', exact=True)
            api.expect(search).to_have_id('search-box')
            search.fill('example')
            api.expect(search).to_have_value('example')
            for header in page.locator('th').all():
                api.expect(header).to_have_attribute('scope', 'col')
            for control in page.locator('input[aria-labelledby], select[aria-labelledby]').all():
                header_id = control.get_attribute('aria-labelledby')
                header = page.locator(f'#{header_id}')
                api.expect(header).to_have_count(1)
                name = header.evaluate("node => [...node.childNodes].filter(child => child.nodeType === 3 || !child.hasAttribute('aria-hidden')).map(child => child.textContent).join(' ').replace(/\\s+/g, ' ').trim()")
                assert name
                api.expect(control).to_have_accessible_name(name)
            if page.locator('#excel-popup-search').count():
                page.locator('.excel-trigger').first.click()
                api.expect(page.get_by_role('textbox', name='Rechercher des valeurs', exact=True)).to_have_id('excel-popup-search')
            for control in page.locator('input:not([type="checkbox"]):visible, select:visible').all():
                api.expect(control).to_have_accessible_name(re.compile(r'\S'))
            assert not errors, errors
        finally:
            browser.close()
