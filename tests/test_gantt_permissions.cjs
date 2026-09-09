// UI behavior only; Python integration tests enforce the corresponding writes.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../app/presentation/assets/components/gantt/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function harness() {
  const nodes = new Map(), messages = [];
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {style: {}, closest() {return this;}});
    return nodes.get(id);
  };
  const context = vm.createContext({document: {getElementById: node},
    window: {innerWidth: 1200, innerHeight: 800},
    hideContextMenu() {}, hideProjectContextMenu() {}, hideDepContextMenu() {}, hideTooltip() {},
    hideResourceCellContextMenu() {}, confirm: () => true,
    Streamlit: {setComponentValue: message => messages.push(message)},
    tasksData: [], currentProjectId: 1, selectedContextMenuTask: null, selectedContextMenuProjectId: null,
  });
  const run = code => vm.runInContext(code, context);
  const load = (start, end) => run(script.slice(script.indexOf(start), script.indexOf(end)));
  load('    let editAllProjects =', '    let allProjectsData =');
  load('    function showContextMenu(', '    function showContextMenuById(');
  load('    function showProjectContextMenu(', '    function hideResourceCellContextMenu(');
  load('    function triggerManageTaskTags(', '    // TIMELINE RENDERER');
  load('    function triggerGoToResourcePoolDetails(', '    function triggerFilterResourcePool(');
  return {context, run, load, node, messages};
}

test('task and project menus default to read only and use the independent edit scope', () => {
  const h = harness();
  for (const permission of [undefined, {editable_projects: [1]}]) {
    h.context.updatePermissionControls(permission);
    for (const projectId of [1, 2]) {
      h.context.showContextMenu(null, {id: 10, project_id: projectId});
      h.context.showProjectContextMenu(null, projectId);
      const expected = permission && projectId === 1 ? '' : 'none';
      for (const id of ['ctx-label-add-step', 'ctx-label-edit-step', 'ctx-label-task-tags',
        'ctx-label-task-pools', 'ctx-label-complete-step', 'ctx-label-delete-step',
        'ctx-project-add-step', 'ctx-import-csv', 'ctx-label-project-tags', 'ctx-label-project-pools']) {
        assert.equal(h.node(id).style.display, expected, id);
      }
      assert.equal(h.node('ctx-export-csv').style.display, undefined);
      assert.equal(h.node('ctx-label-edit-project').style.display, undefined);
    }
  }
});

test('stale task actions stop emitting writes after edit permission changes', () => {
  const h = harness();
  h.context.selectedContextMenuTask = {id: 10, project_id: 1, name: 'Task'};
  h.context.selectedContextMenuProjectId = 1;
  const actions = ['triggerManageTaskTags', 'triggerManageTaskPools', 'markComplete',
    'deleteSelectedStep', 'triggerManageProjectTagsFromMenu', 'triggerManageProjectPoolsFromMenu'];
  h.context.updatePermissionControls({editable_projects: [1]});
  actions.forEach(action => h.context[action]());
  assert.equal(h.messages.length, actions.length);
  h.context.updatePermissionControls({editable_projects: [2]});
  actions.forEach(action => h.context[action]());
  assert.equal(h.messages.length, actions.length);
  h.context.triggerManageProjectTagsFromMenu('export_csv_template');
  h.context.triggerEditProjectFromMenu();
  assert.deepEqual(h.messages.slice(-2).map(item => item.action), ['export_csv_template', 'edit_project_details']);
});

test('dependency editing needs both projects and shared pool details need business administration', () => {
  const h = harness();
  h.context.updatePermissionControls({editable_projects: [1]});
  assert.equal(h.context.canEditDependency({predProjectId: 2, succProjectId: 1}), false);
  assert.equal(h.context.canEditDependency({predProjectId: 1, succProjectId: 1}), true);
  h.context.selectedResourceCellCtx = {pool_id: 1};
  h.context.triggerGoToResourcePoolDetails();
  assert.equal(h.messages.length, 0);
  h.context.triggerGoToResourcePoolDetails('show_pool_allocations');
  assert.equal(h.messages[0].action, 'show_pool_allocations');
  h.context.updatePermissionControls({edit_all: true, manage_shared: true});
  assert.equal(h.context.canEditDependency({predProjectId: 2, succProjectId: 1}), true);
  assert.equal(h.context.canEditTask({id: 10}), false);
  h.context.triggerGoToResourcePoolDetails();
  assert.equal(h.messages[1].action, 'go_to_pool_details');
});

test('read-only task bars hide resize handles and register no drag action', () => {
  const h = harness();
  h.load('    function bindDragEvents(', '    // Choice-only responses');
  const handles = [{style: {}}, {style: {}}], listeners = [];
  const element = {style: {}, querySelectorAll: () => handles,
    addEventListener: (name, callback) => listeners.push({name, callback})};
  h.context.bindDragEvents(element, {id: 10, project_id: 1}, false);
  assert.equal(element.style.cursor, 'default');
  assert.ok(handles.every(handle => handle.style.display === 'none'));
  assert.equal(listeners.length, 0);
  h.context.updatePermissionControls({editable_projects: [1]});
  h.context.bindDragEvents(element, {id: 10, project_id: 1}, false);
  assert.equal(listeners.length, 1);
  h.context.updatePermissionControls({});
  // A stale listener returns before consuming the event or touching task dates.
  listeners[0].callback({button: 0});
  assert.equal(h.messages.length, 0);
});
