import {test} from 'node:test';
import assert from 'node:assert/strict';
import {resourceRows,resourceCell,resourceWindow,RESOURCE_ROW_HEIGHT,demandSeries} from '../src/resources/rows.js';
import {createResourceSummaries} from '../src/resources/summary.js';
import {createPlanningStore} from '../src/state/store.js';
import {createActionController,resolveTarget} from '../src/workspace/actions.js';
import {createCalendar} from '../src/calendar/index.js';
import {ContractError} from '../src/contracts/index.js';

const calendar=createCalendar({start:'2026-01-01',end:'2026-03-01',mode:'Month',today:'2026-01-01'});
const resource=(id='pool',extra={})=>({id,name:id,capacity:10,usage:{'2026-01-01':6,'2026-01-02':4},assignedCapacity:{'2026-01-02':2},selectedUsage:{'2026-01-02':3},...extra});
const snapshot=()=>({version:1,kind:'snapshot',scope:'s',revision:'r',projects:[],tasks:[],resources:[resource()]});
function fixture(input=snapshot(),filters={},collapsedResources=[]) {
  const store=createPlanningStore(input);store.setView({filters:{resources:filters},collapsedResources});
  const {data,view}=store.read(),summaries=createResourceSummaries(),model=resourceRows(data,view,calendar,summaries);
  return {store,data,view,summaries,model};
}

test('assigned, total and selected rows retain daily extrema and independent excess',()=>{
  const h=fixture();assert.deepEqual(h.model.rows.map(row=>row.scope),['assigned','total','selected']);
  const results=h.model.rows.map(row=>resourceCell(row,calendar.bottomCells[0],h.model.pools,h.summaries));
  assert.equal(results[0].value,2);assert.equal(results[1].value,6);assert.equal(results[1].maxExcess,2);
  assert.equal(results[2].value,3);assert.equal(results[2].maxExcess,1);assert.equal(results[2].isOverallocated,true);
  assert.deepEqual(demandSeries(resource(),'selected',true),{});
  assert.deepEqual(demandSeries({id:'zero'},'selected'),{});assert.deepEqual(demandSeries({id:'zero'},'total'),{});
});

test('hierarchy visibility, expansion and group warnings preserve nonfungible capacities',()=>{
  const input=snapshot();input.resources.push(resource('unused',{usedBySelection:false}),resource('balanced',{capacity:100,usage:{},selectedUsage:{},assignedCapacity:{}}));
  input.hierarchy=[{id:'root',name:'Organization',children:[{id:'nested',name:'Team',children:[{id:'leaf',resourceId:'pool'},{id:'hidden',resourceId:'unused'}]},
    {id:'balanced-leaf',resourceId:'balanced'},{id:'missing',resourceId:'missing'}]}];
  const h=fixture(input);assert.equal(h.model.pools.size,2);assert.equal(h.model.rows.length,8);
  assert.equal(h.model.rows[0].node.id,'root');assert.equal(h.model.rows[1].node.id,'nested');assert.equal(h.model.rows[2].depth,2);
  assert.equal(resourceCell(h.model.rows[0],calendar.bottomCells[0],h.model.pools,h.summaries).isOverallocated,true);
  assert.deepEqual(h.model.descendants.get('root'),['pool','balanced']);
  assert.equal(fixture(input,{},['root']).model.rows.length,1);
  const collapsed=fixture(input,{},['leaf']);assert.equal(collapsed.model.rows[2].scope,'total');assert.equal(collapsed.model.rows[2].collapsed,true);
  assert.equal(fixture(input,{showTotal:false,showSelected:false}).model.rows.length,4);
  assert.equal(fixture(input,{hideUnused:false}).model.pools.size,3);
  assert.equal(fixture(input,{onlyOverallocated:true}).model.pools.size,1);
});

test('comparison rows appear only for different displayed demand and can make unused pools visible',()=>{
  const input=snapshot();input.resources=[resource('pool',{usedBySelection:false,comparisonUsage:{total:{'2026-01-01':6.01},selected:{'2026-01-02':4}}})];
  input.hierarchy=[{id:'group',children:[{id:'leaf',resourceId:'pool'}]}];
  const h=fixture(input);assert.equal(h.model.pools.size,1);
  assert.deepEqual(h.model.rows.map(row=>[row.scope,row.comparison]),[['total',false],['assigned',false],['total',false],['selected',false],['selected',true]]);
  const last=resourceCell(h.model.rows.at(-1),calendar.bottomCells[0],h.model.pools,h.summaries);
  assert.equal(last.value,4);assert.equal(last.maxExcess,2);
  input.resources[0].comparisonUsage.total={'2026-01-01':11};
  const differing=fixture(input);assert.equal(differing.model.rows[1].comparison,true);
  assert.equal(resourceCell(differing.model.rows[1],calendar.bottomCells[0],differing.model.pools,differing.summaries).isOverallocated,true);
  assert.equal(fixture(input,{onlyOverallocated:true}).model.pools.size,1);
});

test('row and column windows remain bounded independently on very large grids',()=>{
  const scale=createCalendar({start:'2026-01-01',end:'2030-01-01',mode:'Day',today:'2026-01-01'});
  for(const top of [0,20000,RESOURCE_ROW_HEIGHT*100000]) {
    const window=resourceWindow(100000,top,324,scale.bottomCells,20000,900);
    assert.ok(window.end-window.start+1<=28);assert.ok(window.colLast-window.colFirst+1<=30);
    assert.ok(window.start>=0);assert.ok(window.end<100000);
  }
  assert.equal(resourceWindow(0,0,50,[],0,900).end,-1);
  for(const args of [[-1,0,324,[],0,900],[1,NaN,324,[],0,900],[1,0,-1,[],0,900],[1,0,324,[],-1,900]])assert.throws(()=>resourceWindow(...args),ContractError);
});

test('nested group selections use actual opaque hierarchy IDs and reset independent scroll',()=>{
  const h=fixture({...snapshot(),hierarchy:[{id:'organization',children:[{id:'group',name:'Team',children:[{id:'leaf',resourceId:'pool'}]}]}]});
  const events=[],actions=createActionController({store:h.store,onEvent:event=>events.push(event)}),target={kind:'hierarchy',id:'group'};
  assert.equal(h.store.lookup('hierarchy','group').name,'Team');assert.equal(resolveTarget(h.data,target).record.name,'Team');
  actions.select(target,{scope:'selected',start:'2026-01-01',end:'2026-01-31'});
  assert.equal(events[0].targetId,'group');assert.equal(events[0].context.scope,'selected');assert.equal(h.store.read().view.selection.kind,'hierarchy');
  h.store.setView({resourceScrollTop:200});
  h.store.update({...snapshot(),scope:'other'});assert.equal(h.store.read().view.resourceScrollTop,0);assert.equal(h.store.read().view.selection,null);
});

test('resource display metadata rejects malformed capacity, comparison series and flags',()=>{
  for(const changes of [{definedCapacity:-1},{usedBySelection:1},{hasAssignments:'yes'},{comparisonUsage:[]},{comparisonUsage:{selected:{bad:3}}}]) {
    assert.throws(()=>fixture({...snapshot(),resources:[resource('pool',changes)]}),ContractError);
  }
  assert.throws(()=>fixture({...snapshot(),hierarchy:[{id:'group',name:42}]}),ContractError);
  assert.equal(fixture({...snapshot(),resources:[resource('pool',{definedCapacity:12,hasAssignments:true})]}).model.rows.length,3);
  for(const resourceFilter of [{},{resourceId:1},{groupId:'g',clearAction:1},{resourceId:'pool',name:42},{resourceId:'pool',start:'bad',end:'bad'}])assert.throws(()=>fixture({...snapshot(),resourceFilter}),ContractError);
  assert.equal(fixture({...snapshot(),resourceFilter:{resourceId:'pool',name:'Pool',clearAction:'clear',start:'2026-01-01',end:'2026-01-31'}}).model.rows.length,3);
  const h=fixture({...snapshot(),resourceFilter:{groupId:'group'}});
  h.store.update({version:1,kind:'patch',scope:'s',revision:'r',resourceFilter:null});assert.equal(h.store.read().data.resourceFilter,null);
});

test('legacy visibility composes selected-project usage, ancestors, changed selections and daily warnings',()=>{
  const pools=[resource('1',{usedBySelection:true,capacity:4,usage:{'2026-01-02':3},selectedUsage:{},assignedCapacity:{}}),
    resource('2',{usedBySelection:false,capacity:4,usage:{'2026-01-02':1},selectedUsage:{},assignedCapacity:{'2026-01-02':0}}),
    resource('3',{usedBySelection:true,capacity:4,usage:{'2026-01-02':5},selectedUsage:{},assignedCapacity:{}})];
  const input={...snapshot(),resources:pools,hierarchy:[{id:'root',children:[{id:'nested',children:[{id:'leaf1',resourceId:'1'}]},{id:'empty',children:[{id:'leaf2',resourceId:'2'}]},{id:'leaf3',resourceId:'3'}]}]};
  assert.deepEqual([...fixture(input,{hideUnused:false,onlyOverallocated:true}).model.pools.keys()],['2','3']);
  assert.deepEqual([...fixture(input,{onlyOverallocated:true}).model.pools.keys()],['3']);
  const first=fixture({...input,resources:pools.slice(0,2)});
  assert.deepEqual(first.model.rows.map(row=>row.node.id),['root','nested','leaf1','leaf1','leaf1']);
  assert.equal(fixture({...input,resources:pools.slice(0,2)},{},['nested']).model.rows.length,2);
  const changed={...input,resources:[{...pools[0],usedBySelection:false},{...pools[1],usedBySelection:true}]};
  assert.deepEqual(fixture(changed).model.rows.map(row=>row.node.id),['root','empty','leaf2','leaf2','leaf2']);
  assert.equal(fixture({...changed,resources:changed.resources.map(pool=>({...pool,usedBySelection:false}))}).model.rows.length,0);
  const compare={...snapshot(),resources:[resource('pool',{capacity:4,usage:{'2026-01-01':2,'2026-01-02':1},comparisonUsage:{total:{'2026-01-01':1,'2026-01-02':2}}})]};
  assert.equal(fixture(compare).model.rows.filter(row=>row.comparison).length,0);
  const h=fixture(compare),day=createCalendar({start:'2026-01-01',end:'2026-01-02',mode:'Day',today:'2026-01-01'});
  assert.equal(resourceRows(h.data,h.view,day,h.summaries).rows.filter(row=>row.comparison).length,1);
  const feb=createCalendar({start:'2026-02-01',end:'2026-02-02',mode:'Day',today:'2026-02-01'});
  const scoped=fixture(input,{onlyOverallocated:true});assert.equal(resourceRows(scoped.data,scoped.view,feb,scoped.summaries).rows.length,0);
});
