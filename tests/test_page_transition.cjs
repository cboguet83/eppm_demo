const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname,
  '../app/presentation/components/page_transition.py'), 'utf8');
const script = source.match(/_JS = """([\s\S]*?)"""/)[1]
  .replace('export default function', 'function mount');

function transition() {
  let state = 'notRunning', token = 'original', skeleton = false, observer;
  let nextFrame = 0;
  const frames = new Map(), listeners = new Map(), classes = new Set();
  const overlay = {style: {}, setAttribute() {}, remove() {}};
  const doc = {
    body: {append() {}, classList: {
      add: value => classes.add(value), remove: value => classes.delete(value),
    }},
    createElement: () => overlay,
    querySelector: selector => {
      if (selector === '[data-testid="stApp"]') return {getAttribute: () => state};
      if (selector === '[data-eppm-page-rendered]') return {getAttribute: () => token};
      if (selector === '[data-testid="stMain"]') return {getBoundingClientRect: () => ({left: 0, top: 0})};
      return skeleton ? {} : null;
    },
    addEventListener: (name, action) => listeners.set(name, action),
    removeEventListener: name => listeners.delete(name),
  };
  const context = vm.createContext({
    requestAnimationFrame: callback => {frames.set(++nextFrame, callback); return nextFrame;},
    cancelAnimationFrame: id => frames.delete(id),
    MutationObserver: class {
      constructor(callback) {observer = callback;}
      observe() {}
      disconnect() {}
    },
  });
  vm.runInContext(script, context);
  const cleanup = context.mount({parentElement: {ownerDocument: doc}});
  return {
    start: () => listeners.get('eppm-navigation-start')(),
    update: values => {
      state = values.state ?? state;
      token = values.token ?? token;
      skeleton = values.skeleton ?? skeleton;
      observer();
    },
    frame: () => {
      const pending = [...frames.values()];
      frames.clear();
      for (const callback of pending) callback();
    },
    loading: () => classes.has('eppm-page-loading'), cleanup,
  };
}

test('idle old content and unrelated DOM changes never release navigation', () => {
  const ui = transition();
  ui.start();
  ui.update({});
  ui.frame(); ui.frame();
  assert.equal(ui.loading(), true);
});

test('a new rendered page releases coalesced navigation only when idle and complete', () => {
  const ui = transition();
  ui.start();
  ui.update({token: 'destination', skeleton: true});
  ui.frame(); ui.frame();
  assert.equal(ui.loading(), true);
  ui.update({skeleton: false});
  ui.frame();
  ui.update({state: 'running'});
  ui.frame();
  assert.equal(ui.loading(), true);
  ui.update({state: 'notRunning'});
  ui.frame();
  assert.equal(ui.loading(), true);
  ui.frame();
  assert.equal(ui.loading(), false);
});

test('observed fragment completion still reveals a response without a new page marker', () => {
  const ui = transition();
  ui.start();
  ui.update({state: 'running'});
  ui.update({state: 'notRunning'});
  ui.frame(); ui.frame();
  assert.equal(ui.loading(), false);
});

test('a pending reveal cannot clear a newer navigation', () => {
  const ui = transition();
  ui.start();
  ui.update({token: 'first'});
  ui.frame();
  ui.start();
  ui.frame();
  assert.equal(ui.loading(), true);
  ui.update({token: 'second'});
  ui.frame(); ui.frame();
  assert.equal(ui.loading(), false);
});
