const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app/presentation/components/portfolio_table.py'), 'utf8');
const script = source.match(/_TABLE_JS = r"""([\s\S]*?)"""/)[1].replace('export default function', 'function mount');

function harness({deferredBadges = false} = {}) {
  const requests = [], clicks = [], ganttClicks = [], timers = new Map(), listeners = new Map();
  const badgeRequests = [];
  let cleanup;
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
  const context = vm.createContext({AbortController,
    fetch: (url, options) => new Promise((resolve, reject) => {
      badgeRequests.push({url, options, resolve, reject});
      options.signal.addEventListener('abort', () => reject(Object.assign(new Error(), {name: 'AbortError'})));
    }),
    document: {createElement: element,
    addEventListener(type, handler) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(handler);
    },
    removeEventListener(type, handler) {listeners.get(type)?.delete(handler);}},
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
        is_overallocated: deferredBadges ? undefined : i === 0})),
      selected_id: null,
      page_info: {context: 'db-v1', total: 10000, offset, query: request?.query || {}, request_id: request?.nonce,
        ...(deferredBadges ? {allocation_endpoint: '/api/portfolio/allocations', revision: 'revision-1'} : {}), ...extra}};
    cleanup?.();
    cleanup = context.mount({data, parentElement: parent, setStateValue: (key, payload) => requests.push(payload),
      setTriggerValue: (key, payload) => (key === 'gantt_click' ? ganttClicks : clicks).push(payload)});
    flushFrames();
  }
  function scroll(index) {const scroller = root.querySelector('.table-scroll'); scroller.scrollTop = index * 40 + 44; scroller.onscroll(); flushFrames();}
  function button(text) {return root.querySelectorAll('button').find(b => b.textContent === text);}
  const dispatch = (type, event) => [...(listeners.get(type) || [])].forEach(handler => handler(event));
  return {root, requests, clicks, ganttClicks, timers, badgeRequests, render, scroll, button, flushFrames,
    dispatch, listeners, unmount: () => cleanup?.()};
}

test('header filters dismiss outside the shadow root without applying drafts or reopening on late responses', () => {
  const app = harness(); app.render();
  app.root.querySelector('.filter-button').onclick();
  const menu = app.root.querySelector('.filter-menu');
  const search = menu.querySelector('input');
  // Document listeners see the shadow host as target, but the composed path includes the menu.
  app.dispatch('pointerdown', {target: {}, composedPath: () => [search, menu, app.root]});
  assert.equal(app.root.querySelector('.filter-menu'), menu);
  search.value = 'pending search'; search.oninput();
  assert.equal(app.timers.size, 1);
  app.dispatch('pointerdown', {composedPath: () => [{}]});
  assert.equal(app.root.querySelector('.filter-menu'), undefined);
  assert.equal(app.root._portfolio.menu, null);
  assert.equal(app.timers.size, 0);
  assert.equal(app.requests.length, 1);
  assert.equal(app.root._portfolio.query.filters, undefined);
  app.render(0, {facet: {column:'name', search:'', stats:[], values:[]}});
  assert.equal(app.root.querySelector('.filter-menu'), undefined);
  assert.equal(app.listeners.get('pointerdown').size, 1);
  app.root.querySelector('.filter-button').onclick();
  app.render(0, {request_id:'stale'});
  app.dispatch('keydown', {key:'Escape'});
  assert.equal(app.root.querySelector('.filter-menu'), undefined);
  app.unmount();
  assert.equal(app.listeners.get('pointerdown').size, 0);
  assert.equal(app.listeners.get('keydown').size, 0);
});

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

test('a saved project refresh retains scroll while a changed filter resets it', () => {
  const app = harness(); app.render(); app.scroll(20);
  app.render(0, {context: 'saved-revision', preserve_position: true});
  assert.equal(app.root.querySelector('.table-scroll').scrollTop, 844);
  assert.equal(app.root._portfolio.context, 'saved-revision');
  app.render(0, {context: 'filtered-revision'});
  assert.equal(app.root.querySelector('.table-scroll').scrollTop, 0);
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

test('overallocation is an indicator and navigation uses the project context menu', () => {
  const app = harness(); app.render();
  const warning = app.root.querySelector('.overallocation-indicator');
  assert.equal(warning.onclick, undefined);
  assert.equal(warning.tag, 'span');
  let stopped = 0;
  app.root.querySelector('.project-menu-button').onclick({preventDefault() {}, stopPropagation() {stopped++;}});
  assert.deepEqual(app.ganttClicks, []);
  app.button('View resource overallocation in Gantt').onclick({stopPropagation() {stopped++;}});
  assert.deepEqual(app.ganttClicks, [1]);
  assert.deepEqual(app.clicks, []);
  assert.equal(stopped, 2);
  app.scroll(80); app.render(100); app.scroll(100);
  const row = app.root.querySelectorAll('tr').find(r => r.dataset.projectId === '101');
  row.oncontextmenu({preventDefault() {}, stopPropagation() {}});
  app.button('View resource overallocation in Gantt').onclick({stopPropagation() {}});
  assert.deepEqual(app.ganttClicks, [1, 101]);
  const ordinaryRow = app.root.querySelectorAll('tr').find(r => r.dataset.projectId === '102');
  ordinaryRow.onkeydown({key: 'F10', shiftKey: true, preventDefault() {}, stopPropagation() {}});
  assert.equal(app.button('View resource overallocation in Gantt'), undefined);
  assert.ok(app.button('Open project details'));
  app.root.onkeydown({key: 'Escape'});
  assert.equal(app.root.querySelector('.project-context-menu'), undefined);
});

test('a distant boundary jump loads visible rows before the preceding overscan page', () => {
  const app = harness(); app.render();
  app.scroll(5000);
  assert.equal(app.requests.at(-1).offset, 5000);
  app.render(5000);
  assert.ok(app.root.querySelectorAll('tr').some(row => row.dataset.projectId === '5001'));
  assert.equal(app.root.querySelector('.table-scroll').scrollTop, 5000 * 40 + 44);
  assert.equal(app.requests.at(-1).offset, 4900);
});

test('opening details from a context menu highlights that project without rerunning the grid', () => {
  const app = harness(); app.render();
  const row = app.root.querySelectorAll('tr').find(item => item.dataset.projectId === '2');
  row.oncontextmenu({preventDefault() {}, stopPropagation() {}});
  app.button('Open project details').onclick({stopPropagation() {}});
  assert.deepEqual(app.clicks, [2]);
  assert.equal(app.root._portfolio.selected, 2);
  assert.equal(app.root.querySelector('tr.selected').dataset.projectId, '2');
  assert.equal(app.requests.length, 0);
});

test('master-list height is one header and eight rows, with no numbered paging controls', () => {
  const app = harness(); app.render();
  assert.equal(app.root.querySelector('.table-scroll').style.height, '364px');
  assert.match(source, /box-sizing: border-box/);
});

const settle = () => new Promise(resolve => setImmediate(resolve));
function deliverBadges(request, overloaded = [], extra = {}) {
  const body = JSON.parse(request.options.body);
  request.resolve({ok: true, json: async () => ({...body, overallocated: overloaded, ...extra})});
}

test('rows render immediately and deferred warnings update without a Streamlit request or scrollbar replacement', async () => {
  const app = harness({deferredBadges: true}); app.render();
  const scroll = app.root.querySelector('.table-scroll');
  assert.ok(app.root.querySelectorAll('tr').some(row => row.dataset.projectId === '1'));
  assert.equal(app.root.querySelector('.loading-row'), undefined);
  assert.equal(app.root.querySelector('.overallocation-indicator'), undefined);
  const request = app.badgeRequests[0];
  assert.equal(JSON.parse(request.options.body).project_ids.length, 25);
  assert.equal(request.options.credentials, 'same-origin');
  deliverBadges(request, [1]); await settle();
  assert.ok(app.root.querySelector('.overallocation-indicator'));
  assert.equal(app.requests.length, 0);
  app.render();
  assert.equal(app.root.querySelector('.table-scroll'), scroll);
  assert.ok(app.root.querySelector('.overallocation-indicator'));
  assert.equal(app.badgeRequests.length, 1);
});

test('rapid paging keeps badge work bounded and applies late badges only to the current rows and scope', async () => {
  const app = harness({deferredBadges: true}); app.render();
  const first = app.badgeRequests[0];
  app.scroll(5020); app.render(5000);
  assert.equal(app.badgeRequests.length, 1);
  deliverBadges(first, [1]); await settle();
  assert.equal(app.root.querySelector('.overallocation-indicator'), undefined);
  const current = app.badgeRequests[1];
  assert.equal(JSON.parse(current.options.body).project_ids[0], 5021);
  app.render(0, {context: 'new-scope'});
  assert.equal(current.options.signal.aborted, true);
  deliverBadges(current, [5021]); await settle();
  assert.equal(app.root.querySelector('.overallocation-indicator'), undefined);
  assert.equal(app.root._portfolio.badgeError, undefined);
  deliverBadges(app.badgeRequests.at(-1), []); await settle();
  assert.equal(app.root._portfolio.badgePending, null);
});

test('badge failures do not freeze rows or retry endlessly, and retries retain scroll position', async () => {
  const app = harness({deferredBadges: true}); app.render();
  app.badgeRequests[0].resolve({ok: false, status: 503}); await settle();
  assert.ok(app.button('Retry allocation warnings'));
  assert.equal(app.badgeRequests.length, 1);
  app.scroll(20);
  assert.equal(app.badgeRequests.length, 1);
  app.button('Retry allocation warnings').onclick();
  assert.equal(app.badgeRequests.length, 2);
  deliverBadges(app.badgeRequests[1], [21]); await settle();
  assert.equal(app.root.querySelector('.table-scroll').scrollTop, 844);
  assert.equal(app.button('Retry allocation warnings'), undefined);
  assert.ok(app.root.querySelector('.overallocation-indicator'));
});

test('malformed badge responses cannot mark rows clear and changed revisions require explicit refresh', async () => {
  const app = harness({deferredBadges: true}); app.render();
  deliverBadges(app.badgeRequests[0], [], {nonce: 'stale'}); await settle();
  assert.equal(app.root._portfolio.pages.get(0)[0].is_overallocated, undefined);
  app.button('Retry allocation warnings').onclick();
  app.badgeRequests[1].resolve({ok: false, status: 409}); await settle();
  assert.equal(app.requests.length, 0);
  app.button('Refresh project list').onclick();
  assert.equal(app.requests.length, 1);
  assert.equal(app.requests[0].kind, 'page');
});

test('a stalled badge request times out without blocking scrolling or automatically retrying', async () => {
  const app = harness({deferredBadges: true}); app.render();
  [...app.timers.values()].forEach(callback => callback());
  await settle();
  assert.equal(app.root._portfolio.badgePending, null);
  assert.equal(app.timers.size, 0);
  assert.equal(app.badgeRequests.length, 1);
  assert.ok(app.button('Retry allocation warnings'));
  app.scroll(5020);
  assert.equal(app.requests.at(-1).offset, 5000);
});
