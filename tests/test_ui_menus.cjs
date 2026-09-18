const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
const html = read('app/presentation/assets/components/gantt/index.html');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
function loadFunction(context, name) {
  const start = script.indexOf('    function ' + name + '(');
  const end = script.indexOf('\n    function ', start + 1);
  vm.runInContext(script.slice(start, end), context);
}

function loadPermissions(context, projectIds) {
  // Use the production scenario state and guards together, as the page does.
  vm.runInContext(script.slice(script.indexOf('    let tasksData ='),
    script.indexOf('    function toggleBaseline(')), context);
  vm.runInContext(script.slice(script.indexOf('    let editAllProjects ='),
    script.indexOf('    let allProjectsData =')), context);
  loadFunction(context, 'canImportProject');
  context.selectedContextMenuProjectAlternative = false;
  context.updatePermissionControls({editable_projects: projectIds});
  // These tests exercise permitted menu actions; read-only behavior is covered
  // separately by test_gantt_permissions.cjs.
  vm.runInContext('editEnabled = true', context);
}

test('project CSV menu and pool allocation menu retain the selected identity', () => {
  const events = [];
  const context = vm.createContext({
    selectedContextMenuProjectId: '42', hideProjectContextMenu(){}, hideResourceCellContextMenu(){},
    selectedResourceCellCtx: {pool_id: 8, pool_name: 'Delivery'},
    Streamlit: {setComponentValue: value => events.push(value)},
  });
  loadPermissions(context, [42]);
  loadFunction(context, 'triggerManageProjectTagsFromMenu');
  loadFunction(context, 'triggerGoToResourcePoolDetails');
  vm.runInContext(`triggerManageProjectTagsFromMenu('import_csv_template');
    triggerManageProjectTagsFromMenu('export_csv_template');
    triggerGoToResourcePoolDetails('show_pool_allocations');`, context);
  assert.deepEqual(events.map(e => [e.action, e.project_id || e.pool_id]),
    [['import_csv_template', '42'], ['export_csv_template', '42'], ['show_pool_allocations', 8]]);
  assert.match(html, /onclick="openAddStepModal\(selectedContextMenuProjectId\)"/);
});

test('capacity cells provide pool and period context and only the underassignment badge is orange', () => {
  const cell = html.slice(html.indexOf('return `<div class="resource-demand-cell assigned-capacity-cell'),
    html.indexOf('const isCollapsedPool ='));
  assert.match(cell, /data-pool-id="\$\{pool.id\}"/);
  assert.match(cell, /oncontextmenu="handleCellContextMenu\(event, this\)"/);
  const style = html.match(/\.underassignment-badge\s*\{([^}]+)\}/)[1];
  assert.match(style, /#ffedd5/);
  assert.doesNotMatch(html, /\.assigned-capacity-cell\.capacity-under\s*\{/);
  assert.doesNotMatch(html, /\.assigned-capacity-row\.capacity-under\s*\{/);
});

test('project filter submenu forwards every scope and group menus retain group identity', () => {
  const events = [];
  const context = vm.createContext({
    selectedContextMenuProjectId: '42', selectedContextMenuTask: null,
    allProjectsData: [{id:'42', name:'Selected'}],
    hideProjectContextMenu(){}, hideContextMenu(){}, hideResourceCellContextMenu(){},
    selectedResourceCellCtx: {pool_id:null, group_id:7, pool_name:'Group', start_date:'', end_date:''},
    Streamlit: {setComponentValue: value => events.push(value)},
  });
  for (const name of ['triggerFilterContextProject','triggerFilterResourcePool','triggerGoToResourcePoolDetails']) loadFunction(context, name);
  for (const scope of ['this','all','predecessors']) context.triggerFilterContextProject('project', scope);
  assert.deepEqual(events.map(event=>event.filter_scope), ['this','all','predecessors']);
  context.triggerFilterResourcePool(true);
  context.triggerGoToResourcePoolDetails('show_pool_allocations');
  assert.deepEqual(events.slice(3).map(event=>[event.action,event.group_id]),
    [['filter_by_resource_pool',7],['show_pool_allocations',7]]);
  assert.equal((html.match(/oncontextmenu="handleGroupContextMenu\(event\)"/g)||[]).length, 2);
  assert.match(html, /#project-context-menu[^{}]*\{\s*overflow:visible/);
});

test('opening project and task menus keeps nested submenus outside their scroll boxes', () => {
  const menu = {style:{},offsetWidth:210,offsetHeight:220};
  const context = vm.createContext({
    document:{getElementById:id=>id === 'project-context-menu' ? menu : null},
    window:{innerWidth:1000,innerHeight:700}, tasksData:[], projectDependencyIssues:()=>[],
    hideContextMenu(){},hideDepContextMenu(){},hideTooltip(){},
  });
  loadPermissions(context, [42]);
  loadFunction(context,'showProjectContextMenu');
  context.showProjectContextMenu({clientX:980,clientY:680,preventDefault(){},stopPropagation(){}},42);
  assert.equal(menu.style.overflow,'visible');
  assert.equal(menu.style.overflowY,undefined);
  assert.ok(parseFloat(menu.style.left) + menu.offsetWidth <= 990);
  assert.ok(parseFloat(menu.style.top) + menu.offsetHeight <= 690);
  const taskMenu = {style:{},offsetWidth:230,offsetHeight:300};
  context.document.getElementById = id => id === 'context-menu' ? taskMenu : {style:{}, closest(){return this;}};
  context.hideProjectContextMenu = () => {};
  loadFunction(context,'showContextMenu');
  context.showContextMenu({clientX:980,clientY:680,preventDefault(){},stopPropagation(){}}, {id:1,project_id:42});
  assert.equal(taskMenu.style.overflow,'visible');
  assert.equal(taskMenu.style.overflowY,undefined);
  assert.ok(parseFloat(taskMenu.style.left) + taskMenu.offsetWidth <= 990);
  assert.ok(parseFloat(taskMenu.style.top) + taskMenu.offsetHeight <= 690);
});

test('pool hover details show both assignment extremes while purple stays on a badge', () => {
  const context = vm.createContext({getT:(_, fallback)=>fallback,
    getAssignedCapacityForPeriod:()=>({min:1,max:4})});
  loadFunction(context,'poolAssignmentDetails');
  loadFunction(context,'poolAssignmentBadges');
  const pool={name:'Full pool name',theoretical_capacity:2,has_assigned_resources:true};
  const details=context.poolAssignmentDetails(pool,'2026-01-01','2026-01-31');
  assert.match(details,/Full pool name/);
  assert.equal(details,'Full pool name\nDefined capacity: 2.00 FTE\nMin assigned capacity: 1.00 FTE\nMax assigned capacity: 4.00 FTE');
  context.getAssignedCapacityForPeriod = () => ({min:2,max:2});
  assert.equal(context.poolAssignmentDetails(pool,'2026-01-01','2026-01-31'),'Full pool name');
  context.getAssignedCapacityForPeriod = () => ({min:1,max:2});
  assert.equal(context.poolAssignmentDetails(pool,'2026-01-01','2026-01-31'),
    'Full pool name\nDefined capacity: 2.00 FTE\nMin assigned capacity: 1.00 FTE');
  context.getAssignedCapacityForPeriod = () => ({min:2,max:4});
  assert.equal(context.poolAssignmentDetails(pool,'2026-01-01','2026-01-31'),
    'Full pool name\nDefined capacity: 2.00 FTE\nMax assigned capacity: 4.00 FTE');
  const badges=context.poolAssignmentBadges(pool,{min:1,max:4},2);
  assert.match(badges,/underassignment-badge/);
  assert.match(badges,/overassignment-badge/);
  assert.doesNotMatch(html,/\.assigned-capacity-cell\.capacity-over\s*\{/);
  assert.doesNotMatch(html,/\.assigned-capacity-row\.capacity-over\s*\{/);
  assert.match(html,/\.overassignment-badge\s*\{[^}]*#f3e8ff/);
  assert.equal((html.match(/data-resource-filter=/g)||[]).length,3);
  assert.equal((html.match(/data-filter-label=/g)||[]).length,3);
});

test('task Assign Resource action uses a person icon and retains the clicked task', () => {
  assert.match(html, /onclick="triggerManageTaskPools\(\)">\s*<span>👤<\/span>\s*<span id="ctx-label-task-pools">Assign Resource<\/span>/);
  assert.match(script, /elTaskPools\.innerText = getT\('context_menu.assign_resource', 'Assign Resource'\)/);
  const events = [];
  const context = vm.createContext({hideContextMenu(){},
    selectedContextMenuTask:{id:'17',name:'Design',project_id:4},
    Streamlit:{setComponentValue:value=>events.push(value)}});
  loadPermissions(context, [4]);
  loadFunction(context,'triggerManageTaskPools');
  context.triggerManageTaskPools();
  assert.equal(events[0].action,'manage_task_pools');
  assert.equal(events[0].id,17);
  assert.equal(events[0].project_id,4);
});

test('resource hover card contains only the escaped concise assignment summary', () => {
  const tooltips = [];
  const context = vm.createContext({showHoverOverlay:true,
    escapeHtml:value=>value.replaceAll('<','&lt;').replaceAll('>','&gt;'),
    showTooltip:(_,value)=>tooltips.push(value)});
  loadFunction(context,'showResourceCellTooltip');
  context.showResourceCellTooltip({},'Pool <A>');
  assert.equal(tooltips[0],'<div style="font-size:12px;line-height:1.45;white-space:pre-wrap">Pool &lt;A&gt;</div>');
  context.showHoverOverlay = false;
  context.showResourceCellTooltip({},'Hidden');
  assert.equal(tooltips.length,1);
});

test('pool hover inserts colored availability below its escaped title', () => {
  const tooltips = [];
  const context = vm.createContext({showHoverOverlay:true,
    getT:(_,fallback)=>fallback,
    escapeHtml:value=>value.replaceAll('<','&lt;').replaceAll('>','&gt;'),
    showTooltip:(_,value)=>tooltips.push(value)});
  loadFunction(context,'formatResourceValue');
  loadFunction(context,'showResourceCellTooltip');
  context.showResourceCellTooltip({},'Pool <A>\nDefined capacity: 5 FTE',
    {isOverallocated:false,minAvailable:2.5,maxExcess:0});
  assert.match(tooltips[0], /<strong>Pool &lt;A&gt;<\/strong><div style="color:#4ade80/);
  assert.match(tooltips[0], /Available: 2.5 FTE<\/div>Defined capacity: 5 FTE/);
  context.showResourceCellTooltip({},'Pool B',{isOverallocated:true,minAvailable:0,maxExcess:1.2});
  assert.match(tooltips[1], /color:#f87171/);
  assert.match(tooltips[1], /Overallocated: 1.2 FTE/);
});

test('pool cell hover respects selected-project scope and capacity exceptions', () => {
  const total = {}, selected = {}, calendar = {'2026-01-01':0};
  const pool = {name:'Pool',daily_usage:total,selected_projects_daily_usage:selected,
    daily_assigned_capacity:calendar,displayed_assigned_capacity:5,has_assigned_resources:false};
  const calls = [];
  const context = vm.createContext({getResourcePoolById:()=>pool,
    poolAssignmentDetails:()=>pool.name,showResourceCellTooltip(){},
    getDemandCapacityStatusForPeriod:(...args)=>{calls.push(args);return {};}});
  loadFunction(context,'handleCellMouseEnter');
  for(const scope of ['selected','total'])context.handleCellMouseEnter({},
    {dataset:{poolId:'1',scope,startDate:'2026-01-01',endDate:'2026-01-02'}});
  assert.equal(calls[0][0],selected);
  assert.equal(calls[1][0],total);
  assert.equal(calls[0][2],calendar);
});

test('allocation popup and filter actions retain the clicked quarter and row scope', () => {
  const events=[];
  const context=vm.createContext({hideResourceCellContextMenu(){},canManageSharedData:false,
    selectedResourceCellCtx:{pool_id:1,pool_name:'Pool A',start_date:'2025-07-01',end_date:'2025-09-30',allocation_scope:'selected'},
    Streamlit:{setComponentValue:value=>events.push(value)}});
  loadFunction(context,'triggerGoToResourcePoolDetails');
  loadFunction(context,'triggerFilterResourcePool');
  context.triggerGoToResourcePoolDetails('show_pool_allocations');
  context.triggerFilterResourcePool(true);
  for(const event of events){
    assert.equal(event.start_date,'2025-07-01');assert.equal(event.end_date,'2025-09-30');
    assert.equal(event.allocation_scope,'selected');
  }
  context.selectedResourceCellCtx.allocation_scope='total';
  context.triggerGoToResourcePoolDetails('show_pool_allocations');
  assert.equal(events[2].allocation_scope,'total');
});

test('CSV export fetches the access-controlled endpoint once per nonce without a modal or cached blob', () => {
  const source = read('app/presentation/components/csv_download.py');
  const js = source.match(/_DOWNLOAD_JS = """([\s\S]*?)"""/)[1];
  const clicks = [];
  const root = {dataset:{}, appendChild(){}};
  const parentElement = {querySelector:()=>root};
  const context = vm.createContext({
    document: {createElement:tag=>{
      assert.equal(tag, 'a');
      return {click(){clicks.push([this.href, this.download]);},remove(){}};
    }},
  });
  vm.runInContext(js.replace('export default function', 'function mount'), context);
  const data = {nonce:'one',filename:'project_42_template.csv',url:'/downloads/projects/42/template.csv'};
  context.mount({data,parentElement});
  context.mount({data,parentElement});
  assert.deepEqual(clicks,[['/downloads/projects/42/template.csv','project_42_template.csv']]);
  context.mount({data:{...data, nonce:'two'},parentElement});
  assert.equal(clicks.length, 2);
  assert.equal(clicks[1][0], '/downloads/projects/42/template.csv');
});

test('lazy-tab position guard crosses the component shadow root and retains the greatest height', () => {
  const js = read('app/presentation/components/tab_position.py').match(/_POSITION_JS = """([\s\S]*?)"""/)[1];
  const listeners = new Map();
  const panel = {clientHeight: 720, style: {},
    addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: name => listeners.delete(name)};
  const host = {closest: name => name === '.st-key-details' ? panel : null, getRootNode: () => ({})};
  const parent = {closest: () => null, getRootNode: () => ({host})};
  const context = vm.createContext({});
  vm.runInContext(js.replace('export default function', 'function mount'), context);
  const cleanup = context.mount({data: {panel_key: 'details'}, parentElement: parent});
  const tabEvent = {target: {closest: selector => selector === '[role="tab"]'}};
  listeners.get('pointerdown')(tabEvent);
  assert.equal(panel.style.minHeight, '720px');
  panel.clientHeight = 300;
  listeners.get('keydown')(tabEvent);
  assert.equal(panel.style.minHeight, '720px');
  panel.clientHeight = 900;
  listeners.get('pointerdown')(tabEvent);
  assert.equal(panel.style.minHeight, '900px');
  cleanup();
  assert.equal(listeners.size, 0);
});

test('log right-click and keyboard menus edit the requested row and clean up listeners', () => {
  const js = read('app/presentation/components/action_table.py').match(/_TABLE_JS = r"""([\s\S]*?)"""/)[1];
  function element(tag) {
    return {tag, children: [], style: {}, attributes: {}, offsetWidth: 220, offsetHeight: 50,
      appendChild(child) {this.children.push(child); child.parent = this;},
      replaceChildren() {this.children = [];},
      setAttribute(key, value) {this.attributes[key] = value;},
      remove() {this.parent.children = this.parent.children.filter(c => c !== this);},
      querySelector(tag) {return this.children.find(c => c.tag === tag);},
      focus(){}, getBoundingClientRect() {return {left: 20, bottom: 50};},
      set innerHTML(value) {throw Error('Unsafe HTML');},
    };
  }
  const root = element('div'), events = [], listeners = new Map();
  const context = vm.createContext({window: {innerWidth: 1000, innerHeight: 600}, document: {
    createElement: element, addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: name => listeners.delete(name),
  }});
  vm.runInContext(js.replace('export default function', 'function mount'), context);
  const cleanup = context.mount({data: {rows: [{id: 7, description: 'First line\n<script>literal</script>'}],
    columns: [['description', 'Description']], actions: {edit: 'Edit entry'}, context_menu: true},
    parentElement: {querySelector: () => root}, setTriggerValue: (key, value) => events.push({key, ...value})});
  const row = root.children[0].children[1].children[0];
  assert.equal(row.children[0].textContent, 'First line\n<script>literal</script>');
  row.oncontextmenu({preventDefault(){}, stopPropagation(){}, clientX: 999, clientY: 599});
  let menu = root.children[1];
  assert.equal(menu.style.left, '770px');
  menu.children[0].onclick();
  row.onkeydown({key: 'F10', shiftKey: true, preventDefault(){}, stopPropagation(){}});
  menu = root.children[1];
  menu.children[0].onclick();
  assert.deepEqual(events, [{key: 'action', id: 7, action: 'edit'}, {key: 'action', id: 7, action: 'edit'}]);
  cleanup();
  assert.equal(listeners.size, 0);
});
