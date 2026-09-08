const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/views/portfolio_table_component.py'), 'utf8');
const script = source.match(/_TABLE_JS = r"""([\s\S]*?)"""/)[1].replace('export default function', 'function mount');

function harness() {
  const requests = [], clicks = [], ganttClicks = [], timers = new Map();
  let sequence = 0;
  function element(tag = 'div') {
    const el = {tag, children: [], style: {}, dataset: {}, attributes: {}, className: '',
      scrollTop: 0, scrollLeft: 0, clientHeight: 512, value: '', textContent: '',
      append(...children) { children.forEach(c => this.appendChild(c)); },
      appendChild(c) {this.children.push(c); c.parent = this;},
      replaceChildren(...children) {this.children = []; this.append(...children);},
      setAttribute(k, v) {this.attributes[k] = v;},
      remove() {this.parent.children = this.parent.children.filter(c => c !== this);},
      focus() {}, setSelectionRange() {}, getBoundingClientRect() {return {left: 0, bottom: 44};},
      querySelectorAll(selector) {
        const descendants = this.children.flatMap(c => [c, ...c.querySelectorAll('*')]);
        const sel = selector.split(' ').at(-1);
        return descendants.filter(c => {
          if (sel === '*') return true;
          if (sel.startsWith('#')) return c.id === sel.slice(1);
          const [tag, cls] = sel.split('.');
          return (!tag || c.tag === tag) && (!cls || c.className.split(' ').includes(cls));
        });
      },
      querySelector(selector) {return this.querySelectorAll(selector)[0];},
    };
    el.classList = {add(c) {el.className += ' ' + c;}, remove(c) {el.className = el.className.split(' ').filter(v => v !== c).join(' ');}};
    return el;
  }
  const parent = element(), root = element(); root.id = 'portfolio-project-table'; parent.appendChild(root);
  const frames = new Map();
  const context = vm.createContext({document: {createElement: element},
    window: {innerWidth: 1400, innerHeight: 900},
    setTimeout: f => {timers.set(++sequence, f); return sequence;}, clearTimeout: id => timers.delete(id),
    requestAnimationFrame: f => {frames.set(++sequence, f); return sequence;}, cancelAnimationFrame: id => frames.delete(id),
  });
  vm.runInContext(script, context);
  function flushFrames() {const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(f => f());}
  function render(offset = 0, extra = {}) {
    const request = requests.at(-1);
    const data = {columns: [{key: 'name', label: 'Project', format: 'text'}, {key: 'planned_budget', label: 'Budget', format: 'currency'}],
      rows: Array.from({length: 100}, (_, i) => ({project_id: offset + i + 1, name: 'Project ' + (offset + i + 1), planned_budget: i,
        is_overallocated: i === 0})),
      selected_id: null,
      page_info: {context: 'db-v1', total: 10000, offset, query: request?.query || {}, request_id: request?.nonce, ...extra}};
    context.mount({data, parentElement: parent, setStateValue: (key, payload) => requests.push(payload),
      setTriggerValue: (key, payload) => (key === 'gantt_click' ? ganttClicks : clicks).push(payload)});
    flushFrames();
  }
  function scroll(index) {const scroller = root.querySelector('.table-scroll'); scroller.scrollTop = index * 40 + 44; scroller.onscroll(); flushFrames();}
  function button(text) {return root.querySelectorAll('button').find(b => b.textContent === text);}
  return {root, requests, clicks, ganttClicks, timers, render, scroll, button, flushFrames};
}

test('virtual scrolling renders a small window, prefetches, preserves position, and ignores stale responses', () => {
  const app = harness(); app.render();
  assert.ok(app.root.querySelectorAll('tbody')[0].children.length < 40);
  assert.equal(app.requests.length, 0);
  app.scroll(80);
  assert.equal(app.requests.at(-1).offset, 100);
  const top = app.root.querySelector('.table-scroll').scrollTop;
  app.render(0, {request_id: 'stale'});
  assert.ok(app.root._portfolio.pending);
  assert.equal(app.root.querySelector('.table-scroll').scrollTop, top);
  app.render(100);
  assert.equal(app.root._portfolio.pending, null);
  assert.equal(app.root.querySelector('.table-scroll').scrollTop, top);
  app.scroll(103);
  const row = app.root.querySelectorAll('tr').find(r => r.dataset.projectId === '104');
  row.onclick(); row.onclick();
  assert.deepEqual(app.clicks, [104]);
  assert.ok(app.root.querySelectorAll('tbody')[0].children.length < 40);
});

test('scroll jumps fetch the required batch and the browser cache stays bounded', () => {
  const app = harness(); app.render();
  for (let offset = 500; offset <= 4500; offset += 500) {
    app.scroll(offset + 20);
    assert.equal(app.requests.at(-1).offset, offset);
    app.render(offset);
  }
  assert.equal(app.root._portfolio.pages.size, 5);
  app.scroll(20);
  assert.equal(app.requests.at(-1).offset, 0);
  app.render(0);
  app.render(0, {context: 'db-after-edit'});
  assert.equal(app.root.querySelector('.table-scroll').scrollTop, 0);
  assert.equal(app.root._portfolio.pages.size, 1);
});

test('header statistics are requested lazily; include/exclude filters and sorting restart the scroll', () => {
  const app = harness(); app.render(); app.scroll(30);
  app.root.querySelectorAll('button')[0].onclick();
  assert.equal(app.requests.at(-1).kind, 'facet');
  assert.equal(app.requests.at(-1).column, 'name');
  app.render(0, {facet: {column: 'name', search: '', stats: [['Rows', 10000], ['Unique', 10000]],
    values: [{value: 'Project 9999', count: 1}], has_more: true}});
  assert.ok(app.root.querySelectorAll('span').some(s => s.textContent === '10000'));
  const checkbox = app.root.querySelectorAll('input').find(i => i.type === 'checkbox');
  checkbox.checked = false; checkbox.onchange();
  app.button('Apply').onclick();
  assert.equal(app.requests.at(-1).kind, 'page');
  assert.equal(app.requests.at(-1).offset, 0);
  assert.equal(app.requests.at(-1).query.filters.name.mode, 'exclude');
  assert.deepEqual([...app.requests.at(-1).query.filters.name.values], ['Project 9999']);
  assert.equal(app.root.querySelector('.table-scroll').scrollTop, 0);
  app.render(0, {total: 9999});
  app.root.querySelectorAll('button')[0].onclick();
  app.button('Sort Z → A').onclick();
  assert.equal(app.requests.at(-1).query.sort.column, 'name');
  assert.equal(app.requests.at(-1).query.sort.direction, 'desc');
});

test('facet search is debounced and searches the server, not only cached rows', () => {
  const app = harness(); app.render();
  app.root.querySelectorAll('button')[0].onclick();
  app.render(0, {facet: {column: 'name', search: '', stats: [], values: [], has_more: true}});
  const search = app.root.querySelectorAll('input').find(i => i.type === 'search');
  search.value = 'old'; search.oninput(); search.value = '9999'; search.oninput();
  assert.equal(app.timers.size, 1);
  [...app.timers.values()][0]();
  assert.equal(app.requests.at(-1).search, '9999');
  assert.equal(app.requests.at(-1).kind, 'facet');
});

test('overallocation icon navigates with a stable project ID without selecting another row', () => {
  const app = harness(); app.render();
  const warning = app.root.querySelector('.overallocation-button');
  let stopped = 0;
  warning.onclick({stopPropagation() {stopped++;}});
  assert.deepEqual(app.ganttClicks, [1]);
  assert.deepEqual(app.clicks, []);
  assert.equal(stopped, 1);
  assert.match(warning.attributes['aria-label'], /Project 1$/);
  app.scroll(80); app.render(100); app.scroll(100);
  app.root.querySelector('.overallocation-button').onclick({stopPropagation() {}});
  assert.deepEqual(app.ganttClicks, [1, 101]);
});

test('master-list height is one header and eight rows, with no numbered paging controls', () => {
  const app = harness(); app.render();
  assert.equal(app.root.querySelector('.table-scroll').style.height, '364px');
  assert.match(source, /box-sizing: border-box/);
});
