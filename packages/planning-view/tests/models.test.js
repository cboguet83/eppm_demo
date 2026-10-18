import {test} from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {ContractError} from '../src/contracts/index.js';
import {addDays,dayIndex,dateFromIndex,timelineBounds,createCalendar,shiftTask} from '../src/calendar/index.js';
import {decodeIntervals,createResourceSummaries,formatResourceValue,capacityDetails} from '../src/resources/summary.js';

const options={start:'2023-01-01',end:'2024-04-01',mode:'Month',today:'2024-02-29'};
for (const [mode,count,width] of [['Month',15,675],['Quarter',5,140],['Year',4,160]]) {
  test(`${mode} period geometry preserves reference widths, leap and year boundaries`,()=>{
    const model=createCalendar({...options,mode});
    assert.equal(model.bottomCells.length,count);assert.equal(model.width,width);
    assert.equal(model.bottomCells[0].start,'2023-01-01');
    for (let i=1;i<count;i++) assert.equal(model.bottomCells[i].start,addDays(model.bottomCells[i-1].end,1));
    assert.equal(model.topCells.reduce((sum,c)=>sum+c.width,0),width);
    if(mode==='Month') assert.equal(model.bottomCells[13].end,'2024-02-29');
  });
}

test('short calendars fill the viewport and date endpoints match shared cell geometry',()=>{
  const model=createCalendar({...options,start:'2024-01-01',viewportWidth:1067});
  assert.equal(model.width,1067);
  for (const cell of model.bottomCells) {
    assert.ok(Math.abs(model.dateToX(cell.start)-cell.x)<1e-9);
    assert.ok(Math.abs(model.endDateToX(cell.end)-cell.x-cell.width)<1e-9);
  }
  assert.equal(model.dateAtX(model.dateToX('2024-02-29')),'2024-02-29');
  assert.equal(model.dateAtX(-1),'2023-12-31');
  assert.equal(model.dateAtX(model.width),'2024-04-01');
  const feb=model.bottomCells[1];
  assert.equal(model.dragDays(feb.x,feb.width/29),1);
  assert.equal(model.dragDays(feb.x,-feb.width/29),-1);
});

for (const mode of ['Day','Week']) test(`${mode} retains period labels, injected today and complete periods`,()=>{
  const calendar=createCalendar({...options,start:'2024-02-28',end:'2024-03-03',mode});
  assert.equal(calendar.bottomCells[0].label,mode==='Day'?'28':'W4');
  assert.ok(calendar.bottomCells.some(cell=>cell.isCurrent));
  assert.equal(calendar.topCells.length,mode==='Day'?2:1);
});

test('padding retains existing modes, overlays and empty schedule behavior',()=>{
  const rows=[{start:'2024-02-28',end:'2024-03-01'}],today='2026-10-18';
  const expected={Day:['2024-02-25','2024-03-16'],Week:['2024-02-14','2024-04-01'],
    Month:['2024-01-01','2024-07-01'],Quarter:['2024-01-01','2025-04-01'],Year:['2023-01-01','2026-01-01']};
  for (const [mode,[start,end]] of Object.entries(expected)) assert.deepEqual(timelineBounds(rows,mode,today),{start,end});
  assert.deepEqual(timelineBounds([],'Day','2024-01-01'),{start:'2024-01-01',end:'2024-03-31'});
  assert.equal(timelineBounds([{start:'2024-03-01',end:'2024-03-01'}],'Day',today).end,'2024-03-15');
});

test('move and resize retain inclusive duration, clamp edges and move milestones',()=>{
  const task={start:'2026-03-28',end:'2026-03-30'};
  assert.deepEqual(shiftTask(task,1),{start:'2026-03-29',end:'2026-03-31'});
  assert.deepEqual(shiftTask(task,9,'start'),{start:'2026-03-30',end:'2026-03-30'});
  assert.deepEqual(shiftTask(task,-9,'end'),{start:'2026-03-28',end:'2026-03-28'});
  assert.deepEqual(shiftTask({start:'2026-10-25',end:'2026-10-25'},1,'end'),{start:'2026-10-26',end:'2026-10-26'});
  assert.equal(task.start,'2026-03-28');
});

test('date arithmetic and geometry agree across UTC and Luxembourg transitions',()=>{
  const script=`import {addDays,createCalendar,shiftTask} from './packages/planning-view/src/calendar/index.js';
    const c=createCalendar({start:'2026-03-27',end:'2026-11-01',mode:'Day',today:'2026-10-25'});
    console.log(JSON.stringify([addDays('2026-03-28',2),shiftTask({start:'2026-10-24',end:'2026-10-26'},1),c.dateToX('2026-10-26'),c.dragDays(38,38)]));`;
  const run=TZ=>execFileSync(process.execPath,['--input-type=module','-e',script],{env:{...process.env,TZ},encoding:'utf8'});
  assert.equal(run('UTC'),run('Europe/Luxembourg'));
});

test('interval expansion retains zeroes and gaps and rejects malformed or excessive series',()=>{
  assert.deepEqual(decodeIntervals([['2028-02-28','2028-03-01',0],['2028-03-03','2028-03-03',4]]),
    {'2028-02-28':0,'2028-02-29':0,'2028-03-01':0,'2028-03-03':4});
  for (const input of [null,[[]],[['2024-01-02','2024-01-01',1]],
    [['2024-01-01','2024-01-02',1],['2024-01-02','2024-01-03',1]],
    [['2024-01-01','2024-01-01',-1]]]) assert.throws(()=>decodeIntervals(input),ContractError);
  assert.throws(()=>decodeIntervals([['2024-01-01','2024-01-03',1]],2),ContractError);
  assert.throws(()=>decodeIntervals([],0),ContractError);
  assert.deepEqual(decodeIntervals([]),{});
});

test('resource extrema use daily pairings, sparse overrides and independent cache ownership',()=>{
  const summaries=createResourceSummaries();
  const input={start:'2026-01-01',end:'2026-01-02',capacity:10,
    usage:{'2026-01-01':6,'2026-01-02':4},assignedCapacity:{'2026-01-02':2}};
  const expected={minCapacity:2,maxCapacity:10,maxDemand:6,maxExcess:2,isOverallocated:true,minAvailable:0};
  assert.deepEqual(summaries.summarize(input),expected);
  assert.equal(summaries.summarize(input),summaries.summarize(input));
  assert.ok(Object.isFrozen(summaries.summarize(input)));
  assert.notEqual(createResourceSummaries().summarize(input),summaries.summarize(input));
  const old=summaries.summarize(input);summaries.clear();assert.notEqual(summaries.summarize(input),old);
  assert.equal(summaries.summarize({...input,assignedCapacity:{'2026-01-01':0,'2026-01-02':1}}).maxCapacity,1);
  assert.equal(summaries.summarize({...input,usage:{},assignedCapacity:{'2026-01-02':0}}).minCapacity,0);
  assert.equal(summaries.summarize({...input,usage:{},assignedCapacity:{}}).minAvailable,10);
  assert.equal(summaries.summarize({...input,usage:{'2026-01-01':1},assignedCapacity:{'2026-01-02':2}}).minAvailable,2);
  assert.equal(summaries.summarize({start:input.start,end:input.end,capacity:0}).maxExcess,0);
  assert.equal(summaries.summarize({...input,usage:{},capacity:3}).maxDemand,0);
});

test('resource scopes use identical rules and values keep established display precision',()=>{
  const summaries=createResourceSummaries(),common={start:'2026-01-01',end:'2026-01-02',capacity:3};
  assert.deepEqual([6,2,4].map(amount=>summaries.summarize({...common,usage:{'2026-01-01':amount}}).isOverallocated),[true,false,true]);
  assert.deepEqual([0,1.24,99.99,100.4,101.6].map(formatResourceValue),['0.0','1.2','100.0','100','102']);
  assert.throws(()=>formatResourceValue(-1),ContractError);
  assert.throws(()=>summaries.summarize({...common,capacity:-1}),ContractError);
  assert.throws(()=>summaries.summarize({...common,end:'2025-01-01'}),ContractError);
});

test('capacity hover summaries include only differing assigned extrema and remain plain text',()=>{
  const pool={name:'Pool <A>',capacity:2,definedCapacity:2,hasAssignments:true};
  assert.equal(capacityDetails(pool,{minCapacity:2,maxCapacity:2}),'Pool <A>');
  assert.equal(capacityDetails(pool,{minCapacity:1,maxCapacity:4}),'Pool <A>\nDefined capacity: 2.0 FTE\nMin assigned capacity: 1.0 FTE\nMax assigned capacity: 4.0 FTE');
  assert.equal(capacityDetails(pool,{minCapacity:1,maxCapacity:2}),'Pool <A>\nDefined capacity: 2.0 FTE\nMin assigned capacity: 1.0 FTE');
  assert.equal(capacityDetails(pool,{minCapacity:2,maxCapacity:4}),'Pool <A>\nDefined capacity: 2.0 FTE\nMax assigned capacity: 4.0 FTE');
  assert.equal(capacityDetails({...pool,hasAssignments:false},{minCapacity:0,maxCapacity:4}),'Pool <A>');
  assert.match(capacityDetails({...pool,definedCapacity:undefined},{minCapacity:1,maxCapacity:2},{unit:'people',labels:{definedCapacity:'Defined',minAssignedCapacity:'Minimum'}}),/Defined: 2.0 people\nMinimum: 1.0 people/);
});

test('invalid geometry and dates fail safely at pure model interfaces',()=>{
  for (const date of ['0000-01-01','2027-02-29','bad']) assert.throws(()=>dayIndex(date),ContractError);
  for (const day of [Infinity,1.1,1e20,-1e20]) assert.throws(()=>dateFromIndex(day),ContractError);
  for (const patch of [{mode:'bad'},{end:options.start},{viewportWidth:-1},{maxPeriods:0},{maxPeriods:1},{months:[]}]) {
    assert.throws(()=>createCalendar({...options,...patch}),ContractError);
  }
  assert.throws(()=>createCalendar(options).dateAtX(NaN),ContractError);
  assert.throws(()=>timelineBounds([{start:'2024-02-01',end:'2024-01-01'}],'Day',options.today),ContractError);
  assert.throws(()=>timelineBounds([],'bad',options.today),ContractError);
  assert.throws(()=>shiftTask({start:options.start,end:options.end},0.5),ContractError);
});
