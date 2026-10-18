// Non-Gantt component characterizations remain local. Planning assertions use
// imported owners plus mounted EPPM menu/tooltip/keyboard browser checks.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const read=name=>fs.readFileSync(path.join(__dirname,'..',name),'utf8');
void import('../packages/planning-view/tests/models.test.js');
void import('../packages/planning-view/tests/actions.test.js');
require('./test_eppm_planning_adapter.cjs');

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
