/** Fresh capability checks and correlated user intentions, independent of the DOM. */
import {ContractError,validateEvent,validateMessage} from '../contracts/index.js';

/** Resolve an opaque target only from the delivered data.
 * @param {object} data Snapshot. @param {object} target Kind/id and optional overlayId.
 */
export function resolveTarget(data,target) {
  if(!target || !['tasks','projects','dependencies','resources'].includes(target.kind))return null;
  const overlay=target.overlayId?data.overlays.find(row=>row.id===target.overlayId):null;
  if(target.overlayId && !overlay)return null;
  const rows=overlay?(target.kind==='projects'?[data.projects.find(row=>row.id===overlay.projectId)]:(overlay[target.kind] ?? [])):data[target.kind];
  const record=rows.find(row=>row?.id===target.id);
  return record?{record,overlay,lane:overlay?.kind ?? 'current',projectId:record.projectId ?? (target.kind==='projects'?record.id:undefined)}:null;
}

/** UI hints are rechecked at request time; the host still authorizes every write.
 * @param {object} data Snapshot. @param {object} view View state.
 * @param {object} target Entity target. @param {string} operation Requested edit type.
 */
export function canEdit(data,view,target,operation='task',resolved=resolveTarget(data,target)) {
  if(!resolved || !view.filters.editEnabled || !data.capabilities.edit || resolved.lane==='baseline')return false;
  if(data.overlays.some(overlay=>overlay.kind==='alternative') && resolved.lane!=='alternative')return false;
  if(resolved.record.editable===false || resolved.overlay?.editable===false)return false;
  if(operation==='command')return true;
  if(target.kind!==(operation==='dependency'?'dependencies':'tasks'))return false;
  const capability={dates:'editDates',progress:'editProgress',task:'editTasks',dependency:'editDependencies'}[operation];
  return !!capability && data.capabilities[capability]!==false;
}

/** Validate declarative menu entries iteratively with bounded depth and no cycles.
 * @param {object[]} actions Host-owned context commands.
 */
export function validateActions(actions=[]) {
  if(!Array.isArray(actions))throw new ContractError('contextActions');
  const pending=actions.map(action=>({action,depth:1})),objects=new Set(),ids=new Set();
  while(pending.length) {
    const {action,depth}=pending.pop();
    if(!action || typeof action!=='object' || objects.has(action) || depth>8)throw new ContractError('contextActions');
    objects.add(action);
    if(typeof action.id!=='string' || !action.id.trim() || ids.has(action.id) || typeof action.label!=='string')throw new ContractError('contextActions.identity');
    ids.add(action.id);
    if(action.capability!==undefined && typeof action.capability!=='string')throw new ContractError('contextActions.capability');
    for(const field of ['targetKinds','lanes'])if(action[field]!==undefined && (!Array.isArray(action[field]) || action[field].some(value=>typeof value!=='string')))throw new ContractError('contextActions.'+field);
    if(action.requiresEdit!==undefined && typeof action.requiresEdit!=='boolean')throw new ContractError('contextActions.requiresEdit');
    if(action.children!==undefined) {
      if(!Array.isArray(action.children))throw new ContractError('contextActions.children');
      for(const child of action.children)pending.push({action:child,depth:depth+1});
    }
  }
  return validateMessage({version:1,kind:'patch',scope:'validation',revision:'validation',commands:actions}).commands;
}

/** @param {object} action Declarative action. @param {object} data Snapshot. @param {object} view View. @param {object} target Current target. */
export function actionAllowed(action,data,view,target) {
  const resolved=resolveTarget(data,target);
  if(!resolved)return false;
  return (!action.targetKinds || action.targetKinds.includes(target.kind)) && (!action.lanes || action.lanes.includes(resolved.lane)) &&
    (!action.capability || data.capabilities[action.capability]===true) && (!action.requiresEdit || canEdit(data,view,target,'command'));
}

/** Validate edited values before setting pending state or notifying the host.
 * @param {string} type Event type. @param {object} values Edited fields. @param {object} record Original entity.
 */
function validateValues(type,values,record) {
  if(type==='task') {
    const next={...record,...values};
    validateMessage({version:1,kind:'snapshot',scope:'validation',revision:'validation',projects:[{id:record.projectId,name:''}],tasks:[next],dependencies:values.dependencies ?? []});
    for(const field of ['description','phase'])if(next[field]!==undefined && typeof next[field]!=='string')throw new ContractError('task.'+field);
  }
  if(type==='dependency')validateMessage({version:1,kind:'patch',scope:'validation',revision:'validation',dependencies:[{...record,...values,id:record.id}]});
}

/** Own correlation and request delivery. Host callbacks may update synchronously.
 * @param {object} store Store. @param {Function} onEvent Host event sink.
 * @param {Function} requestId Opaque ID provider. @returns {object} Request/draft seam.
 */
export function createActionController({store,onEvent=()=>{},requestId=()=>crypto.randomUUID()}) {
  let disposed=false,overlayIndexes=new WeakMap();
  const resolve=target=>{
    if(disposed || !target || !['tasks','projects','dependencies','resources'].includes(target.kind))return null;
    const overlay=target.overlayId?store.lookup('overlays',target.overlayId):null;
    if(target.overlayId && !overlay)return null;
    let record;
    if(!overlay)record=store.lookup(target.kind,target.id);
    else if(target.kind==='projects')record=target.id===overlay.projectId?store.lookup('projects',target.id):null;
    else {
      if(!overlayIndexes.has(overlay))overlayIndexes.set(overlay,Object.fromEntries(['tasks','dependencies'].map(kind=>[kind,new Map((overlay[kind] ?? []).map(row=>[row.id,row]))])));
      record=overlayIndexes.get(overlay)[target.kind]?.get(target.id);
    }
    return record?{record,overlay,lane:overlay?.kind ?? 'current',projectId:record.projectId ?? (target.kind==='projects'?record.id:undefined)}:null;
  };
  const targetState=target=>target.overlayId?{kind:'overlays',id:target.overlayId,values:{target}}:{kind:target.kind,id:target.id,values:{target}};
  const failure=id=>{
    if(disposed || store.read().view.pendingRequestId!==id)return;
    store.setView({pendingRequestId:null,preview:null,error:'The host could not process this action.'});
  };
  const deliver=event=>{
    try {
      const result=onEvent(event);
      if(result && typeof result.then==='function')Promise.resolve(result).catch(()=>failure(event.requestId));
    }catch(error){failure(event.requestId);throw error;}
    return event;
  };
  return {
    resolve,
    canEdit(target,operation='task'){if(disposed)return false;const {data,view}=store.read();return canEdit(data,view,target,operation,resolve(target));},
    open(target) {
      if(disposed)return false;
      const {data,view}=store.read(),operation=target.kind==='dependencies'?'dependency':'task';
      if(view.pendingRequestId || !canEdit(data,view,target,operation,resolve(target)))return false;
      const {record}=resolve(target);
      const fields=operation==='dependency'?{type:record.type,lagDays:record.lagDays ?? 0,predecessor:record.predecessor,successor:record.successor}:
        {name:record.name,start:record.start,end:record.end,progress:record.progress ?? 0,description:record.description ?? '',phase:record.phase ?? '',
          dependencies:(target.overlayId?data.overlays.find(row=>row.id===target.overlayId).dependencies ?? []:data.dependencies).filter(dep=>dep.successor.kind==='task' && dep.successor.id===record.id)};
      store.setView({draft:{...targetState(target),values:{target,fields}},error:null});return true;
    },
    request(type,target,values={}) {
      if(disposed)return null;
      const {data,view}=store.read(),resolved=resolve(target);
      if(view.pendingRequestId || !resolved || !canEdit(data,view,target,type,resolved))return null;
      validateValues(type,values,resolved.record);
      const event=validateEvent({version:1,scope:data.scope,revision:data.revision,requestId:requestId(),type,
        targetId:target.id,targetKind:target.kind,overlayId:target.overlayId ?? null,lane:resolved.lane,
        ...(['task','dependency'].includes(type)?{values}:values)});
      store.setView({pendingRequestId:event.requestId,error:null,preview:{target,...values}});
      return deliver(event);
    },
    command(action,target,context={}) {
      if(disposed)return null;
      const {data,view}=store.read();
      if(!actionAllowed(action,data,view,target))return null;
      const event=validateEvent({version:1,scope:data.scope,revision:data.revision,requestId:requestId(),type:'command',command:action.id,
        targetId:target.id,targetKind:target.kind,overlayId:target.overlayId ?? null,context});
      return deliver(event);
    },
    select(target,context={}) {
      if(disposed)return null;
      const {data}=store.read();
      if(data.capabilities.select===false || !resolveTarget(data,target))return null;
      store.setView({selection:targetState(target)});
      return deliver(validateEvent({version:1,scope:data.scope,revision:data.revision,requestId:requestId(),type:'select',targetId:target.id,
        targetKind:target.kind,overlayId:target.overlayId ?? null,context}));
    },
    close(){if(!disposed)store.setView({draft:null,error:null});},
    destroy(){disposed=true;overlayIndexes=new WeakMap();}
  };
}
