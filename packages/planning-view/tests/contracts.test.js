import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ContractError, validateDate, validateMessage, validateEvent} from '../src/contracts/index.js';

const snapshot = () => ({version:1,kind:'snapshot',scope:'view',revision:'r1',
  projects:[{id:'project-alpha',name:'Alpha'}],tasks:[{id:'task-build-1',projectId:'project-alpha',
    name:'Build',start:'2028-02-28',end:'2028-03-01',progress:0}]});

test('opaque identities, inclusive dates, and omitted resources survive independent copying', () => {
  const source=snapshot(), result=validateMessage(source);
  assert.deepEqual(result,source);
  result.tasks[0].name='Changed';
  assert.equal(source.tasks[0].name,'Build');
  assert.equal(validateDate('2028-02-29'),'2028-02-29');
});

for (const day of ['0000-01-01','2027-02-29','2028-02-30','2028-13-01','1/2/2028',null,1]) {
  test(`reject invalid calendar value ${day}`, () => assert.throws(()=>validateDate(day),ContractError));
}

const invalid = [
  x=>x.version=2, x=>x.scope='', x=>x.tasks.push({...x.tasks[0]}),
  x=>x.tasks[0].id=42, x=>x.tasks[0].end='2027-01-01',
  x=>x.tasks[0].progress=101, x=>x.tasks[0].projectId='missing',
  x=>x.projects[0].name=null, x=>x.capabilities={edit:'yes'},
  x=>x.labels={edit:true}, x=>x.extra=()=>{}, x=>x.extra=NaN,
  x=>x.extra=new Date(), x=>x.extra=x,
  x=>x.loadedProjectIds=['project-alpha','project-alpha'],
  x=>x.resources=[{id:'pool',name:'Pool',capacity:-1}],
  x=>x.hierarchy=[{id:'a',children:[{id:'a'}]}],
  x=>x.dependencies=[{id:'dep',type:'invalid',predecessor:{kind:'unavailable'},successor:{kind:'task',id:'task-build-1'}}],
];
invalid.forEach((mutate,index)=>test(`invalid snapshot ${index} leaves caller input unchanged`,()=>{
  const value=snapshot();mutate(value);
  const name=value.tasks[0].name;
  assert.throws(()=>validateMessage(value),ContractError);
  assert.equal(value.tasks[0].name,name);
}));

test('cyclic hierarchy rejects promptly without a recursive stack',()=>{
  const value=snapshot(),node={id:'pool'};node.children=[node];value.hierarchy=[node];
  assert.throws(()=>validateMessage(value),ContractError);
});

test('daily series retain explicit zero and absent days; unavailable endpoints stay unavailable',()=>{
  const value=snapshot();
  value.resources=[{id:'pool',name:'Pool',capacity:5,assignedCapacity:{'2028-02-29':0}}];
  value.dependencies=[{id:'edge',type:'FS',lagDays:-1,
    predecessor:{kind:'unavailable'},successor:{kind:'task',id:'task-build-1'}}];
  const result=validateMessage(value);
  assert.equal(result.resources[0].assignedCapacity['2028-02-29'],0);
  assert.equal(result.resources[0].assignedCapacity['2028-03-01'],undefined);
  assert.deepEqual(result.dependencies[0].predecessor,{kind:'unavailable'});
});

test('patches and correlated safe rejections have distinct envelopes',()=>{
  const base={version:1,scope:'view',revision:'r2'};
  assert.deepEqual(validateMessage({...base,kind:'patch',removeProjectIds:['project-alpha']}),
    {...base,kind:'patch',removeProjectIds:['project-alpha']});
  assert.equal(validateMessage({...base,kind:'response',requestId:'request',accepted:false,error:'Stale edit'}).accepted,false);
  assert.throws(()=>validateMessage({...base,kind:'response',accepted:true}),ContractError);
});

test('events preserve target identities and reject malformed ranges and progress',()=>{
  const base={version:1,scope:'view',revision:'r1',requestId:'event',type:'dates',
    targetId:'task-build-1',start:'2028-02-29',end:'2028-03-01'};
  assert.deepEqual(validateEvent(base),base);
  assert.throws(()=>validateEvent({...base,end:'2028-02-28'}),ContractError);
  assert.throws(()=>validateEvent({...base,type:'progress',progress:101}),ContractError);
  assert.throws(()=>validateEvent({...base,type:'unsupported'}),ContractError);
  assert.equal(validateEvent({...base,type:'command',command:'show-details'}).command,'show-details');
  assert.deepEqual(validateEvent({...base,type:'load',projectIds:['project-alpha']}).projectIds,['project-alpha']);
});

test('comparison records, hierarchy and localized capabilities retain their own copies',()=>{
  const value=snapshot();
  value.tasks[0].stableId='stable-build';
  value.overlays=[{id:'alternative-a',kind:'alternative',projectId:'project-alpha',
    tasks:[{...value.tasks[0],name:'Alternative'}],dependencies:[]}];
  value.hierarchy=[{id:'group',children:[{id:'leaf',resourceId:'pool'}]}];
  value.capabilities={edit:false};value.labels={edit:'Modifier'};value.reset=true;
  const result=validateMessage(value);
  assert.equal(result.overlays[0].tasks[0].stableId,'stable-build');
  assert.equal(result.hierarchy[0].children[0].resourceId,'pool');
  assert.equal(result.capabilities.edit,false);
  assert.equal(result.labels.edit,'Modifier');
  assert.equal(result.reset,true);
  assert.throws(()=>validateMessage({...value,overlays:[{...value.overlays[0],kind:'draft'}]}),ContractError);
});

test('internal ownership transfer validates caller-frozen graphs and preserves immutable independent data',async()=>{
  const {ownMessage}=await import('../src/contracts/owned.js');
  const input={version:1,kind:'snapshot',scope:'s',revision:'r',projects:[{id:'p',name:'P'}],tasks:[],resources:[{id:'r',name:'R',capacity:1,usage:{'2026-01-01':1}}]};
  const owned=ownMessage(input);assert.notEqual(owned,input);assert.equal(ownMessage(owned),owned);
  input.resources[0].usage['2026-01-01']=99;assert.equal(owned.resources[0].usage['2026-01-01'],1);
  assert.equal(Object.isFrozen(owned.resources[0].usage),true);
  assert.throws(()=>ownMessage(Object.freeze({...input,resources:[{id:'r',name:'R',capacity:1,usage:{'2026-02-30':1}}]})),ContractError);
  assert.throws(()=>ownMessage({...input,resources:[{id:'r',name:'R',capacity:1,usage:{'2026-01-01':NaN}}]}),ContractError);
  const cycle={};cycle.self=cycle;assert.throws(()=>ownMessage({...input,extra:cycle}),ContractError);
  const shared={safe:'value'};const aliases=ownMessage({...input,extra:[shared,shared]});assert.equal(aliases.extra[0],aliases.extra[1]);
  const fresh=validateMessage(owned);assert.notEqual(fresh,owned);fresh.resources[0].usage['2026-01-01']=3;assert.equal(owned.resources[0].usage['2026-01-01'],1);
});

test('owned schema validation checks the copied values and cannot be bypassed by changing accessors',()=>{
  const input=snapshot();let calls=0;
  Object.defineProperty(input.tasks[0],'name',{enumerable:true,get(){return ++calls===1?42:'Valid later';}});
  assert.throws(()=>validateMessage(input),ContractError);assert.equal(calls,1);
  const event={version:1,scope:'s',revision:'r',requestId:'id',type:'progress',targetId:'t'};
  Object.defineProperty(event,'progress',{enumerable:true,get:()=>NaN});assert.throws(()=>validateEvent(event),ContractError);
  const source=JSON.parse('{"version":1,"kind":"snapshot","scope":"s","revision":"r","projects":[],"tasks":[],"__proto__":{"polluted":true}}');
  const result=validateMessage(source);assert.equal(Object.hasOwn(result,'__proto__'),true);assert.equal(Object.getPrototypeOf(result),Object.prototype);assert.equal({}.polluted,undefined);
});

for(const day of ['0001-01-01','9999-12-31','2000-02-29','2400-02-29'])test('Gregorian date remains valid '+day,()=>assert.equal(validateDate(day),day));
for(const day of ['1900-02-29','2100-02-29','2026-04-31','2026-00-01','2026-13-01','2026-01-00'])test('Gregorian date remains invalid '+day,()=>assert.throws(()=>validateDate(day),ContractError));
