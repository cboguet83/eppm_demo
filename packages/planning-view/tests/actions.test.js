import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createActionController,canEdit,resolveTarget,validateActions,actionAllowed} from '../src/workspace/actions.js';
import {createPlanningStore} from '../src/state/store.js';
import {ContractError} from '../src/contracts/index.js';

const current={kind:'tasks',id:'task'};
const task=(id='task')=>({id,projectId:'project',stableId:'stable',name:'Task',start:'2026-01-01',end:'2026-01-03'});
const snapshot=()=>({version:1,kind:'snapshot',scope:'scope',revision:'r1',projects:[{id:'project',name:'Project'}],tasks:[task()],
  dependencies:[{id:'dep',type:'FS',predecessor:{kind:'unavailable'},successor:{kind:'task',id:'task'}}],capabilities:{edit:true}});
const patch=values=>({version:1,kind:'patch',scope:'scope',revision:'r1',...values});
function harness(input=snapshot(),options={}) {
  const store=createPlanningStore(input);store.setView({filters:{editEnabled:true}});let counter=0;const events=[];
  const actions=createActionController({store,onEvent:event=>events.push(event),requestId:()=>String(++counter),...options});
  return {store,actions,events};
}

test('task creation targets the displayed project alternative and captures its revision',()=>{
  const input=snapshot();input.projects[0].context={projectId:'project'};
  input.overlays=[{id:'alt',kind:'alternative',projectId:'project',editable:true,context:{planRevision:4},tasks:[]}];
  const h=harness(input);assert.equal(h.actions.openCreate(current),true);
  const draft=h.store.read().view.draft;assert.equal(draft.kind,'overlays');assert.equal(draft.id,'alt');assert.equal(draft.values.create,true);
  assert.equal(draft.values.target.id,'project');
  const event=h.actions.requestCreate(draft.values.target,{...draft.values.fields,name:'New step'});
  assert.equal(event.operation,'create');assert.equal(event.type,'task');assert.equal(event.overlayId,'alt');assert.equal(event.context.planRevision,4);
  assert.equal(event.targetKind,'projects');assert.equal(h.events.length,1);
  assert.equal(h.actions.requestCreate(draft.values.target,draft.values.fields),null);
  h.store.update({version:1,kind:'response',scope:'scope',revision:'r1',requestId:event.requestId,accepted:false,error:'Stale plan'});
  assert.equal(h.store.read().view.draft.values.fields.name,'');
  h.store.update(patch({capabilities:{edit:false}}));assert.equal(h.actions.openCreate(current),false);
  assert.equal(h.actions.requestCreate(draft.values.target,{...draft.values.fields,name:'Forbidden'}),null);
});

test('an open draft retains host revision context when authoritative metadata changes',()=>{
  const input=snapshot();input.tasks[0].context={projectId:'project',planRevision:4};
  const h=harness(input);h.actions.open(current);
  h.store.update(patch({tasks:[{...input.tasks[0],context:{projectId:'project',planRevision:5}}]}));
  const fields=h.store.read().view.draft.values.fields;
  const event=h.actions.request('task',current,{...fields,name:'Old draft'});
  assert.equal(event.context.planRevision,4);assert.equal(h.store.lookup('tasks','task').context.planRevision,5);
});

test('creation starts after the invoked task or the displayed project schedule and preserves phase defaults',()=>{
  const input=snapshot();input.projects[0].defaultPhase='Host default';input.tasks[0].phase='Task phase';
  const h=harness(input);h.actions.openCreate(current);
  assert.equal(h.store.read().view.draft.values.fields.phase,'Task phase');
  assert.equal(h.store.read().view.draft.values.fields.start,input.tasks[0].end);h.actions.close();
  h.actions.openCreate({kind:'projects',id:'project'});assert.equal(h.store.read().view.draft.values.fields.phase,'Host default');
});

test('edits are correlated once, reject safely and settle only on authoritative updates',()=>{
  const h=harness();assert.equal(h.actions.open(current),true);
  const event=h.actions.request('dates',current,{start:'2026-01-02',end:'2026-01-04'});
  assert.equal(h.events.length,1);assert.equal(event.targetId,'task');assert.equal(event.requestId,'1');
  assert.equal(h.store.lookup('tasks','task').start,'2026-01-01');
  assert.equal(h.actions.request('dates',current,{start:'2026-01-02',end:'2026-01-04'}),null);
  h.store.update({version:1,kind:'response',scope:'scope',revision:'r1',requestId:'1',accepted:false,error:'Stale'});
  assert.equal(h.store.read().view.error,'Stale');assert.equal(h.store.read().view.draft.id,'task');
  h.actions.request('task',current,{...h.store.read().view.draft.values.fields,name:'Changed'});
  h.store.update(patch({tasks:[{...task(),name:'Changed'}]}));
  h.store.update({version:1,kind:'response',scope:'scope',revision:'r1',requestId:'2',accepted:true});
  assert.equal(h.store.read().view.draft,null);assert.equal(h.store.lookup('tasks','task').name,'Changed');
});

test('malformed edits fail before pending state or host delivery',()=>{
  const h=harness();
  for(const [type,values] of [['dates',{start:'bad',end:'2026-01-02'}],['progress',{progress:101}],
    ['task',{description:42}],['task',{phase:[]}],['dependency',{type:'wrong'}]]) {
    const target=type==='dependency'?{kind:'dependencies',id:'dep'}:current;
    assert.throws(()=>h.actions.request(type,target,values),ContractError);
    assert.equal(h.store.read().view.pendingRequestId,null);assert.equal(h.events.length,0);
  }
});

test('revoked capabilities, opt-in mode and record hints are enforced by stale callers',()=>{
  const h=harness();assert.equal(h.actions.open(current),true);
  h.store.update(patch({capabilities:{edit:false}}));
  assert.equal(h.actions.open(current),false);assert.equal(h.actions.request('progress',current,{progress:100}),null);
  h.store.update(patch({capabilities:{edit:true,editDates:false,editProgress:false,editTasks:false}}));
  assert.equal(h.actions.request('dates',current,{start:'2026-01-02',end:'2026-01-04'}),null);
  assert.equal(h.actions.request('progress',current,{progress:50}),null);assert.equal(h.actions.open(current),false);
  h.store.update(patch({capabilities:{edit:true},tasks:[{...task(),editable:false}]}));assert.equal(h.actions.open(current),false);
  h.store.update(patch({tasks:[task()]}));h.store.setView({filters:{editEnabled:false}});assert.equal(h.actions.open(current),false);
  const {data,view}=h.store.read();assert.equal(canEdit(data,view,{kind:'tasks',id:'missing'}),false);
  assert.equal(resolveTarget(data,{kind:'unknown',id:'x'}),null);assert.equal(resolveTarget(data,null),null);
});

test('comparison edits target alternatives only and keep baselines immutable',()=>{
  const input=snapshot();input.overlays=[{id:'base',kind:'baseline',projectId:'project',tasks:[task('baseline')]},
    {id:'alt',kind:'alternative',projectId:'project',tasks:[task('alternative')],dependencies:[{...input.dependencies[0],successor:{kind:'task',id:'alternative'}}]}];
  const h=harness(input),alternative={kind:'tasks',id:'alternative',overlayId:'alt'};
  assert.equal(h.actions.open(current),false);assert.equal(h.actions.open({kind:'tasks',id:'baseline',overlayId:'base'}),false);
  assert.equal(h.actions.open(alternative),true);assert.equal(h.store.read().view.draft.kind,'overlays');
  assert.equal(h.store.read().view.draft.values.fields.dependencies.length,1);
  h.actions.request('progress',alternative,{progress:100});assert.equal(h.events[0].overlayId,'alt');assert.equal(h.events[0].lane,'alternative');
  const {data,view}=h.store.read();assert.equal(resolveTarget(data,{kind:'projects',id:'project',overlayId:'alt'}).record.name,'Project');
  assert.equal(resolveTarget(data,{kind:'tasks',id:'x',overlayId:'missing'}),null);
  assert.equal(canEdit(data,view,{kind:'tasks',id:'alternative',overlayId:'alt'},'unknown'),false);
  assert.equal(canEdit(data,view,{kind:'projects',id:'project'},'dates'),false);
  const denied=harness({...input,overlays:input.overlays.map(row=>({...row,editable:false}))});assert.equal(denied.actions.open(alternative),false);
});

test('dependency editing keeps link type inside values rather than replacing event type',()=>{
  const h=harness(),target={kind:'dependencies',id:'dep'};
  assert.equal(h.actions.open(target),true);
  const event=h.actions.request('dependency',target,{type:'SF',lagDays:-3,predecessor:{kind:'project',id:'project'}});
  assert.equal(event.type,'dependency');assert.equal(event.values.type,'SF');assert.equal(event.values.lagDays,-3);
});

test('commands and selections preserve opaque context and recheck action capabilities',()=>{
  const h=harness(),action={id:'host',label:'Host',capability:'manage',targetKinds:['tasks'],lanes:['current'],requiresEdit:true};
  assert.equal(h.actions.command(action,current),null);
  h.store.update(patch({capabilities:{edit:true,manage:true}}));
  assert.equal(h.actions.command(action,current,{start:'2026-01-01'}).context.start,'2026-01-01');
  assert.equal(h.actions.select(current).targetId,'task');assert.equal(h.store.read().view.selection.id,'task');
  assert.equal(actionAllowed({...action,lanes:['baseline']},h.store.read().data,h.store.read().view,current),false);
  assert.equal(actionAllowed({...action,targetKinds:['resources']},h.store.read().data,h.store.read().view,current),false);
  assert.equal(h.actions.command(action,{kind:'tasks',id:'missing'}),null);
  h.store.update(patch({capabilities:{edit:true,select:false}}));assert.equal(h.actions.select(current),null);
  assert.equal(h.actions.select({kind:'tasks',id:'missing'}),null);
  h.actions.close();h.actions.destroy();h.actions.destroy();
  assert.equal(h.actions.request('task',current,{}),null);assert.equal(h.actions.open(current),false);assert.equal(h.actions.select(current),null);assert.equal(h.actions.command(action,current),null);h.actions.close();
});

test('declarative context actions are copied, bounded and validated without executable content',()=>{
  const actions=[{id:'group',label:'Group',children:[{id:'child',label:'Child'}]}],checked=validateActions(actions);
  actions[0].label='Changed';assert.equal(checked[0].label,'Group');assert.deepEqual(validateActions(),[]);
  const cycle={id:'cycle',label:'Cycle'};cycle.children=[cycle];
  let deep={id:'8',label:'Deep'};for(let i=7;i>=0;i--)deep={id:String(i),label:'Deep',children:[deep]};
  for(const value of [null,[null],[{}],[{id:'a',label:'A'},{id:'a',label:'Duplicate'}],[cycle],[deep],
    [{id:'a',label:'A',capability:1}],[{id:'a',label:'A',lanes:[1]}],[{id:'a',label:'A',targetKinds:'tasks'}],
    [{id:'a',label:'A',requiresEdit:'yes'}],[{id:'a',label:'A',children:{}}],[{id:'a',label:'A',execute:()=>{}}]])assert.throws(()=>validateActions(value),ContractError);
});

test('sync and async host failures reconcile pending previews without exposing exceptions',async()=>{
  const h=harness(snapshot(),{onEvent:()=>{throw new Error('private');}});
  assert.throws(()=>h.actions.request('progress',current,{progress:50}),/private/);
  assert.equal(h.store.read().view.pendingRequestId,null);assert.equal(h.store.read().view.error,'The host could not process this action.');
  const other=harness(snapshot(),{onEvent:()=>Promise.reject(new Error('private'))});
  other.actions.request('progress',current,{progress:50});await Promise.resolve();await Promise.resolve();
  assert.equal(other.store.read().view.pendingRequestId,null);
  let reject;const pending=harness(snapshot(),{onEvent:()=>new Promise((_,fail)=>{reject=fail;})});
  pending.actions.request('progress',current,{progress:50});pending.actions.destroy();pending.store.destroy();reject(new Error('late'));await Promise.resolve();await Promise.resolve();
});

test('indexed targets invalidate replaced overlays and reject stale editors while a write is pending',()=>{
  const input=snapshot();input.resources=[{id:'resource',name:'Pool',capacity:2}];input.overlays=[{id:'alt',kind:'alternative',projectId:'project',tasks:[task('alternative')]}];
  const h=harness(input),target={kind:'tasks',id:'alternative',overlayId:'alt'};
  assert.equal(h.actions.resolve(target).record.name,'Task');assert.equal(h.actions.canEdit(target),true);
  assert.equal(h.actions.resolve({kind:'projects',id:'project',overlayId:'alt'}).record.name,'Project');
  assert.equal(h.actions.resolve({kind:'projects',id:'other',overlayId:'alt'}),null);
  assert.equal(h.actions.resolve({kind:'resources',id:'resource',overlayId:'alt'}),null);
  assert.equal(h.actions.resolve({kind:'resources',id:'resource'}).record.name,'Pool');
  assert.equal(h.actions.resolve({kind:'tasks',id:'alternative',overlayId:'missing'}),null);
  assert.equal(h.actions.resolve(null),null);assert.equal(h.actions.resolve({kind:'unknown',id:'task'}),null);
  h.store.update(patch({overlays:[{...input.overlays[0],tasks:[{...task('alternative'),name:'New'}]}]}));
  assert.equal(h.actions.resolve(target).record.name,'New');
  h.actions.request('progress',target,{progress:50});assert.equal(h.actions.open(target),false);
  h.actions.destroy();assert.equal(h.actions.resolve(target),null);assert.equal(h.actions.canEdit(target),false);
});
