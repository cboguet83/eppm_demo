import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ContractError} from '../src/contracts/index.js';
import {createPlanningStore} from '../src/state/store.js';
import {createLoadingController} from '../src/state/loader.js';

const task=(id,projectId)=>({id,projectId,name:id,start:'2026-01-01',end:'2026-01-02'});
const initial=(count=2)=>({version:1,kind:'snapshot',scope:'view',revision:'r1',
  projects:Array.from({length:count},(_,i)=>({id:'p'+i,name:'Project '+i,taskCount:1})),
  tasks:[task('t0','p0'),task('t1','p1')],loadedProjectIds:['p0','p1']});
const patch=values=>({version:1,kind:'patch',scope:'view',revision:'r1',...values});

test('patches are atomic and preserve unchanged records, resources, draft and viewport',()=>{
  const store=createPlanningStore({...initial(),resources:[{id:'pool',name:'Pool',capacity:2,usage:{'2026-01-01':1}}]});
  store.setView({scrollTop:100,scrollLeft:25,draft:{kind:'tasks',id:'t1',values:{name:'Unsaved'}}});
  const old=store.read(),resource=old.data.resources[0];
  assert.equal(store.update(patch({replaceProjectIds:['p0'],tasks:[task('t2','p0')]})),true);
  assert.equal(store.lookup('tasks','t0'),undefined);
  assert.equal(store.lookup('tasks','t2').id,'t2');
  assert.equal(store.lookup('tasks','t1'),old.data.tasks[1]);
  assert.equal(store.read().data.resources[0],resource);
  assert.deepEqual(store.read().view,old.view);
  const current=store.read();
  assert.throws(()=>store.update(patch({tasks:[task('bad','unknown')]})),ContractError);
  assert.equal(store.read().data,current.data);
  assert.throws(()=>store.update(patch({loadedProjectIds:['unknown']})),ContractError);
  assert.throws(()=>store.update(patch({evictProjectIds:[1]})),ContractError);
  assert.equal(store.read().data,current.data);
});

test('same-scope snapshots preserve drafts; explicit reset and new scopes clear state',()=>{
  const store=createPlanningStore(initial());
  store.setView({draft:{kind:'projects',id:'p0'},scrollTop:120,selection:{kind:'tasks',id:'t0'}});
  store.update({...initial(),revision:'r2'});
  assert.equal(store.read().view.scrollTop,120);
  store.update(patch({revision:'r2',reset:true}));
  assert.equal(store.read().view.scrollTop,0);
  store.setView({scrollTop:200});
  store.update({...initial(),scope:'another'});
  assert.equal(store.read().view.scrollTop,0);
  assert.equal(store.update(patch({removeTaskIds:['t0']})),false);
  assert.equal(store.update(patch({scope:'another',revision:'r3',baseRevision:'old'})),false);
  assert.equal(store.update(patch({scope:'another',revision:'r3',baseRevision:'r1'})),true);
});

test('deletion invalidates the removed draft and selection and prunes owned links/overlays',()=>{
  const store=createPlanningStore({...initial(),dependencies:[{id:'edge',type:'FS',
    predecessor:{kind:'unavailable'},successor:{kind:'task',id:'t0'}}],
    overlays:[{id:'baseline',kind:'baseline',projectId:'p0',tasks:[task('old','p0')]}]});
  store.setView({draft:{kind:'tasks',id:'t0'},selection:{kind:'tasks',id:'t0'}});
  store.update(patch({removeProjectIds:['p0']}));
  assert.equal(store.read().view.draft,null);assert.equal(store.read().view.selection,null);
  assert.ok(store.read().view.error.includes('no longer available'));
  assert.equal(store.read().data.dependencies.length,0);
  assert.equal(store.read().data.overlays.length,0);
  assert.equal(store.lookup('projects','p0'),undefined);
  assert.deepEqual(store.read().data.loadedProjectIds,['p1']);
});

test('correlated responses reconcile preview and preserve rejected drafts',()=>{
  const store=createPlanningStore(initial());
  store.setView({draft:{kind:'tasks',id:'t0'},pendingRequestId:'request',preview:{start:'2026-01-02'}});
  const response={version:1,kind:'response',scope:'view',revision:'r1',requestId:'request',accepted:false,error:'Stale dates'};
  assert.equal(store.update({...response,requestId:'old'}),false);
  assert.equal(store.update(response),true);
  assert.equal(store.read().view.preview,null);assert.equal(store.read().view.error,'Stale dates');
  assert.equal(store.read().view.draft.id,'t0');
  store.setView({pendingRequestId:'accepted'});
  store.update({...response,requestId:'accepted',accepted:true});
  assert.equal(store.read().view.draft,null);assert.equal(store.read().view.error,null);
});

test('stores own frozen snapshots, independent views and deliberate disposal',()=>{
  const source=initial(),store=createPlanningStore(source),other=createPlanningStore(source);
  source.tasks[0].name='Changed';
  assert.equal(store.lookup('tasks','t0').name,'t0');
  assert.throws(()=>{store.read().data.tasks[0].name='Mutated';},TypeError);
  const notifications=[];const unsubscribe=store.subscribe(type=>notifications.push(type));
  store.setView({scrollTop:10});assert.equal(other.read().view.scrollTop,0);
  unsubscribe();store.setView({scrollTop:20});
  assert.deepEqual(notifications,['view']);
  for(const value of [{scrollTop:-1},{mode:'Invalid'},{filters:[]},{draft:{kind:'bad',id:'x'}},
    {draft:{kind:'tasks',id:'missing'}},{pendingRequestId:42}]) assert.throws(()=>store.setView(value),ContractError);
  assert.throws(()=>store.subscribe(1),ContractError);
  store.destroy();store.destroy();
  assert.equal(store.setView({}),false);assert.equal(store.update(null),false);
  assert.throws(()=>store.read(),ContractError);assert.equal(store.lookup('tasks','t0'),undefined);
  store.subscribe(()=>{})();
  assert.throws(()=>createPlanningStore(patch({})),ContractError);
  assert.equal(other.lookup('unknown','x'),undefined);
  assert.throws(()=>createPlanningStore({...initial(),loadedProjectIds:['missing']}),ContractError);
  assert.throws(()=>createPlanningStore({...initial(),overlays:[{id:'bad',kind:'baseline',projectId:'missing',tasks:[]}]}),ContractError);
  assert.throws(()=>createPlanningStore({...initial(),overlays:[{id:'bad',kind:'baseline',projectId:'p0',tasks:[task('wrong','p1')]}]}),ContractError);
});

test('project dependencies, explicit task/resource deletion and capability patches reconcile without unrelated changes',()=>{
  const store=createPlanningStore({...initial(),resources:[{id:'pool',name:'Pool',capacity:3}],
    dependencies:[{id:'project-edge',type:'FS',predecessor:{kind:'unavailable'},successor:{kind:'project',id:'p0'}}]});
  store.update(patch({removeResourceIds:['pool'],removeTaskIds:['t1'],capabilities:{edit:false},labels:{edit:'Modifier'}}));
  assert.equal(store.lookup('resources','pool'),undefined);assert.equal(store.lookup('tasks','t1'),undefined);
  assert.equal(store.read().data.capabilities.edit,false);assert.equal(store.read().data.labels.edit,'Modifier');
  store.update(patch({removeProjectIds:['p0']}));assert.equal(store.read().data.dependencies.length,0);
});

function harness(count=140,options={}) {
  const store=createPlanningStore({...initial(count),tasks:[],loadedProjectIds:[]});
  const timers=new Map(),requests=[],errors=[];let index=0;
  const controller=createLoadingController({store,
    load:request=>new Promise((resolve,reject)=>requests.push({request,resolve,reject})),
    schedule:callback=>{timers.set(++index,callback);return index;},cancel:id=>timers.delete(id),
    onError:error=>errors.push(error),...options});
  const tick=async()=>{
    const current=[...timers.values()];timers.clear();current.forEach(callback=>callback());
    await Promise.resolve();await Promise.resolve();
  };
  const finish=async(request= requests.at(-1),extra={})=>{
    request.resolve(patch({scope:request.request.scope,revision:request.request.revision,
      tasks:request.request.projectIds.map(id=>task('t-'+id,id)),replaceProjectIds:request.request.projectIds,...extra}));
    await Promise.resolve();await Promise.resolve();
  };
  return {store,controller,timers,requests,errors,tick,finish};
}

test('visible requests coalesce before overscan, remain single-flight and cap retention at 100',async()=>{
  const h=harness(),ids=Array.from({length:140},(_,i)=>'p'+i);
  h.controller.request(ids.slice(10,30),ids.slice(0,140));
  h.controller.request(ids.slice(10,30),ids.slice(0,140));
  assert.equal(h.timers.size,1);await h.tick();
  assert.equal(h.requests.length,1);assert.equal(h.requests[0].request.projectIds.length,25);
  assert.deepEqual(h.requests[0].request.projectIds.slice(0,20),ids.slice(10,30));
  h.controller.request(ids.slice(10,30),ids);
  await h.tick();assert.equal(h.requests.length,1);
  for(let i=0;i<4;i++){await h.finish();await h.tick();}
  assert.equal(h.requests.length,4);assert.equal(h.store.read().data.loadedProjectIds.length,100);
  assert.equal(h.controller.status().queued.length,0);
  h.controller.request(ids.slice(115,140));await h.tick();await h.finish();
  assert.equal(h.store.read().data.loadedProjectIds.length,100);
  assert.equal(h.store.lookup('tasks','t-p10'),undefined);
  assert.equal(h.store.lookup('projects','p10').taskCount,1);
});

test('scope/revision changes abort old reads and reject late results',async()=>{
  const h=harness();h.controller.request(['p0']);await h.tick();const old=h.requests[0];
  h.store.update({...initial(140),scope:'next',revision:'r2',tasks:[],loadedProjectIds:[]});
  assert.equal(old.request.signal.aborted,true);
  h.controller.request(['p1']);await h.tick();
  await h.finish(old);assert.equal(h.store.lookup('tasks','t-p0'),undefined);
  await h.finish();assert.equal(h.store.lookup('tasks','t-p1').projectId,'p1');
  assert.equal(h.errors.length,0);
});

test('read errors retain valid data and require an explicit retry',async()=>{
  const h=harness();h.controller.request(['p0']);await h.tick();
  h.requests[0].reject(new Error('backend detail must not be displayed'));
  await Promise.resolve();await Promise.resolve();
  assert.equal(h.controller.status().failed,true);assert.equal(h.timers.size,0);
  assert.equal(h.errors[0].code,'load_failed');assert.ok(!h.errors[0].message.includes('backend detail'));
  h.controller.request(['p1']);await h.tick();assert.equal(h.requests.length,1);
  h.controller.retry();await h.tick();await h.finish();
  assert.equal(h.controller.status().failed,false);assert.equal(h.store.lookup('tasks','t-p1').projectId,'p1');
});

for(const bad of [{scope:'wrong'},{replaceProjectIds:[]},{tasks:[task('bad','p3')]},{projects:[{id:'p3',name:'Wrong'}]}]) {
  test('invalid load result fails once without state mutation or a retry loop '+JSON.stringify(bad),async()=>{
    const h=harness();h.controller.request(['p0']);await h.tick();const old=h.store.read().data;
    await h.finish(undefined,bad);
    assert.equal(h.store.read().data,old);assert.equal(h.errors[0].code,'invalid_load');
    assert.equal(h.controller.status().failed,true);assert.equal(h.timers.size,0);
  });
}

test('disposal cancels scheduled work and in-flight callbacks without notifications',async()=>{
  const h=harness();h.controller.request(['unknown','p0']);h.controller.destroy();h.controller.destroy();
  await h.tick();assert.equal(h.requests.length,0);h.controller.request(['p1']);h.controller.retry();
  assert.deepEqual(h.controller.status().queued,[]);
  const other=harness();other.controller.request(['p0']);await other.tick();const request=other.requests[0];
  other.store.destroy();assert.equal(request.request.signal.aborted,true);
  request.reject(new Error('late'));await Promise.resolve();await Promise.resolve();
  assert.equal(other.errors.length,0);assert.equal(other.controller.status().disposed,true);
});

test('loader limits and inputs reject unsafe configuration',()=>{
  for(const options of [{batchSize:0},{maxProjects:Infinity},{batchSize:101},{load:null},{onError:null}]) {
    assert.throws(()=>harness(140,options),ContractError);
  }
  const h=harness();assert.throws(()=>h.controller.request([42]),ContractError);
  assert.throws(()=>h.controller.request('p0'),ContractError);h.controller.destroy();
});
