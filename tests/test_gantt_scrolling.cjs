// Run with: node --test tests/test_gantt_scrolling.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../app/presentation/assets/components/gantt/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

test('entire Gantt script parses', () => new vm.Script(script));

test('hide-unused pools preserves ancestors, respects collapsed groups, and updates on project changes', () => {
  const pools = [{id: 1, used_by_selected_projects: true}, {id: 2, used_by_selected_projects: false}];
  const hierarchy = [{key: 'root', node_type: 'group', children: [
    {key: 'nested', node_type: 'group', children: [{key: 'pool:1', node_type: 'pool', pool_id: 1}]},
    {key: 'empty', node_type: 'group', children: [{key: 'pool:2', node_type: 'pool', pool_id: 2}]},
  ]}];
  const context = vm.createContext({resourcePoolIndex: new Map(pools.map(p => [p.id, p])),
    resourcePoolsData: pools, resourcePoolHierarchy: hierarchy, collapsedResourceNodes: new Set(),
    showTotalRows: true, showSelectedRows: true, groupUsageCache: new Map()});
  const run = code => vm.runInContext(code, context);
  run(script.slice(script.indexOf('    function getResourcePoolById('), script.indexOf('    function renderResourceGrid(')));
  assert.equal(run('getResourceDisplayRows().length'), 9);
  run('hideUnusedPools = true');
  assert.deepEqual([...run('getResourceDisplayRows().map(row => row.nodeKey)')],
    ['root', 'nested', 'pool:1', 'pool:1', 'pool:1']);
  run("collapsedResourceNodes.add('nested')");
  assert.equal(run('getResourceDisplayRows().length'), 2);
  pools[0].used_by_selected_projects = false;
  pools[1].used_by_selected_projects = true;
  assert.deepEqual([...run('getResourceDisplayRows().map(row => row.nodeKey)')],
    ['root', 'empty', 'pool:2', 'pool:2', 'pool:2']);
  pools[1].used_by_selected_projects = false;
  assert.equal(run('getResourceDisplayRows().length'), 0);
  run('hideUnusedPools = false');
  assert.equal(run('getResourceDisplayRows().length'), 6);
  assert.doesNotMatch(html.match(/<input[^>]*id="chk-hide-unused-pools"[^>]*>/)[0], /\schecked/);
});

test('external links start disabled in both the toolbar and renderer', () => {
  assert.doesNotMatch(html.match(/<input[^>]*id="chk-external-links"[^>]*>/)[0], /\schecked(?:\s|=|>)/);
  assert.match(script, /let showExternalLinks = false;/);
});

test('overallocation filter uses daily capacity and composes with the selected-project filter', () => {
  const pools = [
    {id:1, used_by_selected_projects:true, capacity:4, daily_usage:{'2026-01-02':3}},
    {id:2, used_by_selected_projects:false, capacity:4, daily_usage:{'2026-01-02':1}, daily_assigned_capacity:{'2026-01-02':0}},
    {id:3, used_by_selected_projects:true, capacity:4, daily_usage:{'2026-01-02':5}},
  ];
  const context = vm.createContext({resourcePoolIndex:new Map(pools.map(p=>[p.id,p])),
    resourcePoolHierarchy:[{key:'group',node_type:'group',children:pools.map(p=>({key:'pool:'+p.id,node_type:'pool',pool_id:p.id}))}],
    resourcePoolsData:pools, collapsedResourceNodes:new Set(), groupUsageCache:new Map(),
    showTotalRows:true, showSelectedRows:true, timelineStart:'2026-01-01',timelineEnd:'2026-01-03',formatDate:d=>d});
  const run = code=>vm.runInContext(code,context);
  run(script.slice(script.indexOf('    const EMPTY_DAILY_SERIES ='),script.indexOf('    function isDisplayedPoolPeriodOverallocated(')));
  run(script.slice(script.indexOf('    function getResourcePoolById('),script.indexOf('    function renderResourceGrid(')));
  run('resourcePoolIndex=new Map(resourcePoolsData.map(p=>[p.id,p]));onlyOverallocatedPools=true');
  assert.deepEqual([...run('resourcePoolsData.filter(isResourcePoolVisible).map(p=>p.id)')],[2,3]);
  assert.equal(run('getResourceDisplayRows()[0].nodeKey'),'group');
  run('hideUnusedPools=true');
  assert.deepEqual([...run('resourcePoolsData.filter(isResourcePoolVisible).map(p=>p.id)')],[3]);
  run("timelineStart='2026-02-01';timelineEnd='2026-02-02'");
  assert.equal(run('getResourceDisplayRows().length'),0);
});

function dependencyWindow() {
  function node() {
    return {children: [], attributes: {}, events: {}, style: {}, writes: 0,
      setAttribute(key, value) {this.attributes[key] = value; this.writes++;},
      appendChild(child) {this.children.push(child); child.parent = this;},
      replaceChildren() {this.children = [];},
      addEventListener(name, fn) {this.events[name] = fn;},
      remove() {this.parent.children = this.parent.children.filter(child => child !== this);}};
  }
  const group = node(), viewport = node(), scroller = {scrollLeft: 0, clientWidth: 900};
  const context = vm.createContext({
    document: {createElementNS: node, getElementById: id => ({'grid-links-group': group,
      'dependency-viewport': viewport, 'timeline-body-scroller': scroller})[id]},
    tasksByIdMap: new Map(), taskIncomingDeps: new Map(), taskOutgoingDeps: new Map(),
    projIncomingDeps: new Map(), projOutgoingDeps: new Map(),
    currentProjectId: null, totalTimelineWidth: 20000, showExternalLinks: true, showInternalLinks: true,
    collapsedProjects: new Set(['A', 'B']), allTaskPositions: {},
    allProjectPositions: {
      A: {rowIdx: 0, startX: 10, endX: 100, centerY: 23, isProject: true},
      B: {rowIdx: 8, startX: 200, endX: 300, centerY: 391, isProject: true}},
    masterRenderItems: Array.from({length: 20}, (_, i) => i === 0 || i === 8 ?
      {type: 'project_header', project_id: i === 0 ? 'A' : 'B', isCollapsed: true} : {}),
    tasksData: [11, 12].map(id => ({id, project_id: 'A', name: `Predecessor ${id}`, start: '2026-01-01', end: '2026-01-02'})).concat(
      [21, 22, 23, 24].map((id, i) => ({id, name: `Successor ${id}`, project_id: 'B', start: '2026-01-03', end: '2026-01-04',
        dependenciesList: [{predecessor_task_id: i === 1 ? 12 : 11, predecessor_project_id: 'A',
          link_type: i === 2 ? 'SS' : 'FS', lag_days: i, is_violated: i === 3}]}))),
    formatMmmYy: value => {context.dateFormats++; return value;}, dateFormats: 0,
    formatLinkTypeLabel: type => type,
    showDependencyBundleMenu: (event, bundle) => {context.clickedBundle = bundle;},
  });
  const run = code => vm.runInContext(code, context);
  run(script.slice(script.indexOf('    const renderedDependencyLinks ='), script.indexOf('    function highlightRow(')));
  run(script.slice(script.indexOf('    function buildDependencyIndex('), script.indexOf('    function renderTimeline(')));
  run('buildDependencyIndex()');
  return {run, context, group, viewport, scroller};
}

test('collapsed dependencies share paths without losing details, lag or violation status', () => {
  const h = dependencyWindow();
  h.run('renderDependencyLinks(0, 10)');
  assert.equal(h.group.children.length, 3, 'identical anchors share a line; type and violation remain distinct');
  assert.equal(h.context.dateFormats, 0, 'scroll rendering must not format dependency detail dates');
  const first = h.group.children[0];
  first.children[1].events.click({preventDefault() {}, stopPropagation() {}});
  const members = h.context.clickedBundle.members;
  assert.equal(members.length, 2);
  assert.equal(members[0].getInfo().succId, 21);
  assert.equal(members[1].getInfo().succId, 22);
  assert.equal(members[1].getInfo().lagStr, '+1 day(s)');
  h.run('renderDependencyLinks(0, 11)');
  assert.equal(h.group.children[0], first, 'overlapping scroll windows retain their SVG nodes');
  assert.equal(h.context.clickedBundle.members.length, 2, 'reusing a line must not accumulate duplicate members');
  h.run('showExternalLinks = false; renderDependencyLinks(0, 11)');
  assert.equal(h.group.children.length, 0);
  h.run('showExternalLinks = true; renderDependencyLinks(0, 11)');
  assert.equal(h.group.children.length, 3);
  h.run('renderDependencyLinks(12, 19)');
  assert.equal(h.group.children.length, 0);
  assert.equal(h.run('renderedDependencyLinks.size'), 0, 'cache is bounded by the current window');
});

test('expanded headers skip hidden task links and dependency geometry refreshes after edits', () => {
  const h = dependencyWindow();
  h.run('renderDependencyLinks(0, 10)');
  const previous = h.group.children[0];
  h.run('allProjectPositions.B.startX = 400; buildDependencyIndex(); renderDependencyLinks(0, 10)');
  assert.notEqual(h.group.children[0], previous);
  assert.match(h.group.children[0].children[0].attributes.d, /H 400$/);
  h.run("masterRenderItems[0].isCollapsed = false; masterRenderItems[8].isCollapsed = false; collapsedProjects.clear(); renderDependencyLinks(0, 10)");
  assert.equal(h.group.children.length, 0);
  h.run(`
    allTaskPositions = {11: {rowIdx: 1, startX: 10, endX: 100, centerY: 69, project_id: 'A'},
      21: {rowIdx: 9, startX: 200, endX: 300, centerY: 437, project_id: 'B'}};
    masterRenderItems[1] = {task: tasksData[0]}; masterRenderItems[9] = {task: tasksData[2]};
    buildDependencyIndex(); renderDependencyLinks(0, 10);
  `);
  assert.equal(h.group.children.length, 1, 'visible task links remain available when projects expand');
});

test('dependency painting is clipped to the viewport and horizontal overscan is reused', () => {
  const h = dependencyWindow();
  h.scroller.scrollLeft = 3000;
  h.run('updateDependencyClip(5, 30)');
  assert.equal(h.viewport.attributes.viewBox, '2400 230 2100 1196');
  const writes = h.viewport.writes;
  h.scroller.scrollLeft = 3100;
  h.run('updateDependencyClip(5, 30)');
  assert.equal(h.viewport.writes, writes);
  h.scroller.scrollLeft = 8000;
  h.run('updateDependencyClip(5, 30)');
  assert.equal(h.viewport.attributes.viewBox, '7400 230 2100 1196');
});

test('off-screen predecessor markers retain every dependency and disappear outside the window', () => {
  const h = dependencyWindow();
  h.run('delete allProjectPositions.A; renderDependencyLinks(0, 10)');
  assert.equal(h.group.children.length, 3);
  assert.equal(h.group.children[0].children.length, 3, 'stub includes line, hit target and entry dot');
  h.group.children[0].children[2].events.click({preventDefault() {}, stopPropagation() {}});
  assert.equal(h.context.clickedBundle.members.length, 2);
  h.run('renderDependencyLinks(0, 3)');
  assert.equal(h.group.children.length, 0, 'an off-screen successor must not leave an orphan stub');
});

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
    scheduleProjectLoads: () => {},
    requestAnimationFrame: callback => { frames.push(callback); return frames.length; },
  });
  vm.runInContext(script.slice(script.indexOf('    const renderedDependencyLinks ='),
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

test('period indexes retain minimum capacity and detect a single overallocated day', () => {
  const context = vm.createContext({});
  vm.runInContext(script.slice(script.indexOf('    const EMPTY_DAILY_SERIES ='),
    script.indexOf('    function isDisplayedPoolPeriodOverallocated(')), context);
  vm.runInContext(`
    const capacity = {'2026-01-02': 0, '2026-01-03': 8};
    const usage = {'2026-01-01': 3, '2026-01-02': 0.1, '2026-01-03': 4};
    const result = getAssignedCapacityForPeriod(4, capacity, '2026-01-01', '2026-03-31');
    const status = getDemandCapacityStatusForPeriod(usage, 4, capacity, '2026-01-01', '2026-03-31');
  `, context);
  assert.equal(vm.runInContext('result.min', context), 0);
  assert.equal(vm.runInContext('result.max', context), 8);
  assert.equal(vm.runInContext('status.isOverallocated', context), true);
  assert.equal(vm.runInContext('status.maxExcess', context), 0.1);
  assert.equal(vm.runInContext("getAssignedCapacityForPeriod(4, capacity, '2026-01-01', '2026-03-31') === result", context), true);
  assert.equal(vm.runInContext("getDemandCapacityStatusForPeriod(usage, 4, capacity, '2026-01-01', '2026-03-31') === status", context), true);
  assert.equal(vm.runInContext("getAssignedCapacityForPeriod(5, null, '2026-01-01', '2026-12-31').min", context), 5);
  assert.equal(vm.runInContext("getAssignedCapacityForPeriod(4, {'2026-01-01':8}, '2026-01-01', '2026-01-01').min", context), 8);
  assert.equal(vm.runInContext("getDemandCapacityStatusForPeriod(usage, 4, capacity, '2026-01-03', '2026-03-31').isOverallocated", context), false);
});

test('external choice requests are queued, stale responses ignored, and selected predecessors preserved', () => {
  const messages = [], refreshed = [];
  function row() {
    const select = {disabled: false, appendChild() {}};
    return {isConnected: true, querySelector: () => select};
  }
  const a = row(), b = row();
  const context = vm.createContext({a, b,
    document: {createElement: () => ({})}, externalTasksData: {},
    Streamlit: {setComponentValue: value => messages.push(value)},
    populateDepTargets: (row, initial) => refreshed.push(initial.predecessor_task_id),
  });
  vm.runInContext(script.slice(script.indexOf('    const dependencyRequests ='),
    script.indexOf('    function populateDepTargets(')), context);
  vm.runInContext("requestDependencyChoices('2', a, {predecessor_task_id:21}); requestDependencyChoices('3', b, {predecessor_task_id:31});", context);
  assert.equal(messages.length, 1);
  assert.equal(a.querySelector().disabled, true);
  context.response = {project_id: '2', nonce: 'old', tasks: []};
  vm.runInContext('receiveDependencyChoices(response)', context);
  assert.equal(messages.length, 1);
  context.response.nonce = messages[0].nonce;
  vm.runInContext('receiveDependencyChoices(response)', context);
  assert.deepEqual(refreshed, [21]);
  assert.equal(messages.length, 2);
  assert.equal(messages[1].project_id, '3');
  b._dependencyProject = '4'; // user changed the project while the old request was pending
  context.response = {project_id: '3', nonce: messages[1].nonce, tasks: []};
  vm.runInContext('receiveDependencyChoices(response)', context);
  assert.deepEqual(refreshed, [21]);
});
