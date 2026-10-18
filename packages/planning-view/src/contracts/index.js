/** Versioned, JSON-only host contracts. Validation never changes caller data. */
export const CONTRACT_VERSION = 1;

/** Safe contract failure: only schema paths, never supplied values. */
export class ContractError extends TypeError {
  /** @param {string} path Invalid schema location. */
  constructor(path) {
    super(`Invalid planning contract at ${path}`);
    this.name = 'ContractError';
  }
}

/** @param {boolean} valid Condition. @param {string} path Schema location. */
function requireValue(valid, path) {
  if (!valid) throw new ContractError(path);
}

/** @param {unknown} value Candidate. @param {string} path Schema location. */
function record(value, path) {
  requireValue(value !== null && typeof value === 'object' && !Array.isArray(value), path);
  requireValue(Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null, path);
  return value;
}

/** @param {unknown} value Candidate. @param {string} path Schema location. */
function identity(value, path) {
  requireValue(typeof value === 'string' && value.trim().length > 0, path);
  return value;
}

/** @param {unknown} value Candidate. @param {string} path Schema location. */
export function validateDate(value, path = 'date') {
  requireValue(typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && !value.startsWith('0000'), path);
  const time = Date.parse(value + 'T00:00:00Z');
  requireValue(Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value, path);
  return value;
}

/** @param {object} value Date-bearing record. @param {string} path Schema location. */
function range(value, path) {
  validateDate(value.start, path + '.start');
  validateDate(value.end, path + '.end');
  requireValue(value.start <= value.end, path + '.range');
}

/** @param {unknown} values Records. @param {string} path Schema location. */
function rows(values, path) {
  requireValue(Array.isArray(values), path);
  const ids = new Set();
  for (const value of values) {
    record(value, path);
    identity(value.id, path + '.id');
    requireValue(!ids.has(value.id), path + '.duplicateId');
    ids.add(value.id);
  }
  return values;
}

/** @param {unknown} values Task records. @param {string} path Schema location. */
function tasks(values, path) {
  const stableIds=new Set();
  for (const task of rows(values, path)) {
    identity(task.projectId, path + '.projectId');
    requireValue(typeof task.name === 'string', path + '.name');
    range(task, path);
    if (task.stableId !== undefined) identity(task.stableId, path + '.stableId');
    const pairing=JSON.stringify([task.projectId,task.stableId ?? task.id]);
    requireValue(!stableIds.has(pairing),path+'.duplicateStableId');stableIds.add(pairing);
    if (task.progress !== undefined) {
      requireValue(Number.isFinite(task.progress) && task.progress >= 0 && task.progress <= 100, path + '.progress');
    }
  }
}

/** @param {unknown} values Dependencies. @param {string} path Schema location. */
function dependencies(values, path) {
  for (const dependency of rows(values, path)) {
    requireValue(['FS', 'SS', 'FF', 'SF'].includes(dependency.type), path + '.type');
    for (const side of ['predecessor', 'successor']) {
      const endpoint = record(dependency[side], path + '.' + side);
      requireValue(['project', 'task', 'unavailable'].includes(endpoint.kind), path + '.kind');
      if (endpoint.kind !== 'unavailable') identity(endpoint.id, path + '.endpointId');
      if(endpoint.projectId!==undefined)identity(endpoint.projectId,path+'.projectId');
    }
    if (dependency.lagDays !== undefined) requireValue(Number.isInteger(dependency.lagDays), path + '.lagDays');
    for(const flag of ['violated','evaluable','external']) {
      if(dependency[flag]!==undefined)requireValue(typeof dependency[flag]==='boolean',path+'.'+flag);
    }
    if(dependency.diagnostics!==undefined) {
      requireValue(Array.isArray(dependency.diagnostics),path+'.diagnostics');
      requireValue(dependency.diagnostics.every(item=>typeof item==='string' || (item!==null && typeof item==='object' && typeof item.message==='string')),path+'.diagnostics');
    }
  }
}

/** @param {unknown} value Daily series. @param {string} path Schema location. */
function series(value, path) {
  record(value, path);
  for (const [day, amount] of Object.entries(value)) {
    validateDate(day, path + '.date');
    requireValue(Number.isFinite(amount) && amount >= 0, path + '.value');
  }
}

/** @param {unknown} values Resource records. @param {string} path Schema location. */
function resources(values, path) {
  for (const resource of rows(values, path)) {
    requireValue(typeof resource.name === 'string', path + '.name');
    requireValue(Number.isFinite(resource.capacity) && resource.capacity >= 0, path + '.capacity');
    for (const field of ['usage', 'selectedUsage', 'assignedCapacity']) {
      if (resource[field] !== undefined) series(resource[field], path + '.' + field);
    }
    if(resource.definedCapacity!==undefined)requireValue(Number.isFinite(resource.definedCapacity) && resource.definedCapacity>=0,path+'.definedCapacity');
    for(const flag of ['usedBySelection','hasAssignments'])if(resource[flag]!==undefined)requireValue(typeof resource[flag]==='boolean',path+'.'+flag);
    if(resource.comparisonUsage!==undefined) {
      record(resource.comparisonUsage,path+'.comparisonUsage');
      for(const scope of ['total','selected'])if(resource.comparisonUsage[scope]!==undefined)series(resource.comparisonUsage[scope],path+'.comparisonUsage.'+scope);
    }
  }
}

/** Validate iteratively: cycles and duplicate identities cannot recurse forever.
 * @param {unknown} value Resource hierarchy. @param {string} path Schema location.
 */
function hierarchy(value, path) {
  requireValue(Array.isArray(value), path);
  const pending = [...value], objects = new Set(), keys = new Set();
  while (pending.length) {
    const node = record(pending.pop(), path);
    identity(node.id, path + '.id');
    requireValue(!objects.has(node) && !keys.has(node.id), path + '.duplicateOrCycle');
    objects.add(node); keys.add(node.id);
    if (node.resourceId !== undefined) identity(node.resourceId, path + '.resourceId');
    if(node.name!==undefined)requireValue(typeof node.name==='string',path+'.name');
    if (node.children === undefined) continue;
    requireValue(Array.isArray(node.children), path + '.children');
    for (const child of node.children) pending.push(child);
  }
}

/** @param {object} value Message envelope. */
function envelope(value) {
  record(value, 'message');
  requireValue(value.version === CONTRACT_VERSION, 'version');
  identity(value.scope, 'scope');
  identity(value.revision, 'revision');
}

/** Reject non-JSON values and cycles without recursive traversal.
 * @param {unknown} input Candidate JSON data.
 */
function jsonData(input) {
  const pending = [[input, false]], active = new Set();
  while (pending.length) {
    const [value, leaving] = pending.pop();
    if (leaving) { active.delete(value); continue; }
    if (value === null || typeof value === 'string' || typeof value === 'boolean') continue;
    if (typeof value === 'number') { requireValue(Number.isFinite(value), 'json'); continue; }
    requireValue(typeof value === 'object', 'json');
    if (!Array.isArray(value)) record(value, 'json');
    requireValue(!active.has(value), 'json.cycle');
    active.add(value); pending.push([value, true]);
    for (const child of Object.values(value)) pending.push([child, false]);
  }
}

/** @param {object} value Data-bearing message. */
function data(value) {
  if(value.resourceFilter!==undefined && value.resourceFilter!==null) {
    const filter=record(value.resourceFilter,'resourceFilter');
    requireValue(filter.resourceId!==undefined || filter.groupId!==undefined,'resourceFilter.target');
    for(const field of ['resourceId','groupId','clearAction'])if(filter[field]!==undefined)identity(filter[field],'resourceFilter.'+field);
    if(filter.name!==undefined)requireValue(typeof filter.name==='string','resourceFilter.name');
    if(filter.start || filter.end)range(filter,'resourceFilter');
  }
  if (value.projects !== undefined) {
    for (const project of rows(value.projects, 'projects')) {
      requireValue(typeof project.name === 'string', 'projects.name');
      if(project.start!=null || project.end!=null)range(project,'projects');
      if(project.taskCount!==undefined)requireValue(Number.isSafeInteger(project.taskCount) && project.taskCount>=0,'projects.taskCount');
    }
  }
  if (value.tasks !== undefined) tasks(value.tasks, 'tasks');
  if (value.dependencies !== undefined) dependencies(value.dependencies, 'dependencies');
  if (value.resources !== undefined) resources(value.resources, 'resources');
  if (value.hierarchy !== undefined) hierarchy(value.hierarchy, 'hierarchy');
  if (value.overlays !== undefined) {
    for (const overlay of rows(value.overlays, 'overlays')) {
      requireValue(['baseline', 'alternative'].includes(overlay.kind), 'overlays.kind');
      identity(overlay.projectId, 'overlays.projectId');
      tasks(overlay.tasks, 'overlays.tasks');
      if (overlay.dependencies !== undefined) dependencies(overlay.dependencies, 'overlays.dependencies');
    }
  }
  for (const field of ['capabilities', 'labels']) {
    if (value[field] === undefined) continue;
    record(value[field], field);
    const expected = field === 'labels' ? 'string' : 'boolean';
    requireValue(Object.values(value[field]).every(item => typeof item === expected), field);
  }
}

/** Validate an update before state mutation; return an independently owned copy.
 * @param {unknown} input Snapshot, patch, or correlated response.
 * @returns {object} Validated update.
 * @throws {ContractError} Invalid input, with no caller state changes.
 */
export function validateMessage(input) {
  const value = record(input, 'message');
  envelope(value);
  requireValue(['snapshot', 'patch', 'response'].includes(value.kind), 'kind');
  data(value);
  jsonData(value);
  if (value.kind === 'snapshot') {
    rows(value.projects, 'projects');
    tasks(value.tasks, 'tasks');
    const projects = new Set(value.projects.map(project => project.id));
    requireValue(value.tasks.every(task => projects.has(task.projectId)), 'tasks.projectId');
  }
  if (value.kind === 'response') {
    identity(value.requestId, 'requestId');
    requireValue(typeof value.accepted === 'boolean', 'accepted');
    if (value.error !== undefined) requireValue(typeof value.error === 'string', 'error');
  }
  if (value.reset !== undefined) requireValue(typeof value.reset === 'boolean', 'reset');
  for (const field of ['replaceProjectIds', 'removeProjectIds', 'loadedProjectIds']) {
    if (value[field] === undefined) continue;
    requireValue(Array.isArray(value[field]), field);
    value[field].forEach(id => identity(id, field));
    requireValue(new Set(value[field]).size === value[field].length, field + '.duplicateId');
  }
  return structuredClone(value);
}

/** Validate a correlated display intention; business authorization stays in host.
 * @param {unknown} input Host event.
 * @returns {object} Independently owned event.
 */
export function validateEvent(input) {
  const value = record(input, 'event');
  envelope(value);
  jsonData(value);
  identity(value.requestId, 'requestId');
  requireValue(['dates', 'progress', 'task', 'dependency', 'select', 'command', 'load', 'error'].includes(value.type), 'event.type');
  if (['dates', 'progress', 'task', 'dependency', 'select'].includes(value.type)) identity(value.targetId, 'targetId');
  if (value.type === 'dates') range(value, 'event');
  if (value.type === 'progress') requireValue(Number.isFinite(value.progress) && value.progress >= 0 && value.progress <= 100, 'progress');
  if (value.type === 'command') identity(value.command, 'command');
  if (value.type === 'load') {
    requireValue(Array.isArray(value.projectIds), 'projectIds');
    value.projectIds.forEach(id => identity(id, 'projectIds'));
  }
  return structuredClone(value);
}
