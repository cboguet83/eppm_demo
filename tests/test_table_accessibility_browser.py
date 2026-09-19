"""Table headers and search/filter names remain accessible after translation."""

from pathlib import Path
import re

import pytest

api = pytest.importorskip('playwright.sync_api')
COMPONENTS = Path(__file__).resolve().parents[1] / 'app/presentation/assets/components'


@pytest.mark.parametrize('component', [
    'employee_table', 'function_type_table', 'team_table',
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
                trigger = page.locator('.excel-trigger').first
                assert trigger.evaluate('node => node.tagName') == 'BUTTON'
                trigger.focus()
                page.keyboard.press('Enter')
                api.expect(page.get_by_role('textbox', name='Rechercher des valeurs', exact=True)).to_have_id('excel-popup-search')
            for control in page.locator('input:not([type="checkbox"]):visible, select:visible').all():
                api.expect(control).to_have_accessible_name(re.compile(r'\S'))
            page.evaluate('''() => {
                window.actions = [];
                Streamlit.setComponentValue = value => window.actions.push(value);
                document.getElementById('context-menu').style.display = 'block';
            }''')
            action = page.locator('#context-menu .context-menu-item').first
            assert page.locator('.context-menu-item, .excel-trigger').evaluate_all(
                "nodes => nodes.every(node => node.tagName === 'BUTTON')")
            action.focus()
            page.keyboard.press('Space')
            assert len(page.evaluate('window.actions')) == 1
            assert not errors, errors
        finally:
            browser.close()


def test_gantt_submenus_and_resource_toggle_work_with_keyboard():
    with api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 1400, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.set_content((COMPONENTS / 'gantt/index.html').read_text(encoding='utf-8'))
            page.evaluate('''() => {
                window.actions = [];
                Streamlit.setComponentValue = value => window.actions.push(value);
                selectedContextMenuProjectId = 42;
                allProjectsData = [{id: 42, name: 'Keyboard project'}];
                document.getElementById('project-context-menu').style.display = 'block';
            }''')
            assert page.locator('button button').count() == 0
            trigger = page.locator('#ctx-filter-menu').locator('..')
            api.expect(trigger).to_have_role('button')
            trigger.focus()
            page.keyboard.press('Enter')
            api.expect(page.locator('#ctx-filter-this')).to_be_visible()
            page.keyboard.press('Tab')
            api.expect(page.locator('#ctx-filter-this')).to_be_focused()
            page.keyboard.press('Space')
            events = page.evaluate('window.actions')
            assert [(event['action'], event['project_id'], event['filter_scope'])
                    for event in events] == [('filter_project', 42, 'this')]
            toggle = page.get_by_role('button', name='Toggle resource pools grid')
            toggle.focus()
            page.keyboard.press('Enter')
            api.expect(page.locator('#resource-grid-main')).to_have_class(re.compile('collapsed'))
            page.keyboard.press('Space')
            api.expect(page.locator('#resource-grid-main')).not_to_have_class(re.compile('collapsed'))
            page.evaluate('''() => {
                canManageSharedData = true;
                openResourceCellContextMenu(new MouseEvent('contextmenu', {clientX: 100, clientY: 100}),
                    7, 'Pool', '', '', '', null, 'alternative');
            }''')
            api.expect(page.locator('#ctx-res-details-btn')).to_be_disabled()
            pool_filter = page.locator('#ctx-res-filter-btn > button')
            api.expect(pool_filter).to_be_enabled()
            pool_filter.focus()
            page.keyboard.press('Tab')
            api.expect(page.locator('[data-resource-filter="consuming"]')).to_be_focused()
            assert page.locator('.context-menu-item').evaluate_all(
                "nodes => nodes.every(node => node.tagName === 'BUTTON')")
            assert not errors, errors
        finally:
            browser.close()
