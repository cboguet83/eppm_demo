const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname,'../app/presentation/assets/components/gantt/index.html'),'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

function harness() {
  const timers=[], messages=[];
  const context=vm.createContext({setTimeout:(fn,delay)=>{timers.push({fn,delay});return timers.length;},
    Streamlit:{setComponentValue:value=>messages.push(value)},
    masterRenderItems:[],allTaskPositions:{},renderedRowWindow:{start:0,end:10},
    sortTasksList:tasks=>tasks,parseDate:day=>new Date(day),dateToX:date=>date.getUTCDate(),endDateToX:date=>date.getUTCDate()+1,
    buildDependencyIndex(){},renderVirtualWindow(){},renderTimeline(){},
    resourcePoolsData:[],groupUsageCache:new Map(),openProjectDiagModal(){},
  });
  const run=code=>vm.runInContext(code,context);
  run(script.slice(script.indexOf('    let tasksData ='),script.indexOf('    let resourcePoolsData =')));
  return {run,context,timers,messages};
}

test('project requests are bounded, coalesced and reject stale scope responses',()=>{
  const h=harness();
  h.run(`lazyProjects=true; planningScopeToken='current';
    masterRenderItems=Array.from({length:100},(_,i)=>({type:'project_header',project_id:String(i+1),isCollapsed:false}));
    scheduleProjectLoads(0,99); scheduleProjectLoads(0,99);`);
  assert.equal(h.timers.length,1);
  h.timers.shift().fn();
  assert.equal(h.messages.length,1);
  assert.equal(h.messages[0].project_ids.length,25);
  h.run('scheduleProjectLoads(20,60)');
  assert.equal(h.messages.length,1);
  h.run("applyPlanningPatch({scope_token:'old',tasks:[{id:'bad'}],loaded_project_ids:[999]})");
  assert.equal(h.run('tasksData.length'),0);
  assert.equal(h.run('loadedProjectIds.size'),0);
});

test('hydration updates only reserved project rows and eviction restores placeholders',()=>{
  const h=harness();
  h.run(`planningScopeToken='current'; lazyProjects=true;
    projectTaskWindows.set('1',{start:1,end:3}); projectTaskWindows.set('2',{start:4,end:5});
    masterRenderItems=[{project_id:'1'},{type:'loading',project_id:'1'},{type:'loading',project_id:'1'},
      {project_id:'2'},{type:'task',task:{id:'21',project_id:'2'}}];
    tasksData=[masterRenderItems[4].task]; const untouched=masterRenderItems[4];
    applyPlanningPatch({scope_token:'current',replace_projects:[1],loaded_project_ids:[1,2],tasks:[
      {id:'11',project_id:'1',start:'2026-01-01',end:'2026-01-02'},
      {id:'12',project_id:'1',start:'2026-01-03',end:'2026-01-03'}]});`);
  assert.equal(h.run('masterRenderItems[4]===untouched'),true);
  assert.equal(h.run('masterRenderItems[1].task.id'),'11');
  assert.equal(h.run('allTaskPositions[12].rowIdx'),2);
  assert.equal(h.run('tasksData.length'),3);
  h.run("applyPlanningPatch({scope_token:'current',replace_projects:[],evict_project_ids:[1],loaded_project_ids:[2],tasks:[]})");
  assert.equal(h.run('tasksData.length'),1);
  assert.equal(h.run('masterRenderItems[1].type'),'loading');
  assert.equal(h.run('Object.keys(allTaskPositions).length'),0);
});

test('interval transport restores zero capacity and missing-day gaps exactly',()=>{
  const h=harness();
  const result=h.run(`unpackPoolData({daily_assigned_capacity_intervals:[
    ['2026-03-28','2026-03-30',0],['2026-04-02','2026-04-02',4]]})`);
  assert.deepEqual({...result.daily_assigned_capacity},{'2026-03-28':0,'2026-03-29':0,'2026-03-30':0,'2026-04-02':4});
  assert.equal(result.daily_assigned_capacity_intervals,undefined);
});
