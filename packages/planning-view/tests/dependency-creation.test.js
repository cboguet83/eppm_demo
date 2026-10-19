import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createActionController} from '../src/workspace/actions.js';
import {createPlanningStore} from '../src/state/store.js';
import {validateEvent,ContractError} from '../src/contracts/index.js';

function harness(extra={}) {
  const store=createPlanningStore({version:1,kind:'snapshot',scope:'scope',revision:'r1',
    projects:[{id:'alpha',name:'Alpha'},{id:'beta',name:'Beta'}],
    tasks:[{id:'a',projectId:'alpha',name:'A',start:'2026-01-01',end:'2026-01-03'},
      {id:'b',projectId:'beta',name:'B',start:'2026-01-02',end:'2026-01-05'}],
    capabilities:{edit:true,createDependencies:true},...extra});
  store.setView({filters:{editEnabled:true}});
  const events=[];let sequence=0;
  return {store,events,actions:createActionController({store,onEvent:event=>events.push(event),requestId:()=>String(++sequence)})};
}
const source={kind:'tasks',id:'a'},target={kind:'tasks',id:'b'};

for(const type of ['FS','SS','FF','SF'])for(const from of ['tasks','projects'])for(const to of ['tasks','projects']) {
  test(`create ${type} ${from} to ${to} preserves opaque directed identities`,()=>{
    const h=harness(),a={kind:from,id:from==='tasks'?'a':'alpha'},b={kind:to,id:to==='tasks'?'b':'beta'};
    const event=h.actions.requestDependency(a,b,type);
    assert.equal(event.operation,'create');assert.equal(event.values.type,type);assert.equal(event.values.lagDays,0);
    assert.equal(event.values.predecessor.id,a.id);assert.equal(event.values.successor.id,b.id);
    assert.equal(event.context.projectId,'beta');assert.equal(h.events.length,1);
    assert.equal(h.actions.requestDependency(a,b,type),null);
    assert.equal(h.store.read().data.dependencies.length,0);
    assert.equal(h.store.update({version:1,kind:'response',scope:'scope',revision:'r1',requestId:'obsolete',accepted:true}),false);
    h.store.update({version:1,kind:'response',scope:'scope',revision:'r1',requestId:event.requestId,accepted:false,error:'Stale'});
    assert.equal(h.store.read().view.preview,null);assert.equal(h.store.read().view.error,'Stale');
  });
}

test('creation is opt-in and rechecks permissions and endpoint restrictions',()=>{
  for(const capabilities of [{edit:true},{edit:true,createDependencies:false},{edit:false,createDependencies:true}]) {
    assert.equal(harness({capabilities}).actions.requestDependency(source,target,'FS'),null);
  }
  const h=harness();assert.equal(h.actions.requestDependency(source,source,'FS'),null);
  assert.equal(h.actions.requestDependency({kind:'projects',id:'alpha'},source,'FS'),null);
  assert.equal(h.actions.requestDependency({kind:'tasks',id:'missing'},target,'FS'),null);
  h.store.setView({filters:{editEnabled:false}});assert.equal(h.actions.requestDependency(source,target,'FS'),null);
  h.actions.destroy();assert.equal(h.actions.canCreateDependency(source,target),false);
  assert.equal(h.actions.requestDependency(source,target,'FS'),null);
});

test('creation captures successor alternative revision and preserves unrelated draft on acceptance',()=>{
  const h=harness({overlays:[{id:'alternative',kind:'alternative',projectId:'beta',revision:'p2',context:{planRevision:2},
    tasks:[{id:'alternative-task',projectId:'beta',name:'Alternative',start:'2026-01-02',end:'2026-01-05'}]}]});
  const alternative={kind:'tasks',id:'alternative-task',overlayId:'alternative'};
  h.actions.open(alternative);const draft=h.store.read().view.draft;
  assert.equal(h.actions.requestDependency(source,target,'FS'),null);
  const event=h.actions.requestDependency(source,alternative,'SS');
  assert.equal(event.context.planRevision,2);assert.equal(event.overlayId,'alternative');
  h.store.update({version:1,kind:'response',scope:'scope',revision:'r1',requestId:event.requestId,accepted:true});
  assert.deepEqual(h.store.read().view.draft,draft);
});

test('creation rejects malformed payloads before notifying the host',()=>{
  const h=harness();assert.throws(()=>h.actions.requestDependency(source,target,'invalid'),ContractError);
  assert.equal(h.events.length,0);assert.equal(h.store.read().view.pendingRequestId,null);
  const event=h.actions.requestDependency(source,target,'FS');
  for(const values of [{...event.values,lagDays:1},{...event.values,predecessor:{kind:'unavailable'}},
    {...event.values,successor:{kind:'project',id:'beta'}},{...event.values,type:'bad'}]) {
    assert.throws(()=>validateEvent({...event,values}),ContractError);
  }
  assert.throws(()=>validateEvent({...event,overlayId:'alt'}),ContractError);
});

test('a failed creation cannot leave draft-preservation enabled for a later ordinary save',()=>{
  const h=harness();h.actions.open(target);
  const broken=createActionController({store:h.store,onEvent:()=>false,requestId:()=> 'failed'});
  assert.equal(broken.requestDependency(source,target,'FS'),false);
  assert.equal(h.store.read().view.preservePendingDraft,false);
  const event=h.actions.request('task',target,{...h.store.read().view.draft.values.fields,name:'Saved'});
  h.store.update({version:1,kind:'response',scope:'scope',revision:'r1',requestId:event.requestId,accepted:true});
  assert.equal(h.store.read().view.draft,null);
});
