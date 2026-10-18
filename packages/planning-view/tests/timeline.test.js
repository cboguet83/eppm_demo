import {test} from 'node:test';
import assert from 'node:assert/strict';
import {projectRows,pairTasks,summarizeDates,rowWindow,ROW_HEIGHT} from '../src/timeline/rows.js';
import {createPlanningStore} from '../src/state/store.js';
import {ContractError} from '../src/contracts/index.js';

const task=(id,stableId,extra={})=>({id,stableId,projectId:'p',name:id,start:'2026-01-01',end:'2026-01-03',...extra});
const snapshot=()=>({version:1,kind:'snapshot',scope:'s',revision:'r',projects:[{id:'p',name:'Zebra'},{id:'q',name:'Apple',taskCount:2}],tasks:[task('live','stable')],
  overlays:[{id:'baseline',projectId:'p',kind:'baseline',tasks:[task('previous','stable',{name:'Renamed'}),task('removed','removed')]},
    {id:'alt',projectId:'p',kind:'alternative',tasks:[task('other-id','stable'),task('added','added')]}]});

test('comparison pairing uses stable identity and retains current, removed and added rows',()=>{
  const data=snapshot(),rows=pairTasks(data.tasks,data.overlays);
  assert.equal(rows.length,3);assert.equal(rows[0].record.id,'live');
  assert.deepEqual(rows[0].comparisons.map(item=>item.task.id),['previous','other-id']);
  assert.equal(rows[1].current,null);assert.equal(rows[1].record.id,'removed');
  assert.equal(rows[2].record.id,'added');assert.equal(new Set(rows.map(row=>row.key)).size,3);
  assert.equal(pairTasks([task('opaque',undefined)],[])[0].record.id,'opaque');
  assert.equal(summarizeDates([]),null);
  assert.deepEqual(summarizeDates([task('1','1'),task('2','2',{start:'2025-01-01',end:'2027-01-01'})]),{start:'2025-01-01',end:'2027-01-01'});
});

test('grouped projection preserves boundaries, summary ranges, expansion and lazy placeholders',()=>{
  const store=createPlanningStore({...snapshot(),loadedProjectIds:['p']});
  let {data,view}=store.read();let projection=projectRows(data,view);
  assert.deepEqual(projection.rows.map(row=>row.kind),['project','project']);
  assert.deepEqual(projection.rows[0].summary,{start:'2026-01-01',end:'2026-01-03'});
  assert.equal(projection.rows[1].summary,null);assert.equal(projection.rows[1].taskCount,2);
  store.setView({expandedProjects:['p','q']});({view}=store.read());projection=projectRows(data,view);
  assert.deepEqual(projection.rows.map(row=>row.kind),['project','task','task','task','project','loading','loading']);
  assert.equal(projection.taskIndexes.get('live'),2); // added is earlier in the equal-date opaque-ID sort.
  assert.equal(projection.projectIndexes.get('q'),4);
  assert.equal(projection.comparisonIndexes.get(JSON.stringify(['alt','added'])),1);
  assert.equal(projection.rows[0].comparisons.length,2);
  const ungrouped=projectRows(data,view,{grouped:false});assert.equal(ungrouped.rows.length,5);assert.equal(ungrouped.projectIndexes.size,0);
});

test('sorting, text filtering and task ordering never mix project groups',()=>{
  const store=createPlanningStore(snapshot());
  store.setView({expandedProjects:['p','q'],filters:{sort:{field:'name',direction:'asc'},taskSort:{field:'name',direction:'desc'}}});
  let {data,view}=store.read();let projection=projectRows(data,view);
  assert.equal(projection.rows[0].projectId,'q');assert.equal(projection.rows[1].projectId,'p');
  assert.equal(projection.rows[2].record.id,'removed');
  store.setView({filters:{query:'ZEB',projectIds:['p'],sort:{field:'nonsense',direction:'none'}}});
  ({view}=store.read());assert.equal(projectRows(data,view).rows.length,4);
  store.setView({filters:{sort:{field:'name',direction:'desc'}}});({view}=store.read());
  assert.equal(projectRows(data,view).rows[0].projectId,'p');
  const dated={...data,projects:[{id:'p',name:'P',start:'2020-01-01',end:'2030-01-01'}]};
  assert.equal(projectRows(dated,view).rows[0].summary.start,'2020-01-01');
});

test('virtual windows stay bounded at top, middle, end and empty schedules',()=>{
  for(const top of [0,4000,ROW_HEIGHT*100000]) {
    const window=rowWindow(100000,top,280);
    assert.ok(window.end-window.start+1<=39);assert.ok(window.start>=0);assert.ok(window.end<100000);
  }
  assert.equal(rowWindow(0,0,280).end,-1);
  for(const args of [[-1,0,280],[1,-1,280],[1,0,NaN],[1,0,280,-1]])assert.throws(()=>rowWindow(...args),ContractError);
});

test('renderer boundary fields reject invalid summaries and ambiguous stable identities',()=>{
  for(const value of [{...snapshot(),projects:[{id:'p',name:'P',start:'bad',end:'bad'}]},
    {...snapshot(),projects:[{id:'p',name:'P',taskCount:-1}]},
    {...snapshot(),tasks:[task('a','same'),task('b','same')]}])assert.throws(()=>createPlanningStore(value),ContractError);
});
