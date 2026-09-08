const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../app/presentation/assets/components/task_tag_table/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function harness() {
  const elements = new Map(), messages = [], timers = new Map();
  let receive, timerId = 0;
  function element() {
    return {style: {}, dataset: {}, value: '', children: [], scrollHeight: 300,
      classList: {add() {}, remove() {}, toggle() {}}, addEventListener() {},
      appendChild(child) { this.children.push(child); },
      set innerHTML(value) { this.children = []; }};
  }
  const document = {getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    createElement: element, addEventListener() {}, querySelectorAll: () => [], body: element()};
  const context = vm.createContext({document,
    window: {parent: {postMessage: message => messages.push(message)}, addEventListener: (name, cb) => {if (name === 'message') receive = cb;}},
    setTimeout: callback => {timers.set(++timerId, callback); return timerId;}, clearTimeout: id => timers.delete(id),
  });
  vm.runInContext(script, context);
  const rows = Array.from({length: 100}, (_, index) => ({id: index + 1, task_id: index + 1, task_name: 'Task'}));
  function render(extra = {}) {
    receive({data: {type: 'streamlit:render', args: {task_tags: rows,
      page_info: {page: 1, pages: 740, total: 73950, filtered_total: 73950}, ...extra}}});
  }
  return {run: code => vm.runInContext(code, context), messages, timers, render, elements};
}

test('large totals render only the supplied page and wait for the matching response', () => {
  const app = harness();
  app.render();
  assert.equal(app.elements.get('table-body').children.length, 100);
  assert.equal(app.elements.get('stat-count').innerText, 73950);
  app.run('changePage(1)');
  const event = app.messages.at(-1).value;
  assert.equal(event.action, 'query_task_tags');
  assert.equal(event.query.page, 2);
  app.render({query_nonce: 'stale'});
  assert.equal(app.run('queryPending'), true);
  app.render({query_nonce: event.nonce, page_info: {page: 2, pages: 740, total: 73950, filtered_total: 73950}});
  assert.equal(app.run('queryPending'), false);
  assert.equal(app.elements.get('table-body').children.length, 100);
});

test('typing is debounced and filters/sorting request the first page from the server', () => {
  const app = harness();
  app.render();
  app.run("globalSearchQuery = 'first'; requestPage(1, true)");
  app.run("globalSearchQuery = 'latest'; colFilters.free_tag = 'Rare'; requestPage(1, true)");
  assert.equal(app.timers.size, 1);
  [...app.timers.values()][0]();
  const event = app.messages.at(-1).value;
  assert.equal(event.query.search, 'latest');
  assert.equal(event.query.filters.free_tag, 'Rare');
  assert.equal(event.query.page, 1);
  app.render({query_nonce: event.nonce});
  app.run("handleSort('task_name')");
  assert.equal(app.messages.at(-1).value.query.sort, 'task_name');
  assert.equal(app.messages.at(-1).value.query.ascending, true);
});
