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

test('project CSV menu and pool allocation menu retain the selected identity', () => {
  const events = [];
  const context = vm.createContext({
    selectedContextMenuProjectId: '42', hideProjectContextMenu(){}, hideResourceCellContextMenu(){},
    selectedResourceCellCtx: {pool_id: 8, pool_name: 'Delivery'},
    Streamlit: {setComponentValue: value => events.push(value)},
  });
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
  assert.match(html, /#project-context-menu\s*\{\s*overflow:visible/);
});

test('opening the project menu keeps nested submenus outside its scroll box', () => {
  const menu = {style:{},offsetWidth:210,offsetHeight:220};
  const context = vm.createContext({
    document:{getElementById:id=>id === 'project-context-menu' ? menu : null},
    window:{innerWidth:1000,innerHeight:700}, tasksData:[],
    hideContextMenu(){},hideDepContextMenu(){},hideTooltip(){},
  });
  loadFunction(context,'showProjectContextMenu');
  context.showProjectContextMenu({clientX:980,clientY:680,preventDefault(){},stopPropagation(){}},42);
  assert.equal(menu.style.overflow,'visible');
  assert.equal(menu.style.overflowY,undefined);
  assert.ok(parseFloat(menu.style.left) + menu.offsetWidth <= 990);
  assert.ok(parseFloat(menu.style.top) + menu.offsetHeight <= 690);
});

test('CSV export starts one download per nonce without displaying a modal', () => {
  const source = read('app/presentation/components/csv_download.py');
  const js = source.match(/_DOWNLOAD_JS = """([\s\S]*?)"""/)[1];
  const clicks = [], released = [];
  const root = {dataset:{}, appendChild(){}};
  const parentElement = {querySelector:()=>root};
  const context = vm.createContext({
    Blob, URL: {createObjectURL:()=> 'blob:csv', revokeObjectURL:url=>released.push(url)},
    document: {createElement:()=>({click(){clicks.push(this.download);},remove(){}})},
    setTimeout:()=>1, clearTimeout(){},
  });
  vm.runInContext(js.replace('export default function', 'function mount'), context);
  const data = {nonce:'one',filename:'project_42_template.csv',content:'step_number,task_name\n'};
  const cleanup = context.mount({data,parentElement});
  context.mount({data,parentElement});
  assert.deepEqual(clicks,['project_42_template.csv']);
  cleanup();
  assert.deepEqual(released,['blob:csv']);
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
