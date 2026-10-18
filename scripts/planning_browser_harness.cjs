// Shared mounted boundary for component characterization and performance capture.
// Playwright is supplied by the existing Python browser-tests dependency.
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const {execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'..');
const localPython=path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const python=process.env.EPPM_BENCHMARK_PYTHON || (fs.existsSync(localPython)?localPython:'python');

async function openPlanningBrowser(executable=process.env.EPPM_BENCHMARK_BROWSER) {
  const driver=execFileSync(python,['-c','from pathlib import Path; import playwright; print(Path(playwright.__file__).parent / "driver/package")'],{encoding:'utf8'}).trim();
  const {chromium}=require(driver);
  const directory=path.join(root,'app/presentation/assets/components/gantt');
  const server=http.createServer((request,response)=>{
    const relative=decodeURIComponent(new URL(request.url,'http://localhost').pathname);
    const filename=path.resolve(directory,'.'+(relative==='/'?'/index.html':relative));
    if(!filename.startsWith(directory+path.sep)){response.writeHead(403).end();return;}
    fs.readFile(filename,(error,bytes)=>{
      if(error){response.writeHead(404).end();return;}
      response.setHeader('Content-Type',filename.endsWith('.js')?'text/javascript':filename.endsWith('.css')?'text/css':'text/html');
      response.end(bytes);
    });
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  let browser;
  try {
    browser=await chromium.launch({headless:true,chromiumSandbox:true,...(executable?{executablePath:executable}:{})});
    const page=await browser.newPage({viewport:{width:1500,height:1100}});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto('http://127.0.0.1:'+server.address().port);
    // Await the module graph and stylesheet through browser resource loading.
    await page.evaluate(async()=>{
      await import('./eppm-bootstrap.js');
      window.planningTest={events:[],send:args=>window.dispatchEvent(new MessageEvent('message',{source:window.parent,origin:location.origin,data:{type:'streamlit:render',args}}))};
      addEventListener('message',event=>{if(event.data?.type==='streamlit:setComponentValue')planningTest.events.push(event.data.value);});
      const sheet=document.createElement('link');sheet.rel='stylesheet';sheet.href='./planning-view/src/workspace/styles.css';
      document.head.append(sheet);await new Promise((resolve,reject)=>{sheet.onload=resolve;sheet.onerror=reject;});
    });
    return {page,errors,async close(){await browser.close();await new Promise(resolve=>server.close(resolve));}};
  }catch(error){await browser?.close();await new Promise(resolve=>server.close(resolve));throw error;}
}

function fixture({projects=100,tasksPerProject=10,pools=127}={}) {
  const tasks=[],summaries=[],resources=[],hierarchy=[];
  const day=i=>new Date(Date.UTC(2025,0,1+i)).toISOString().slice(0,10);
  for(let p=1;p<=projects;p++) {
    const owned=[];
    for(let t=0;t<tasksPerProject;t++) {
      const id=String(p*100+t),dependenciesList=t?[{id:'internal-'+id,predecessor_task_id:p*100+t-1,task_id:id,link_type:'FS',lag_days:0}]:[];
      for(let d=1;d<=5;d++){const predecessor=(p+d*17)%projects+1;dependenciesList.push({id:'external-'+id+'-'+d,predecessor_task_id:predecessor*100+t,predecessor_project_id:String(predecessor),is_external:true,link_type:['FS','SS','FF','SF'][d%4],lag_days:0});}
      owned.push({id,project_id:String(p),project_name:'Benchmark project '+p,name:'Task '+t,start:day(p+t*25),end:day(p+t*25+35),progress:20,dependenciesList,tags:[],pools:[]});
    }
    tasks.push(...owned);
    summaries.push({id:String(p),name:'Benchmark project '+p,taskCount:tasksPerProject,start:owned[0]?.start ?? day(p),end:owned.at(-1)?.end ?? day(p+35),tags:[],pools:[],projectDependencies:[]});
  }
  for(let p=1;p<=pools;p++) {
    const usage={},capacity={};
    for(let d=0;d<730;d++){usage[day(d)]=(p%5)+1;capacity[day(d)]=d===365?0:4;}
    resources.push({id:p,name:'Pool '+p,used_by_selected_projects:true,capacity:4,theoretical_capacity:4,displayed_assigned_capacity:4,
      has_assigned_resources:true,daily_assigned_capacity:capacity,daily_usage:usage,selected_projects_daily_usage:usage});
  }
  for(let g=0;g<Math.ceil(pools/10);g++){const ids=resources.slice(g*10,g*10+10).map(p=>p.id);hierarchy.push({key:'group:'+g,node_type:'group',name:'Group '+g,descendant_pool_ids:ids,children:ids.map(id=>({key:'pool:'+id,node_type:'pool',pool_id:id,name:'Pool '+id}))});}
  return {tasks,project_summaries:summaries,all_projects:summaries.map(({id,name})=>({id,name})),external_tasks:{},project_id:1,is_multi_project:projects>1,
    resource_pools:resources,resource_pool_hierarchy:hierarchy,data_revision:'benchmark',scope_token:'benchmark',view_scope:'benchmark',task_revision:'r1',
    loaded_project_ids:summaries.map(p=>p.id),permissions:{edit_all:true,baseline_all:true,manage_shared:true},edit_enabled:false,filter_reset:0};
}
module.exports={openPlanningBrowser,fixture,python,root};
