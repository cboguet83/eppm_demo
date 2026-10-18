/** Bounded lazy hydration with injected host I/O and explicit request ownership. */
import {ContractError,validateMessage} from '../contracts/index.js';

/** @param {number} value Positive whole limit. @param {string} field Schema path. */
function limit(value,field) {
  if(!Number.isInteger(value) || value<1) throw new ContractError(field);
}

/** @param {unknown} values Visible or overscan project identities. */
function projectIds(values) {
  if(!Array.isArray(values) || values.some(id=>typeof id!=='string' || !id.trim())) throw new ContractError('load.projectIds');
  return values;
}

/** Create one cancellable, single-flight controller for one store.
 * @param {object} options Injected store, loader, error sink, scheduling and limits.
 * @returns {object} Request/retry/status/dispose interface.
 */
export function createLoadingController({store,load,onError=()=>{},batchSize=25,maxProjects=100,
  schedule=fn=>setTimeout(fn,60),cancel=clearTimeout}) {
  limit(batchSize,'load.batchSize');limit(maxProjects,'load.maxProjects');
  if(batchSize>maxProjects || typeof load!=='function' || typeof onError!=='function') throw new ContractError('load.options');
  let wanted=[],active=null,timer=null,failed=false,disposed=false,generation=0,sequence=0;
  let {scope,revision}=store.read().data;
  const instanceId=crypto.randomUUID();
  const needed=()=>wanted.filter(id=>!store.read().data.loadedProjectIds.includes(id));
  const current=request=>!disposed && active===request && request.generation===generation;
  const abort=()=>{
    generation++;
    if(timer!==null) cancel(timer);
    timer=null;active?.controller.abort();active=null;
  };
  const queue=()=>{
    if(disposed || failed || active || timer!==null || !needed().length) return;
    timer=schedule(()=>{timer=null;void flush();});
  };
  /** @param {object} request Current request. @param {unknown} raw Host result. */
  const apply=(request,raw)=>{
    const patch=validateMessage(raw);
    if(patch.kind!=='patch' || patch.scope!==scope || patch.revision!==revision) throw new ContractError('load.response');
    const requested=new Set(request.projectIds);
    const replacements=patch.replaceProjectIds ?? request.projectIds;
    if(replacements.length!==requested.size || replacements.some(id=>!requested.has(id)) || (patch.tasks||[]).some(task=>!requested.has(task.projectId)) ||
      (patch.projects||[]).some(project=>!requested.has(project.id))) throw new ContractError('load.responseProjects');
    const previous=store.read().data.loadedProjectIds;
    const ordered=[...previous.filter(id=>!replacements.includes(id)),...replacements];
    const evicted=ordered.slice(0,Math.max(0,ordered.length-maxProjects));
    store.update({...patch,replaceProjectIds:replacements,evictProjectIds:evicted,loadedProjectIds:ordered.slice(-maxProjects)});
  };
  /** Coalesced visible-before-overscan batch, with stale response rejection. */
  async function flush() {
    if(disposed || active || failed) return;
    const ids=needed().slice(0,batchSize);
    if(!ids.length) return;
    const request={projectIds:ids,scope,revision,requestId:instanceId+':'+(++sequence),
      controller:new AbortController(),generation};
    active=request;
    try {
      const result=await load({projectIds:ids,scope,revision,requestId:request.requestId,signal:request.controller.signal});
      if(current(request)) apply(request,result);
    } catch(error) {
      if(current(request) && !request.controller.signal.aborted) {
        failed=true;
        onError({code:error instanceof ContractError?'invalid_load':'load_failed',message:'Tasks could not be loaded. Retry to continue.'});
      }
    } finally {
      if(current(request)) {active=null;queue();}
    }
  }
  let unsubscribe=()=>{};
  const destroy=()=>{if(disposed)return;disposed=true;abort();wanted=[];unsubscribe();};
  unsubscribe=store.subscribe(type=>{
    if(type==='destroy') {destroy();return;}
    if(type!=='data') return;
    const next=store.read().data;
    if(next.scope===scope && next.revision===revision) return;
    abort();wanted=[];failed=false;scope=next.scope;revision=next.revision;
  });
  return {
    request(visible,overscan=[]){
      if(disposed) return;
      const all=[...projectIds(visible),...projectIds(overscan)];
      wanted=[...new Set(all)].filter(id=>store.lookup('projects',id)).slice(0,maxProjects);queue();
    },
    retry(){if(disposed)return;failed=false;queue();},
    status(){return {pending:active!==null,failed,queued:disposed?[]:needed(),disposed};},
    destroy
  };
}
