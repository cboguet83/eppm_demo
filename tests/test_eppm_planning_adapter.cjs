// Public adapter behavior, independent of renderer globals or sliced source.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const contracts=import('../app/presentation/assets/components/gantt/eppm-contract.js');
const transport=import('../app/presentation/assets/components/gantt/eppm-transport.js');
function fixture() {
  return {tasks:[{id:'7',project_id:'1',name:'Step',start:'2028-02-28',end:'2028-03-01',progress:50,
    dependenciesList:[{id:9,predecessor_task_id:null,predecessor_project_id:null,link_type:'FS',lag_days:0}]}],
    project_summaries:[{id:1,name:'Project',taskCount:1,start:'2028-02-28',end:'2028-03-01',projectDependencies:[]}],
    scope_token:'server-scope',view_scope:'selection',task_revision:'r1',data_revision:'server-scope',loaded_project_ids:[1],
    permissions:{editable_projects:[1]},edit_enabled:false,filter_reset:0,
    resource_pools:[{id:2,name:'Team',capacity:10,theoretical_capacity:12,displayed_assigned_capacity:5,
      daily_assigned_capacity_intervals:[['2028-02-28','2028-02-28',0]],daily_usage_intervals:[['2028-02-28','2028-03-01',6]]}],
    resource_pool_hierarchy:[{key:'group:3',name:'Group',group_id:3,children:[{key:'pool:3:2',name:'Team',pool_id:2},{key:'pool:3:4',name:'Other',pool_id:4}]}],
    alternatives:{},baseline_tasks:{},show_baseline:false};
}
test('EPPM snapshot preserves stable identities, inclusive zero intervals and redaction',async()=>{
  const {snapshotFor}=await contracts,snapshot=snapshotFor(fixture());
  assert.equal(snapshot.scope,'selection');assert.equal(snapshot.tasks[0].id,'7');assert.equal(snapshot.tasks[0].editable,true);
  assert.deepEqual(snapshot.dependencies[0].predecessor,{kind:'unavailable'});
  assert.deepEqual(snapshot.resources[0].assignedCapacity,{'2028-02-28':0});assert.equal(snapshot.resources[0].capacity,5);
  assert.equal(snapshot.resources[0].usage['2028-02-29'],6);
  assert.deepEqual(snapshot.hierarchy[0].children.map(row=>row.resourceId),['2','4']);
  assert.deepEqual(snapshot.viewHints.expandedProjectIds,['1']);
});
test('current and alternative events preserve the existing task service protocol',async()=>{
  const {eventFor,snapshotFor}=await contracts,host=fixture();
  const event={type:'dates',targetKind:'tasks',targetId:'7',requestId:'move',start:'2028-03-01',end:'2028-03-03',context:{projectId:'1',planRevision:4}};
  assert.deepEqual(eventFor(event,host,['1']),{nonce:'move',scope_token:'server-scope',loaded_project_ids:[1],action:'update_dates',id:7,start_date:'2028-03-01',end_date:'2028-03-03'});
  host.alternatives={1:{id:21,revision:5,name:'Alternative',editable:true,new_scenario:true,tasks:[{id:100,stable_id:7,task_name:'Renamed',start_date:'2028-03-02',end_date:'2028-03-04'}],dependencies:[]}};
  const alternative=snapshotFor(host).overlays[0];assert.equal(alternative.tasks[0].stableId,'7');assert.equal(alternative.newScenario,true);
  const mapped=eventFor({...event,overlayId:alternative.id},host,['1']);
  assert.equal(mapped.action,'update_alternative_dates');assert.equal(mapped.plan_id,21);assert.equal(mapped.revision,4); // Capture draft revision, never silently replace with a newer one.
  const save=eventFor({...event,type:'task',overlayId:alternative.id,values:{name:'Edited',phase:'P',description:'D',start:'2028-03-02',end:'2028-03-04',progress:90,
    dependencies:[{type:'SS',lagDays:-2,predecessor:{kind:'project',id:'8'}}]}},host);
  assert.equal(save.action,'alternative_action');assert.equal(save.operation,'update_task_full');assert.equal(save.task_name,'Edited');
  assert.deepEqual(save.dependencies,[{predecessor_task_id:null,predecessor_project_id:8,link_type:'SS',lag_days:-2}]);
});
test('partial reruns emit canonical patches and correlated rejection without discarding lazy rows',async()=>{
  const {createEppmTransport}=await transport,adapter=createEppmTransport(),emitted=[];
  assert.equal(adapter.prepareRender({},{emit:event=>emitted.push(event)}),null);
  adapter.prepareRender({},{emit:event=>emitted.push(event)});assert.equal(emitted.length,1);assert.equal(emitted[0].command,'initialize_planning');
  const first=adapter.prepareRender(fixture(),{emit:event=>emitted.push(event)});
  adapter.loadedPatch({replaceProjectIds:['8']});
  const event={version:1,scope:'selection',revision:'r1',type:'progress',targetId:'7',targetKind:'tasks',progress:70,requestId:'edit',context:{projectId:'1'}};
  const wire=adapter.encodeEvent(event);assert.deepEqual(wire.loaded_project_ids,[1,8]);
  const rerun=adapter.prepareRender({task_revision:'r1',ack_nonce:'edit',adapter_error:'Changed by another user.'},{emit:()=>{}});
  assert.deepEqual(rerun.snapshot,first.snapshot);assert.deepEqual(adapter.loaded(),['1','8']);
  assert.equal(rerun.messages.at(-1).accepted,false);assert.equal(rerun.messages.at(-1).requestId,'edit');
  const patch=adapter.prepareRender({task_revision:'r2',patch:{replace_projects:[1],tasks:fixture().tasks,loaded_project_ids:[1,8]}},{emit:()=>{}}).messages[0];
  assert.equal(patch.baseRevision,'r1');assert.equal(patch.revision,'r2');assert.deepEqual(patch.replaceProjectIds,['1']);
});
test('HTTP hydration sends bounded same-origin source tokens and requires exact correlation',async()=>{
  const {createTaskProvider}=await transport,host={...fixture(),task_source_tokens:{1:'source'}},calls=[];
  const request={scope:'selection',revision:'r1',requestId:'read',projectIds:['1'],signal:new AbortController().signal};
  const provider=createTaskProvider({host:()=>host,refresh:()=>assert.fail('Unexpected refresh'),fetcher:async(url,options)=>{
    calls.push({url,options});return {ok:true,json:async()=>({scope_token:'server-scope',nonce:'read',replace_projects:[1],tasks:fixture().tasks})};
  }});
  const result=await provider(request);assert.deepEqual(result.replaceProjectIds,['1']);assert.equal(result.requestId,'read');
  assert.equal(calls[0].url,'/api/planning/tasks');assert.equal(calls[0].options.credentials,'same-origin');assert.equal(calls[0].options.signal,request.signal);
  assert.deepEqual(JSON.parse(calls[0].options.body).source_tokens,{'1':'source'});
  await assert.rejects(provider({...request,projectIds:Array.from({length:26},(_,i)=>String(i+1))}),/projectIds/);
  const wrong=createTaskProvider({host:()=>host,refresh:()=>{},fetcher:async()=>({ok:true,json:async()=>({scope_token:'other',nonce:'read'})})});
  await assert.rejects(wrong(request),/readCorrelation/);
});
test('403/409 refresh once per source revision, and cancelled/stale reads never apply',async()=>{
  const {createTaskProvider}=await transport;let host=fixture(),refreshes=0,status=403;
  const provider=createTaskProvider({host:()=>host,refresh:()=>refreshes++,fetcher:async()=>({status,ok:false})});
  const request={scope:'selection',revision:'r1',requestId:'read',projectIds:['1'],signal:new AbortController().signal};
  await assert.rejects(provider(request),/changed/);status=409;await assert.rejects(provider(request),/changed/);assert.equal(refreshes,1);
  host={...host,task_revision:'r2'};await assert.rejects(provider({...request,revision:'r2'}),/changed/);assert.equal(refreshes,2);
  const stale=createTaskProvider({host:()=>host,refresh:()=>assert.fail(),fetcher:async()=>{host={...host,task_revision:'r3'};return {ok:true};}});
  await assert.rejects(stale(request),{name:'AbortError'});
  const controller=new AbortController();controller.abort();await assert.rejects(provider({...request,signal:controller.signal}),{name:'AbortError'});
});

test('EPPM command capabilities preserve read-only navigation and separate approval/admin hints',async()=>{
  const {snapshotFor,projectFor,dependencyFor,resourceFor}=await contracts;
  const {planningCommands,confirmedCommand}=await import('../app/presentation/assets/components/gantt/eppm-commands.js');
  const {actionAllowed}=await import('../packages/planning-view/src/workspace/actions.js');
  const entries=new Map(),pending=[...planningCommands()];while(pending.length){const entry=pending.pop();entries.set(entry.id,entry);pending.push(...(entry.children ?? []));}
  for(const enabled of [false,true])for(const permission of [{},{editable_projects:[1]},{edit_all:true}]) {
    const host={...fixture(),permissions:permission,edit_enabled:enabled},data=snapshotFor(host),view={filters:{editEnabled:enabled}};
    const project={kind:'projects',id:'1'},task={kind:'tasks',id:'7'},permitted=!!permission.edit_all || !!permission.editable_projects;
    for(const command of ['add_step','project_dependencies','import_csv_template','manage_project_tags','manage_project_pools'])assert.equal(actionAllowed(entries.get(command),data,view,project),enabled && permitted,command);
    for(const command of ['export_csv_template','edit_project_details'])assert.equal(actionAllowed(entries.get(command),data,view,project),true,command);
    assert.equal(actionAllowed(entries.get('log_project_event'),data,view,task),permitted);
    assert.equal(actionAllowed(entries.get('log_project_event'),data,view,project),permitted);
  }
  const project=projectFor(fixture().project_summaries[0],{approvable_projects:[1]});assert.equal(project.capabilities.captureBaseline,true);assert.equal(project.editable,false);
  assert.equal(resourceFor(fixture().resource_pools[0]).capabilities.poolDetails,false);
  assert.equal(resourceFor(fixture().resource_pools[0],{},{manage_shared:true}).capabilities.poolDetails,true);
  const link={id:8,predecessor_task_id:9,predecessor_owner_id:2,link_type:'FS'};
  assert.equal(dependencyFor(link,'1','7',{editable_projects:[1]}).editable,false);
  assert.equal(dependencyFor(link,'1','7',{editable_projects:[1,2]}).editable,true);
  assert.equal(dependencyFor(link,'1','7',{editable_projects:[1]},true).editable,true);
  const prompts=[],win={confirm:message=>{prompts.push(message);return false;},alert:()=>assert.fail()};
  assert.equal(confirmedCommand({type:'command',command:'delete_project_baseline',targetId:'1'},fixture(),win),null);
  assert.equal(prompts.length,1);
  assert.equal(confirmedCommand({type:'command',command:'filter_project_with_dependencies',targetId:'1'},fixture(),win).context.filterScope,'all');
});

test('bounded replacements retain unchanged project links and group filters address hierarchy identities',async()=>{
  const {patchFor,snapshotFor}=await contracts,host=fixture();
  host.project_summaries[0].projectDependencies=[{id:21,predecessor_project_id:2,link_type:'SS',lag_days:-2}];
  const patch=patchFor({replace_projects:[1],tasks:host.tasks},host,'r1');
  assert.deepEqual(patch.dependencies.map(row=>row.id),['task:9','project:21']);
  host.active_resource_filter={group_id:3,pool_name:'Group',start_date:'2028-02-28',end_date:'2028-03-01'};
  const snapshot=snapshotFor(host);assert.equal(snapshot.resourceFilter.groupId,'group:3');assert.equal(snapshot.capabilities.clearResourceFilter,true);
  assert.equal(snapshot.resourceFilter.start,'2028-02-28');
});

test('predecessor reads coalesce by project/source while cancellation and stale responses remain isolated',async()=>{
  const {createChoiceReader}=await import('../app/presentation/assets/components/gantt/eppm-choices.js');
  let host=fixture();const requests=[];
  const reader=createChoiceReader({host:()=>host,event:(command,context,project)=>{const nonce='choice-'+(requests.length+1);requests.push({command,context,project,nonce});return nonce;}});
  const firstController=new AbortController(),secondController=new AbortController();
  const request=signal=>({projectId:'2',overlayId:null,signal});
  const first=reader.read(request(firstController.signal)),second=reader.read(request(secondController.signal));
  assert.equal(requests.length,1);firstController.abort();await assert.rejects(first,{name:'AbortError'});
  reader.receive({nonce:'unknown',project_id:'2',tasks:[]});
  reader.receive({nonce:requests[0].nonce,project_id:'2',tasks:[{id:8,task_name:'Predecessor'}]});
  assert.deepEqual(await second,[{id:'8',name:'Predecessor'}]);
  const stale=reader.read(request(new AbortController().signal));host={...host,task_revision:'r2'};
  reader.receive({nonce:requests.at(-1).nonce,project_id:'2',tasks:[]});await assert.rejects(stale,{name:'AbortError'});
  const rejected=reader.read(request(new AbortController().signal));reader.receive({nonce:requests.at(-1).nonce,project_id:'3',tasks:[]});await assert.rejects(rejected,/could not be loaded/);
  const failed=reader.read(request(new AbortController().signal));reader.receive({nonce:requests.at(-1).nonce,project_id:'2',error:'SECRET FAILURE'});
  await assert.rejects(failed,error=>error.message==='Predecessor tasks could not be loaded.');
  const controller=new AbortController(),cancelled=reader.read(request(controller.signal));controller.abort();await assert.rejects(cancelled,{name:'AbortError'});
  reader.receive({nonce:requests.at(-1).nonce,project_id:'2',tasks:[{id:8,task_name:'Late'}]});
  const pending=reader.read(request(new AbortController().signal));reader.destroy();reader.destroy();await assert.rejects(pending,{name:'AbortError'});
  await assert.rejects(reader.read(request(new AbortController().signal)),{name:'AbortError'});
});

test('alternative predecessor choices use stable delivered identities without current schedule reads',async()=>{
  const {createChoiceReader}=await import('../app/presentation/assets/components/gantt/eppm-choices.js');
  const host={...fixture(),alternatives:{1:{tasks:[{id:99,stable_id:7,task_name:'Alternative'}]}},alternative_task_choices:[{id:8,project_id:2,task_name:'External'}]};
  const reader=createChoiceReader({host:()=>host,event:()=>assert.fail('Unexpected current schedule read')});
  const request={projectId:'1',overlayId:'alternative:21',signal:new AbortController().signal};
  assert.deepEqual(await reader.read(request),[{id:'7',name:'Alternative'}]);
  assert.deepEqual(await reader.read({...request,projectId:'2'}),[{id:'8',name:'External'}]);reader.destroy();
});
