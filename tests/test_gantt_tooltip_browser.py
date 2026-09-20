"""Hover tooltips wait, cancel cleanly, and suppress competing native titles."""

from pathlib import Path

from tests.test_dialog_browser import expect, sync_playwright


def test_gantt_hover_delay_and_native_title_restoration():
    source = Path('app/presentation/assets/components/gantt/index.html').read_text(encoding='utf-8')
    script = source[source.index('    let tooltipTimer ='):source.index('    function scenarioTooltip(')]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content('''<div id="timeline-canvas"><button title="Basic" id="bar">Task</button></div>
                <div id="gantt-tooltip" style="display:none;position:fixed"></div>''')
            page.add_script_tag(content='let showHoverOverlay = true;\n' + script + '''
                const bar = document.getElementById('bar');
                bar.onmouseenter = event => showTooltip(event, 'Rich task details');
                bar.onmousemove = moveTooltip;
                bar.onmouseleave = hideTooltip;
            ''')
            bar = page.locator('#bar')
            tooltip = page.locator('#gantt-tooltip')
            bar.hover()
            expect(bar).not_to_have_attribute('title', 'Basic')
            page.wait_for_timeout(600)
            expect(tooltip).to_be_hidden()
            expect(tooltip).to_be_visible(timeout=1000)
            expect(tooltip).to_have_text('Rich task details')
            page.mouse.move(500, 500)
            expect(tooltip).to_be_hidden()
            bar.hover()
            page.wait_for_timeout(200)
            page.mouse.move(500, 500)
            page.wait_for_timeout(1100)
            expect(tooltip).to_be_hidden()
            page.evaluate('toggleHoverVisibility(false)')
            expect(bar).to_have_attribute('title', 'Basic')
        finally:
            browser.close()
