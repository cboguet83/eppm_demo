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

test('HTTP task batches hydrate rows without Streamlit reruns and keep a bounded working set', async()=>{
  const h=harness(), requests=[];
  h.context.AbortController=AbortController;
  h.context.fetch=async(url,options)=>{
    requests.push({url, ...JSON.parse(options.body)});
    return {ok:true,status:200,json:async()=>({scope_token:'current',nonce:'batch',replace_projects:[101],tasks:[]})};
  };
  h.run(`planningTaskEndpoint='/api/planning/tasks'; planningTaskRevision='revision'; planningScopeToken='current';
    loadedProjectIds=new Set(Array.from({length:100},(_,i)=>String(i+1))); planningPendingRequest='batch';`);
  await h.run("requestPlanningTasks(['101'],'batch')");
  assert.equal(requests.length,1);
  assert.deepEqual(requests[0].project_ids,[101]);
  assert.equal(requests[0].revision,'revision');
  assert.equal(h.messages.length,0);
  assert.equal(h.run('loadedProjectIds.size'),100);
  assert.equal(h.run("loadedProjectIds.has('1')"),false);
  assert.equal(h.run("loadedProjectIds.has('101')"),true);
  assert.equal(h.run('planningPendingRequest'),null);
});

test('slow HTTP reads stay single-flight and late responses cannot overwrite another scope', async()=>{
  const h=harness(); let resolve, calls=0;
  h.context.AbortController=AbortController;
  h.context.fetch=()=>{calls++;return new Promise(done=>{resolve=done;});};
  h.run(`lazyProjects=true; planningTaskEndpoint='/api/planning/tasks'; planningTaskRevision='revision'; planningScopeToken='current';
    masterRenderItems=Array.from({length:100},(_,i)=>({type:'project_header',project_id:String(i+1),isCollapsed:false}));
    scheduleProjectLoads(0,20);`);
  h.timers.shift().fn();
  h.run('scheduleProjectLoads(40,60);scheduleProjectLoads(60,90)');
  assert.equal(calls,1);
  assert.equal(h.timers.length,0); // No three-second retry can cancel a slow read.
  h.run("planningScopeToken='new';planningPendingRequest=null");
  resolve({ok:true,status:200,json:async()=>({scope_token:'current',replace_projects:[1],tasks:[{id:'stale'}]})});
  await new Promise(done=>setImmediate(done));
  assert.equal(h.run('tasksData.length'),0);
  assert.equal(h.messages.length,0);
});

for (const status of [403,409]) test(`HTTP ${status} triggers one authorized refresh without a retry loop`, async()=>{
  const h=harness();
  h.context.AbortController=AbortController;
  h.context.fetch=async()=>({ok:false,status});
  h.run("lazyProjects=true;planningScopeToken='current';planningPendingRequest='batch';planningTaskEndpoint='/api/planning/tasks'");
  await h.run("requestPlanningTasks(['1'],'batch')");
  h.run('scheduleProjectLoads(0,20)');
  assert.equal(h.messages.length,1);
  assert.equal(h.messages[0].action,'initialize_planning');
  assert.equal(h.timers.length,0);
});

test('HTTP failures leave existing rows visible and offer an explicit retry', async()=>{
  const h=harness(); let notice;
  h.context.AbortController=AbortController;
  h.context.fetch=async()=>({ok:false,status:503});
  h.context.document={getElementById:()=>notice,createElement:()=>({style:{},remove(){notice=null;}}),
    body:{appendChild(element){notice=element;}}};
  h.run("planningScopeToken='current';planningPendingRequest='batch';tasksData=[{id:'retained'}]");
  await h.run("requestPlanningTasks(['1'],'batch')");
  assert.equal(h.run('tasksData[0].id'),'retained');
  assert.equal(h.messages.length,0);
  assert.equal(h.run('planningLoadError'),true);
  assert.ok(notice.textContent.includes('retry'));
  notice.onclick();
  assert.equal(h.run('planningLoadError'),false);
});

for (const sameSelection of [true,false]) test(`new chart data preserves the viewport only for the same selection: ${sameSelection}`,()=>{
  const h=harness(), viewport={scrollTop:12000,scrollLeft:750}; let render;
  Object.assign(h.context,{
    window:{addEventListener(type,listener){render=listener;}},
    document:{getElementById:()=>viewport}, updatePermissionControls(){},
    lastFilterReset:0,hasInitializedCollapse:true,collapsedProjects:new Set(['2']),
    renderTimeline(){viewport.scrollTop=0;viewport.scrollLeft=0;},
  });
  h.run(script.slice(script.indexOf('    let lastDataRevision ='),script.indexOf('    Streamlit.setComponentReady();')));
  h.run("lastDataRevision='old';planningViewScope='selection';planningScopeToken='old-scope'");
  render({data:{type:'streamlit:render',args:{tasks:[],data_revision:'new',scope_token:'new-scope',
    view_scope:sameSelection?'selection':'different-selection',loaded_project_ids:[],project_summaries:[]}}});
  assert.deepEqual(viewport,sameSelection?{scrollTop:12000,scrollLeft:750}:{scrollTop:0,scrollLeft:0});
  assert.equal(h.context.collapsedProjects.has('2'),sameSelection);
});

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

test('visible Gantt projects load before overscan when external dependencies are enabled',()=>{
  const h=harness();
  h.run(`lazyProjects=true; showExternalLinks=true; planningScopeToken='current';
    masterRenderItems=Array.from({length:100},(_,i)=>({type:'project_header',project_id:String(i+1),isCollapsed:true}));
    renderedRowWindow={start:0,end:45,visibleStart:15,visibleEnd:30};
    scheduleProjectLoads(0,45);`);
  h.timers.shift().fn();
  assert.deepEqual([...h.messages[0].project_ids.slice(0,16)],Array.from({length:16},(_,i)=>String(i+16)));
  assert.equal(h.messages[0].project_ids.length,25);
});

test('creating a task retains viewport focus and expands only its own project',()=>{
  const h=harness(), viewport={scrollTop:1800,scrollLeft:920};
  h.context.document={getElementById:()=>viewport};
  h.context.collapsedProjects=new Set(['2','3']);
  h.context.renderTimeline=()=>{viewport.scrollTop=0;viewport.scrollLeft=0;};
  h.run(`planningScopeToken='current';
    applyPlanningPatch({scope_token:'current', focus_project_id:2,
      project_summaries:[],replace_projects:[2],loaded_project_ids:[1,2],tasks:[
        {id:'22',project_id:'2',start:'2026-01-01',end:'2026-01-02'}]});`);
  assert.deepEqual(viewport,{scrollTop:1800,scrollLeft:920});
  assert.deepEqual([...h.context.collapsedProjects],['3']);
  assert.equal(h.run('planningScopeToken'),'current');
  assert.equal(h.run('tasksData[0].id'),'22');
});
