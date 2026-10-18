import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createDependencyIndex,layoutDependencies,inspectDependency} from '../src/timeline/dependencies.js';
import {projectRows,ROW_HEIGHT} from '../src/timeline/rows.js';
import {createCalendar} from '../src/calendar/index.js';
import {createPlanningStore} from '../src/state/store.js';
import {ContractError} from '../src/contracts/index.js';

const task=(id,projectId='p',extra={})=>({id,projectId,stableId:id,name:id,start:'2026-01-02',end:'2026-01-04',...extra});
const endpoint=id=>({kind:'task',id});
const dependency=(id,type='FS',extra={})=>({id,type,predecessor:endpoint('a'),successor:endpoint('b'),lagDays:2,...extra});
const initial=()=>({version:1,kind:'snapshot',scope:'s',revision:'r',projects:[{id:'p',name:'P'},{id:'q',name:'Q'}],tasks:[task('a'),task('b','q')],dependencies:[]});
const calendar=createCalendar({start:'2026-01-01',end:'2026-02-01',mode:'Day',today:'2026-01-01'});
function fixture(input=initial(),expandedProjects=['p','q']) {
  const store=createPlanningStore(input);store.setView({expandedProjects});
  const {data,view}=store.read(),projection=projectRows(data,view),index=createDependencyIndex(data,projection);
  return {data,projection,index,window:{start:0,end:projection.rows.length-1}};
}

test('all link types retain edge geometry, lag, violations and independent inspection',()=>{
  const h=fixture({...initial(),dependencies:['FS','SS','FF','SF'].map(type=>dependency(type,type,{violated:type==='SF',diagnostics:['Delivered issue']}))});
  const entries=h.index.query(0,3),bundles=layoutDependencies(entries,calendar,h.window);
  assert.equal(h.index.size,4);assert.equal(bundles.length,4);
  const paths=Object.fromEntries(bundles.map(bundle=>[bundle.members[0].dependency.type,bundle.path]));
  assert.ok(paths.FS.startsWith('M 152 '));assert.ok(paths.SS.startsWith('M 38 '));
  assert.ok(paths.FF.endsWith('H 152'));assert.ok(paths.SF.endsWith('H 152'));
  const details=inspectDependency(entries.find(entry=>entry.dependency.type==='SF'));
  assert.equal(details.lagDays,2);assert.deepEqual(details.diagnostics,['Delivered issue']);assert.equal(details.violated,true);
  assert.equal(details.predecessor.name,'a');assert.equal(details.successor.start,'2026-01-02');
});

test('collapsed paths bundle every underlying record and omit internal self-summary links',()=>{
  const input=initial();input.tasks.push(task('c'));
  input.dependencies=[dependency('one'),dependency('two'),dependency('inside','FS',{successor:endpoint('c')}),
    dependency('project','FS',{predecessor:{kind:'project',id:'p'},successor:{kind:'project',id:'q'}})];
  const h=fixture(input,[]),bundles=layoutDependencies(h.index.query(0,1),calendar,h.window);
  assert.equal(h.index.size,3);assert.equal(bundles.length,1);assert.equal(bundles[0].members.length,3);
  assert.equal(inspectDependency(bundles[0].members.find(entry=>entry.dependency.id==='project')).predecessor.name,'P');
  assert.deepEqual(layoutDependencies(h.index.query(0,1),calendar,h.window,{externalLinks:false}),[]);
});

test('unavailable, undelivered and undated endpoints never invent hidden metadata',()=>{
  const input=initial();input.dependencies=[dependency('hidden','FS',{predecessor:{kind:'unavailable',name:'Do not reveal'}}),
    dependency('not-loaded','SS',{predecessor:{kind:'task',id:'missing',projectId:'p'}}),
    dependency('missing-successor','FS',{successor:{kind:'unavailable'}}),
    dependency('neither','FS',{predecessor:{kind:'unavailable'},successor:{kind:'unavailable'}})];
  const h=fixture(input,[]),entries=h.index.query(0,1);
  assert.equal(h.index.size,3);
  assert.deepEqual(inspectDependency(entries.find(entry=>entry.dependency.id==='hidden')).predecessor,{kind:'unavailable'});
  assert.deepEqual(inspectDependency(entries.find(entry=>entry.dependency.id==='not-loaded')).predecessor,{kind:'task',id:'missing'});
  assert.equal(layoutDependencies(entries,calendar,h.window).length,3);
  const noDates=fixture({...initial(),tasks:[],dependencies:[dependency('empty','FS',{predecessor:{kind:'project',id:'p'},successor:{kind:'project',id:'q'}})]},[]);
  assert.equal(noDates.index.size,0);
});

test('interval candidates include crossing paths while excluding distant unrelated edges',()=>{
  const input=initial();input.projects=input.projects.slice(0,1);
  input.tasks=Array.from({length:2000},(_,i)=>task(String(i)));
  input.dependencies=input.tasks.slice(1).map((task,i)=>dependency('edge-'+i,'FS',{predecessor:endpoint(String(i)),successor:endpoint(task.id)}));
  input.dependencies.push(dependency('crossing','FS',{predecessor:endpoint('0'),successor:endpoint('1999')}));
  const h=fixture(input,['p']),entries=h.index.query(800,830);
  assert.ok(entries.length<=33);assert.ok(entries.some(entry=>entry.dependency.id==='crossing'));
  const bundles=layoutDependencies(entries,calendar,{start:800,end:830});
  for(const bundle of bundles){assert.ok(bundle.y>=800*ROW_HEIGHT);assert.ok(bundle.y<=831*ROW_HEIGHT);}
  assert.equal(layoutDependencies(entries,calendar,{start:800,end:830},{internalLinks:false}).length,0);
});

test('comparison endpoints use overlay identity, stable rows and current external fallback lanes',()=>{
  const input=initial();input.overlays=[{id:'alt',kind:'alternative',projectId:'p',tasks:[task('old-id','p',{stableId:'a',start:'2026-01-03'})],
    dependencies:[dependency('alternative','SS',{predecessor:endpoint('old-id')}),dependency('project-alt','SF',{predecessor:{kind:'project',id:'p'}})]}];
  const h=fixture(input),entries=h.index.query(0,3),bundles=layoutDependencies(entries,calendar,h.window);
  assert.equal(bundles.length,2);assert.equal(entries[0].predecessor.lane,'alternative');assert.equal(entries[0].successor.lane,'current');
  const alternative=entries.find(entry=>entry.dependency.id==='alternative');
  assert.equal(inspectDependency(alternative).predecessor.id,'old-id');assert.equal(inspectDependency(alternative).lane,'alternative');
  const milestone=fixture({...initial(),tasks:[task('a','p',{end:'2026-01-02'}),task('b','q',{end:'2026-01-02'})],dependencies:[dependency('m','SF')]});
  assert.ok(layoutDependencies(milestone.index.query(0,3),calendar,milestone.window)[0].path.startsWith('M 29 '));
});

test('optional diagnostic and endpoint metadata is validated before render state changes',()=>{
  const allowed=dependency('valid','FS',{violated:false,evaluable:false,external:true,diagnostics:[{message:'Safe'}]});
  assert.equal(fixture({...initial(),dependencies:[allowed]}).index.size,1);
  for(const fields of [{violated:'yes'},{evaluable:1},{external:null},{diagnostics:'bad'},{diagnostics:[null]},
    {predecessor:{kind:'task',id:'a',projectId:42}}])assert.throws(()=>fixture({...initial(),dependencies:[dependency('bad','FS',fields)]}),ContractError);
});
