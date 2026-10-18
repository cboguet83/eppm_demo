/** Instance-owned validated snapshots, indexes, and interaction state. */
import {ContractError,validateMessage} from '../contracts/index.js';

const COLLECTIONS=Object.freeze(['projects','tasks','dependencies','resources','overlays']);

/** Freeze a validated JSON graph iteratively; unchanged frozen records are reused.
 * @param {object} root Owned JSON data. @returns {object} Frozen data.
 */
function freeze(root) {
  const pending=[root];
  while(pending.length) {
    const node=pending.pop();
    if(node===null || typeof node!=='object' || Object.isFrozen(node)) continue;
    for(const child of Object.values(node)) pending.push(child);
    Object.freeze(node);
  }
  return root;
}

/** @param {object[]} original Old records. @param {object[]} changes Upsert records. @param {Set<string>} removed Removed IDs. */
function merge(original,changes=[],removed=new Set()) {
  const records=new Map(original.filter(row=>!removed.has(row.id)).map(row=>[row.id,row]));
  for(const row of changes) records.set(row.id,row);
  return [...records.values()];
}

/** @param {object} snapshot Validated initial snapshot. */
function complete(snapshot) {
  const result={dependencies:[],resources:[],hierarchy:[],overlays:[],capabilities:{},labels:{},...snapshot};
  result.loadedProjectIds=snapshot.loadedProjectIds ?? snapshot.projects.map(project=>project.id);
  return result;
}

/** @returns {object} Default interaction state for a new view scope. */
function initialView() {
  return {scrollTop:0,scrollLeft:0,mode:'Quarter',expandedProjects:[],collapsedResources:[],
    selection:null,draft:null,preview:null,pendingRequestId:null,error:null,filters:{}};
}

/** @param {object} value Candidate. @param {string} field Unique identifier list. */
function ids(value,field) {
  const list=value[field] ?? [];
  if(!Array.isArray(list) || list.some(id=>typeof id!=='string' || !id.trim()) || new Set(list).size!==list.length) {
    throw new ContractError(field);
  }
  return new Set(list);
}

/** Build complete next data without modifying or cloning unchanged records.
 * @param {object} previous Frozen snapshot. @param {object} patch Validated patch.
 */
function patchData(previous,patch) {
  const replaced=ids(patch,'replaceProjectIds'),removed=ids(patch,'removeProjectIds');
  const evicted=ids(patch,'evictProjectIds'),removeTasks=ids(patch,'removeTaskIds');
  const unloaded=new Set([...removed,...replaced,...evicted]);
  for(const task of previous.tasks) if(unloaded.has(task.projectId)) removeTasks.add(task.id);
  const owner=new Map(previous.tasks.map(task=>[task.id,task.projectId]));
  const removeDependencies=ids(patch,'removeDependencyIds');
  for(const dependency of previous.dependencies) {
    const successor=dependency.successor;
    const project=successor.kind==='project'?successor.id:owner.get(successor.id);
    if(unloaded.has(project) || removeTasks.has(successor.id)) removeDependencies.add(dependency.id);
  }
  const result={...previous,revision:patch.revision,
    projects:merge(previous.projects,patch.projects,removed),
    tasks:merge(previous.tasks,patch.tasks,removeTasks),
    dependencies:merge(previous.dependencies,patch.dependencies,removeDependencies),
    resources:merge(previous.resources,patch.resources,ids(patch,'removeResourceIds'))};
  result.overlays=previous.overlays.filter(row=>!removed.has(row.projectId));
  for(const field of ['hierarchy','overlays','capabilities','labels']) {
    if(patch[field]!==undefined) result[field]=patch[field];
  }
  result.loadedProjectIds=patch.loadedProjectIds ?? previous.loadedProjectIds.filter(id=>!removed.has(id) && !evicted.has(id));
  return result;
}

/** @param {object} data Snapshot. @returns {object} Private collection indexes. */
function buildIndexes(data) {
  return Object.fromEntries(COLLECTIONS.map(field=>[field,new Map(data[field].map(row=>[row.id,row]))]));
}

/** Check relationships after joining individually validated old/new records.
 * @param {object} data Reconciled snapshot; avoids recloning unchanged series.
 */
function membership(data) {
  const projects=new Set(data.projects.map(project=>project.id));
  if(data.loadedProjectIds.some(id=>!projects.has(id))) throw new ContractError('loadedProjectIds');
  if(data.tasks.some(task=>!projects.has(task.projectId))) throw new ContractError('tasks.projectId');
  for(const overlay of data.overlays) {
    if(!projects.has(overlay.projectId) || overlay.tasks.some(task=>task.projectId!==overlay.projectId)) {
      throw new ContractError('overlays.projectId');
    }
  }
}

/** @param {object} view Interaction state. */
function validateView(view) {
  for(const field of ['scrollTop','scrollLeft']) {
    if(!Number.isFinite(view[field]) || view[field]<0) throw new ContractError('view.'+field);
  }
  if(!['Day','Week','Month','Quarter','Year'].includes(view.mode)) throw new ContractError('view.mode');
  if(!view.filters || typeof view.filters!=='object' || Array.isArray(view.filters)) throw new ContractError('view.filters');
  for(const field of ['pendingRequestId','error']) {
    if(view[field]!==null && typeof view[field]!=='string') throw new ContractError('view.'+field);
  }
  ids(view,'expandedProjects'); ids(view,'collapsedResources');
  for(const field of ['selection','draft']) {
    const value=view[field];
    if(value===null) continue;
    if(!value || !COLLECTIONS.includes(value.kind) || typeof value.id!=='string') throw new ContractError('view.'+field);
  }
}

/** Create an isolated store; observers are given a change reason, never mutable maps.
 * @param {object} input Initial versioned snapshot.
 * @returns {object} Read, indexed lookup, update, view, subscribe, and destroy seam.
 */
export function createPlanningStore(input) {
  const validated=validateMessage(input);
  if(validated.kind!=='snapshot') throw new ContractError('initialSnapshot');
  let data=freeze(complete(validated)),indexes=buildIndexes(data),view=freeze(initialView()),disposed=false;
  membership(data);
  const listeners=new Set();
  const notify=type=>{for(const listener of listeners) listener(type);};
  const exists=target=>target===null || indexes[target.kind]?.has(target.id);
  /** @param {object} message Authoritative snapshot, patch or correlated response. */
  const update=message=>{
    if(disposed) return false;
    const next=validateMessage(message);
    if(next.kind!=='snapshot' && next.scope!==data.scope) return false;
    if(next.kind==='response' && next.requestId!==view.pendingRequestId) return false;
    if(next.kind!=='snapshot' && next.revision!==data.revision && next.baseRevision!==data.revision) return false;
    const changedScope=next.scope!==data.scope;
    const candidate=next.kind==='snapshot'?complete(next):patchData(data,next);
    // Each changed record was validated above. Check resulting relationships
    // without walking/cloning every unchanged daily series on each task patch.
    membership(candidate);
    const nextIndexes=buildIndexes(candidate);
    let nextView=changedScope || next.reset?initialView():{...view};
    const target=nextView.draft;
    if(target && !nextIndexes[target.kind].has(target.id)) {
      nextView.draft=null;nextView.error='The edited item is no longer available.';
    }
    if(nextView.selection && !nextIndexes[nextView.selection.kind].has(nextView.selection.id)) nextView.selection=null;
    if(next.kind==='response') {
      nextView.pendingRequestId=null;nextView.preview=null;
      nextView.error=next.accepted?null:(next.error || 'The requested change was rejected.');
      if(next.accepted) nextView.draft=null;
    }
    data=freeze(candidate);indexes=nextIndexes;view=freeze(nextView);
    notify('data');
    return true;
  };
  return {
    read(){if(disposed) throw new ContractError('disposed');return {data,view};},
    lookup(kind,id){return indexes[kind]?.get?.(id);},
    update,
    setView(patch){
      if(disposed) return false;
      const checked=validateMessage({version:1,kind:'patch',scope:data.scope,revision:data.revision,view:{...view,...patch}}).view;
      validateView(checked);
      if(!exists(checked.draft) || !exists(checked.selection)) throw new ContractError('view.target');
      view=freeze(checked);notify('view');return true;
    },
    subscribe(listener){
      if(disposed) return ()=>{};
      if(typeof listener!=='function') throw new ContractError('listener');
      listeners.add(listener);return ()=>listeners.delete(listener);
    },
    destroy(){
      if(disposed) return;
      disposed=true;notify('destroy');listeners.clear();indexes={};data=null;view=null;
    }
  };
}
