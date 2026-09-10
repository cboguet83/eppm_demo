const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app/presentation/components/modal_form.py'), 'utf8');
const script = source.match(/_JS = r"""([\s\S]*?)"""/)[1].replace('export default function', 'function mount');

function fixture() {
  function element(tag) {
    return {tag, children: [], attributes: {}, open: false, value: '',
      appendChild(child) {this.children.push(child);},
      append(...children) {this.children.push(...children);},
      replaceChildren() {this.children = [];},
      setAttribute(key, value) {this.attributes[key] = value;},
      showModal() {assert.equal(this.children[1].tag, 'form'); assert.ok(this.children[1].children.length); this.open = true; this.shows = (this.shows || 0) + 1;},
      close() {this.open = false;},
      getBoundingClientRect() {return {left: 10, right: 500, top: 10, bottom: 400};},
      set innerHTML(value) {throw Error('Unsafe HTML assignment');}};
  }
  const dialog = element('dialog'), events = [];
  const context = vm.createContext({document: {createElement: element}});
  vm.runInContext(script, context);
  const mount = data => context.mount({data, parentElement: {querySelector: () => dialog},
    setTriggerValue: (key, value) => events.push(JSON.parse(JSON.stringify({key, ...value})))});
  const data = {title: '<img onerror=alert(1)>', submit: 'Save', cancel: 'Cancel', error: '', values: {title: 'First\nSecond', role: '1'},
    fields: [{key: 'title', label: 'Description', kind: 'textarea'},
      {key: 'role', label: 'Role', kind: 'select', options: [['1', '<script>']], disabled: true}]};
  return {dialog, events, mount, data};
}

test('modal contains complete safely rendered fields before opening', () => {
  const {dialog, mount, data} = fixture();
  mount(data);
  assert.equal(dialog.shows, 1);
  assert.equal(dialog.children[0].textContent, '<img onerror=alert(1)>');
  const labels = dialog.children[1].children[0].children;
  assert.equal(labels[0].children[1].value, 'First\nSecond');
  assert.equal(labels[0].children[1].attributes['aria-label'], 'Description');
  assert.equal(labels[1].children[1].children[0].textContent, '<script>');
  assert.equal(labels[1].children[1].disabled, true);
});

test('save submits once and remains open until the server acknowledges success', () => {
  const {dialog, events, mount, data} = fixture();
  mount(data);
  const form = dialog.children[1];
  form.onsubmit({preventDefault() {}});
  form.onsubmit({preventDefault() {}});
  dialog.oncancel({preventDefault() {}});
  assert.equal(events.length, 1);
  assert.deepEqual(events[0], {key: 'action', kind: 'save', values: {title: 'First\nSecond', role: '1'}});
  assert.equal(dialog.open, true);
  assert.equal(form.attributes['aria-busy'], 'true');
  mount(null);
  assert.equal(dialog.open, false);
});

test('validation retry retains values and reenables submission without reopening', () => {
  const {dialog, events, mount, data} = fixture();
  mount(data);
  dialog.children[1].onsubmit({preventDefault() {}});
  mount({...data, values: {...data.values, title: 'Retained'}, error: 'Title is required.'});
  assert.equal(dialog.shows, 1);
  const form = dialog.children[1];
  assert.equal(form.children[0].children[0].children[1].value, 'Retained');
  assert.equal(form.children[1].attributes.role, 'alert');
  assert.equal(form.children[1].textContent, 'Title is required.');
  form.onsubmit({preventDefault() {}});
  assert.equal(events.length, 2);
  assert.equal(events[1].values.title, 'Retained');
});

test('cancel, Escape and backdrop dismiss without submitting values', () => {
  for (const action of ['button', 'escape', 'backdrop']) {
    const {dialog, events, mount, data} = fixture();
    mount(data);
    if (action === 'button') dialog.children[1].children[1].children[0].onclick();
    if (action === 'escape') dialog.oncancel({preventDefault() {}});
    if (action === 'backdrop') dialog.onclick({target: dialog, clientX: 0, clientY: 0});
    assert.equal(dialog.open, false);
    assert.deepEqual(events, [{key: 'action', kind: 'cancel'}]);
  }
});
