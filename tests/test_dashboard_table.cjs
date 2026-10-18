const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app/presentation/components/dashboard_table.py'), 'utf8');
const script = source.match(/_JS = r"""([\s\S]*?)"""/)[1].replace('export default function', 'function mount');

function setup() {
  function element() {
    return {children: [], dataset: {}, style: {}, scrollTop: 0,
      appendChild(child) {this.children.push(child);},
      append(...children) {this.children.push(...children);},
      replaceChildren(...children) {this.children = children;},
      setAttribute() {}};
  }
  const root = element(), events = [];
  let sequence = 0;
  const context = vm.createContext({document: {createElement: element},
    crypto: {randomUUID: () => 'event-' + ++sequence}});
  vm.runInContext(script, context);
  context.mount({parentElement: {querySelector: () => root},
    setTriggerValue: (key, value) => events.push({key, ...value}),
    data: {token: 'page-snapshot', selection_token: 'active-filters', offset: 0,
      total: 1, rows: [{id: 7, values: ['Project', '', '', '']}],
      columns: ['Project'], selected: null}});
  return {row: root.children[0].children[1].children[0], events};
}

test('repeated row activations remain distinct before the component rerenders', () => {
  const {row, events} = setup();
  row.onclick();
  row.onkeydown({key: 'Enter', preventDefault() {}});
  assert.equal(events.length, 2);
  assert.equal(events[0].id, 7);
  assert.equal(events[1].id, 7);
  assert.equal(typeof events[0].nonce, 'string');
  assert.notEqual(events[0].nonce, events[1].nonce);
});

test('selection uses the active filter token rather than the selected page token', () => {
  const {row, events} = setup();
  row.onclick();
  assert.equal(events[0].token, 'active-filters');
});
