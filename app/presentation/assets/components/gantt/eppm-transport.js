/** EPPM-only rerun projection and authorized same-origin task hydration. */
import {ContractError,validateMessage} from './planning-view/src/contracts/index.js';
import {snapshotFor,patchFor,eventFor,overlaysFor,resourceFor,projectFor} from './eppm-contract.js';

/** Create a cancellable provider retaining existing HTTP/source-token semantics.
 * @param {Function} host Current EPPM render context. @param {Function} refresh Request one authorized refresh.
 * @param {Function} fetcher Injected same-origin fetch boundary.
 */
export function createTaskProvider({host,refresh,fetcher=globalThis.fetch}) {
  let refreshed=null;
  return async request=>{
    const current=host(),scope=current.scope_token,revision=current.task_revision;
    const body={project_ids:request.projectIds.map(Number),scope_token:scope,revision,nonce:request.requestId};
    if(request.projectIds.length>25 || body.project_ids.some(value=>!Number.isSafeInteger(value) || value<1))throw new ContractError('eppm.projectIds');
    if(request.projectIds.every(project=>typeof current.task_source_tokens?.[project]==='string'))body.source_tokens=Object.fromEntries(request.projectIds.map(project=>[project,current.task_source_tokens[project]]));
    const response=await fetcher('/api/planning/tasks',{method:'POST',credentials:'same-origin',signal:request.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(request.signal.aborted || host().scope_token!==scope || host().task_revision!==revision)throw new DOMException('Planning read cancelled.','AbortError');
    if(response.status===403 || response.status===409) {
      const key=scope+':'+revision;
      if(refreshed!==key){refreshed=key;refresh(request);}
      throw new Error('Planning data changed. Refreshing the authorized view.');
    }
    if(!response.ok)throw new Error('Tasks could not be loaded. Retry loading.');
    const input=await response.json();
    if(request.signal.aborted || host().scope_token!==scope || host().task_revision!==revision)throw new DOMException('Planning read cancelled.','AbortError');
    if(input.scope_token!==scope || input.nonce!==request.requestId)throw new ContractError('eppm.readCorrelation');
    const patch=patchFor(input,current,request.revision);
    patch.requestId=request.requestId;
    if(JSON.stringify([...patch.replaceProjectIds].sort())!==JSON.stringify([...request.projectIds].sort()))throw new ContractError('eppm.readProjects');
    return validateMessage(patch);
  };
}

/** Own compact application metadata, never renderer state or an unbounded task cache.
 * @param {Function} receive Host-only correlated form responses.
 * @returns {object} Bridge normalization plus bounded working-set tracking.
 */
export function createEppmTransport({receive=()=>{}}={}) {
  let host={},snapshot=null,revision=null,loaded=[],initializing=false,emit=null,scenarioKey=null,filterReset=null;
  const pending=new Map();
  const event=(command,context={},targetId=null,overlayId=null)=>{
    if(!emit)return;
    const scope=snapshot?.scope ?? 'initial',dataRevision=revision ?? 'initial';
    const requestId=crypto.randomUUID();
    emit({version:1,scope,revision:dataRevision,requestId,type:'command',command,
      ...(targetId?{targetId,targetKind:'projects'}:{}),overlayId,context});
    return requestId;
  };
  return {
    host:()=>host,
    event,
    loaded:()=>[...loaded],
    loadedPatch(patch) {
      const replaced=new Set(patch.replaceProjectIds ?? []),evicted=new Set(patch.evictProjectIds ?? []);
      loaded=patch.loadedProjectIds ?? [...loaded.filter(project=>!replaced.has(project) && !evicted.has(project)),...replaced].slice(-100);
    },
    encodeEvent(input) {
      if(input.type==='command' && input.command==='toggle_edit')host={...host,edit_enabled:input.context?.enabled===true};
      if(['dates','progress','task','dependency'].includes(input.type))pending.set(input.requestId,input);
      return eventFor(input,host,loaded);
    },
    prepareRender(args,callbacks) {
      if(!args || typeof args!=='object' || Array.isArray(args))throw new ContractError('eppm.args');
      if(args.patch?.scope_token!==undefined && args.patch.scope_token!==(args.scope_token ?? host.scope_token))throw new ContractError('eppm.patchScope');
      emit=callbacks.emit;
      const before=host,oldRevision=revision;
      host={...host,...args,task_source_tokens:{...(args.task_source_tokens ?? host.task_source_tokens),...args.task_source_token_patch}};
      if(args.patch?.project_summaries) {
        const summaries=new Map((host.project_summaries ?? []).map(row=>[String(row.id),row]));
        for(const row of args.patch.project_summaries)summaries.set(String(row.id),row);
        host.project_summaries=[...summaries.values()];
      }
      if(args.patch?.resource_pools) {
        const pools=new Map((host.resource_pools ?? []).map(row=>[String(row.id),row]));
        for(const row of args.patch.resource_pools)pools.set(String(row.id),row);
        host.resource_pools=[...pools.values()];
      }
      if(!snapshot && !args.tasks) {
        if(!initializing){initializing=true;event('initialize_planning');}
        return null;
      }
      const messages=[];
      const rebuilt=!!args.tasks && (!snapshot || before.scope_token!==host.scope_token);
      if(rebuilt) {
        let next=snapshotFor(host);
        if(snapshot?.scope===next.scope)next={...next,viewHints:{editEnabled:next.viewHints.editEnabled}};
        snapshot=next;loaded=(host.loaded_project_ids ?? []).map(String);initializing=false;
      }
      revision=host.task_revision;
      if(args.patch) {
        const patch=patchFor(args.patch,host,revision,oldRevision ?? revision);messages.push(patch);
        this.loadedPatch(patch);
      }
      const nextScenarioKey=JSON.stringify([host.alternatives,host.baseline_tasks,host.show_baseline,host.alternative_pool_usage,host.permissions]);
      if(rebuilt)scenarioKey=nextScenarioKey; // The snapshot already owns these collections.
      const patch={version:1,kind:'patch',scope:snapshot.scope,revision,baseRevision:oldRevision ?? revision,viewHints:{editEnabled:host.edit_enabled===true}};
      if(nextScenarioKey!==scenarioKey)patch.projects=(host.project_summaries ?? []).map(row=>projectFor(row,host.permissions,host));
      if(nextScenarioKey!==scenarioKey) {
        patch.overlays=overlaysFor(host);patch.resources=(host.resource_pools ?? []).map(pool=>resourceFor(pool,host.alternative_pool_usage,host.permissions));scenarioKey=nextScenarioKey;
      }
      if(host.filter_reset!==filterReset){patch.viewHints.resetResourceFilters=true;filterReset=host.filter_reset;}
      messages.push(patch);
      const acknowledgement=args.ack_nonce;
      if(pending.has(acknowledgement)) {
        const original=pending.get(acknowledgement);pending.delete(acknowledgement);
        messages.push({version:1,kind:'response',scope:original.scope,revision,baseRevision:original.revision,requestId:acknowledgement,
          accepted:!args.adapter_error,...(args.adapter_error?{error:args.adapter_error}:{})});
      }
      if(args.dependency_response)receive('choices',args.dependency_response);
      if(args.project_dependency_response)receive('projectDependencies',args.project_dependency_response);
      for(const field of ['tasks','patch','dependency_response','project_dependency_response','adapter_error','ack_nonce'])delete host[field];
      return {snapshot,messages,ackRequestIds:acknowledgement?[acknowledgement]:[],lazy:!host.task_endpoint,options:{grouped:true,editCommand:'toggle_edit',timelineHeight:{min:178,max:439},resourceTooltipDetails:'capacity'}};
    }
  };
}
