// Run with: node --test tests/test_gantt_scrolling.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../src/components/gantt/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

test('entire Gantt script parses', () => new vm.Script(script));

function virtualWindow() {
  const frames = [];
  let writes = 0;
  const container = { set innerHTML(value) { writes++; } };
  const scroller = { scrollTop: 0, clientHeight: 550 };
  const context = vm.createContext({
    masterRenderItems: Array.from({length: 10000}, () => ({})),
    document: { getElementById: id => id === 'timeline-body-scroller' ? scroller :
      id === 'frozen-rows-container' ? container : null },
    getTotalFrozenWidth: () => 400,
    requestAnimationFrame: callback => { frames.push(callback); return frames.length; },
  });
  vm.runInContext(script.slice(script.indexOf('    let renderedRowWindow ='),
    script.indexOf('    function highlightRow(')), context);
  return { context, scroller, frames, writes: () => writes,
    run: code => vm.runInContext(code, context) };
}

test('scrolling reuses overscan, updates on large jumps, and refreshes after edits', () => {
  const harness = virtualWindow();
  harness.run('renderVirtualWindow()');
  assert.equal(harness.writes(), 1);
  for (let offset = 0; offset <= 400; offset += 10) {
    harness.run(`renderVirtualWindow(${offset}, false)`);
  }
  assert.equal(harness.writes(), 1, 'small scrolls must preserve existing DOM');
  harness.run('renderVirtualWindow(200000, false)');
  assert.equal(harness.writes(), 2, 'scrollbar jumps must paint the new window');
  harness.run('renderVirtualWindow(200000)');
  assert.equal(harness.writes(), 3, 'data/column/toggle changes must force repaint');
  harness.run('masterRenderItems = []; renderVirtualWindow()');
  assert.equal(harness.run('renderedRowWindow'), null);
});

test('scroll events are coalesced per frame and use the latest position', () => {
  const harness = virtualWindow();
  for (let event = 0; event < 100; event++) harness.run('scheduleVirtualWindow()');
  assert.equal(harness.frames.length, 1);
  harness.scroller.scrollTop = 50000;
  harness.frames.shift()();
  assert.equal(harness.writes(), 1);
  assert.ok(harness.run('renderedRowWindow.start') > 1000);
  harness.run('scheduleVirtualWindow()');
  harness.frames.shift()();
  assert.equal(harness.writes(), 1, 'horizontal scroll must not repaint rows');
});

test('dependency editor finds tasks from both chart data and off-screen projects', () => {
  const options = [];
  const target = { set innerHTML(value) { options.length = 0; }, appendChild: option => options.push(option) };
  const checkbox = { checked: true };
  const project = { value: '2' };
  const row = { querySelector: selector => ({ '.dep-is-ext': checkbox, '.dep-target': target, '.dep-proj': project })[selector] };
  const context = vm.createContext({
    row,
    tasksData: [
      { id: '11', project_id: '1', name: 'Current' },
      { id: '12', project_id: '1', name: 'Internal predecessor' },
      { id: '21', project_id: '2', name: 'Visible external predecessor' },
    ],
    currentProjectId: '1',
    allProjectsData: [{ id: '1' }, { id: '2' }, { id: '3' }],
    externalTasksData: { '3': [{ id: '31', task_name: 'Hidden external predecessor' }] },
    selectedContextMenuTask: { id: '11' },
    getActiveModalProjectId: () => '1',
    getT: (key, fallback) => fallback,
    document: { createElement: () => ({}) },
  });
  vm.runInContext(script.slice(script.indexOf('    function populateDepTargets('),
    script.indexOf('    function saveEditModal(')), context);
  vm.runInContext('populateDepTargets(row, {predecessor_task_id: 21})', context);
  assert.deepEqual(options.map(option => option.value), ['PROJ:2', 'TASK:21']);
  assert.equal(options[1].selected, true);
  project.value = '3';
  vm.runInContext('populateDepTargets(row)', context);
  assert.deepEqual(options.map(option => option.value), ['PROJ:3', 'TASK:31']);
  checkbox.checked = false;
  vm.runInContext('populateDepTargets(row)', context);
  assert.deepEqual(options.map(option => option.value), ['', 'TASK:12']);
});
