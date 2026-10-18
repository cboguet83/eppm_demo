// Real Chromium rendering/scroll benchmark. Uses an isolated, headless profile.
// node scripts/benchmark_gantt.cjs [path/to/chromium-or-msedge] [--database] [--external-links] [--expanded]
// Native database mode also accepts --env-file=PATH and --client-container=NAME.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn, execFileSync} = require('node:child_process');
const {pathToFileURL} = require('node:url');
const readline = require('node:readline');

async function main() {
  const useDatabase = process.argv.includes('--database');
  const executable = process.argv.slice(2).find(a => !a.startsWith('--')) || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
  const root = path.resolve(__dirname, '..');
  const localPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const python = process.env.EPPM_BENCHMARK_PYTHON || (fs.existsSync(localPython) ? localPython : 'python');
  const databaseOptions = process.argv.filter(value => value.startsWith('--env-file=') || value.startsWith('--client-container='));
  const server = useDatabase ? spawn(python, ['-m','scripts.benchmark_planning_session',
    '--projects',process.argv.includes('--all-projects')?'0':'100', ...databaseOptions],
    {cwd:root,windowsHide:true,stdio:['pipe','pipe','inherit']}) : null;
  const responses=[], readers=[];
  let serverError;
  const failServer = () => {
    serverError = new Error('The isolated PostgreSQL benchmark session could not complete.');
    while(readers.length) readers.shift().reject(serverError);
  };
  if(server) {
    server.once('error', failServer);
    server.once('exit', failServer);
    server.stdin.on('error', failServer);
    readline.createInterface({input:server.stdout}).on('line',line=>{
      try {
        const result=JSON.parse(line);
        if(readers.length) readers.shift().resolve(result);else responses.push(result);
      } catch { failServer(); }
    });
  }
  const nextResponse=()=>responses.length?Promise.resolve(responses.shift()):
    serverError?Promise.reject(serverError):new Promise((resolve,reject)=>{
      const timeout = setTimeout(failServer, 180000);
      readers.push({resolve:value=>{clearTimeout(timeout);resolve(value);},
        reject:error=>{clearTimeout(timeout);reject(error);}});
    });
  const initial=server?await nextResponse().catch(error=>{server.stdin.end();throw error;}):null;
  const payload=initial?.args || null;
  const serverTimings=initial?[{action:'initial',seconds:initial.server_seconds,bytes:JSON.stringify(payload).length}]:[];
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'eppm-gantt-browser-'));
  const browser = spawn(executable, ['--headless=new', '--disable-extensions', '--no-first-run',
    '--no-default-browser-check', '--remote-debugging-port=0', '--window-size=1500,1100',
    '--user-data-dir=' + profile, 'about:blank'], {windowsHide: true, stdio: 'ignore'});
  let socket, closeBrowser, browserError;
  browser.once('error', () => { browserError = new Error('The benchmark browser could not start.'); });
  try {
    const activePort = path.join(profile, 'DevToolsActivePort');
    const deadline = Date.now() + 20000;
    while (!fs.existsSync(activePort)) {
      if (browserError) throw browserError;
      if (Date.now() > deadline) throw new Error('Headless browser did not start');
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    const port = fs.readFileSync(activePort, 'utf8').split('\n')[0];
    const targets = await (await fetch('http://127.0.0.1:' + port + '/json')).json();
    socket = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
    await new Promise(resolve => socket.addEventListener('open', resolve, {once: true}));
    let id = 0;
    const pending = new Map();
    let eventQueue=Promise.resolve();
    socket.onmessage = event => {
      const message = JSON.parse(event.data);
      if(server && message.method==='Runtime.bindingCalled') {
        const request=JSON.parse(message.params.payload);
        eventQueue=eventQueue.then(async()=>{
          server.stdin.write(JSON.stringify(request)+'\n');
          const response=await nextResponse();
          serverTimings.push({action:request.action,seconds:response.server_seconds,bytes:JSON.stringify(response.args).length});
          await evaluate('window.dispatchEvent(new MessageEvent("message",{data:{type:"streamlit:render",args:'+JSON.stringify(response.args)+'}}))');
        });
      }
      if (pending.has(message.id)) {
        const {resolve, reject} = pending.get(message.id); pending.delete(message.id);
        message.error ? reject(message.error) : resolve(message.result);
      }
    };
    const call = (method, params = {}) => new Promise((resolve, reject) => {
      pending.set(++id, {resolve, reject}); socket.send(JSON.stringify({id, method, params}));
    });
    closeBrowser = () => call('Browser.close');
    const evaluate = async expression => {
      const result = await call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
      if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
      return result.result.value;
    };
    await call('Page.navigate', {url: pathToFileURL(path.resolve(__dirname, '../app/presentation/assets/components/gantt/index.html')).href});
    for (let tries = 0; tries < 100; tries++) {
      if (await evaluate('typeof renderTimeline === "function"')) break;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    await evaluate('window.benchmarkPayload = ' + JSON.stringify(payload));
    if(server) {
      await call('Runtime.addBinding',{name:'benchmarkGanttEvent'});
      await evaluate('Streamlit.setComponentValue = value => window.benchmarkGanttEvent(JSON.stringify(value))');
    }
    await evaluate('window.benchmarkOptions = ' + JSON.stringify({external: process.argv.includes('--external-links'), expanded: process.argv.includes('--expanded')}));
    const result = await evaluate(`(async () => {
      const tasks = [], projects = [], pools = [], hierarchy = [];
      const day = i => new Date(Date.UTC(2025,0,1+i)).toISOString().slice(0,10);
      for (let p=1;p<=100;p++) {
        projects.push({id:String(p), name:'Benchmark project '+p, tags:[],pools:[]});
        for (let t=0;t<10;t++) tasks.push({id:String(p*100+t),project_id:String(p),project_name:'Benchmark project '+p,
          name:'Task '+t,start:day(p+t*25),end:day(p+t*25+35),progress:20,
          dependenciesList:t?[{predecessor_task_id:p*100+t-1,task_id:p*100+t,link_type:'FS',lag_days:0}]:[],tags:[],pools:[]});
      }
      // Include dense, distant cross-project links, not just adjacent task links.
      tasks.forEach(task => {
        for(let d=1;d<=5;d++) {
          const predProject=(Number(task.project_id)+d*17)%100+1;
          task.dependenciesList.push({predecessor_task_id:predProject*100+Number(task.id)%10,
            predecessor_project_id:String(predProject),is_external:true,link_type:['FS','SS','FF','SF'][d%4],lag_days:0});
        }
      });
      for (let p=1;p<=127;p++) {
        const usage={}, capacity={};
        for(let d=0;d<730;d++) {usage[day(d)]=(p%5)+1;capacity[day(d)]=d===365?0:4;}
        pools.push({id:p,name:'Pool '+p,used_by_selected_projects:true,capacity:4,theoretical_capacity:4,displayed_assigned_capacity:4,
          has_assigned_resources:true,daily_assigned_capacity:capacity,daily_usage:usage,selected_projects_daily_usage:usage});
      }
      for(let g=0;g<13;g++) {
        const ids=pools.slice(g*10,g*10+10).map(p=>p.id);
        hierarchy.push({key:'group:'+g,node_type:'group',name:'Group '+g,descendant_pool_ids:ids,
          children:ids.map(id=>({key:'pool:'+id,node_type:'pool',pool_id:id,name:'Pool '+id}))});
      }
      const start=performance.now();
      const payload=window.benchmarkPayload || {tasks,
        all_projects:projects,external_tasks:{},project_id:1,is_multi_project:true,resource_pools:pools,
        resource_pool_hierarchy:hierarchy,data_revision:'benchmark'};
      window.dispatchEvent(new MessageEvent('message',{data:{type:'streamlit:render',args:payload}}));
      const renderMs=performance.now()-start;
      const defaultExternalLinks=showExternalLinks;
      if(defaultExternalLinks || document.getElementById('chk-external-links').checked) throw new Error('External links must start disabled');
      if(window.benchmarkOptions.expanded) expandAllProjects();
      toggleLinkVisibility('external',window.benchmarkOptions.external);
      if(lazyProjects && (window.benchmarkOptions.expanded || window.benchmarkOptions.external)) {
        const deadline=performance.now()+15000;
        while(!tasksData.length && performance.now()<deadline) await new Promise(resolve=>setTimeout(resolve,30));
        if(!tasksData.length) throw new Error('Lazy task loading did not complete');
      }
      let inspectedDependencies=0;
      const bundle=[...renderedDependencyLinks.values()].find(b=>b.members.length>1);
      if(bundle) {
        bundle.nodes.querySelector('path').dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:900,clientY:300}));
        const select=document.querySelector('#dep-ctx-content select');
        if(!select || select.options.length!==bundle.members.length) throw new Error('Grouped dependencies are not inspectable');
        const index=bundle.members.length-1;
        select.value=String(index);select.dispatchEvent(new Event('change'));
        if(selectedDependencyInfo.succId!==bundle.members[index].getInfo().succId) throw new Error('Wrong dependency selected');
        inspectedDependencies=bundle.members.length;
        hideDepContextMenu();
      }
      const renderTimes=[];
      const original=renderVirtualWindow;
      renderVirtualWindow=function(...args){const s=performance.now();const r=original(...args);renderTimes.push(performance.now()-s);return r;};
      const scroller=document.getElementById('timeline-body-scroller');
      const frames=[];let prev=performance.now(),maxLinkNodes=0;
      for(let i=0;i<100;i++) {
        scroller.scrollTop=i*(window.benchmarkOptions.expanded?180:35);
        scroller.scrollLeft=(i%30)*20;
        await new Promise(requestAnimationFrame);
        const now=performance.now();frames.push(now-prev);prev=now;
        maxLinkNodes=Math.max(maxLinkNodes,document.querySelectorAll('#grid-links-group path').length);
      }
      const resource=document.getElementById('resource-grid-main');
      resource.scrollTop=5000;
      await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);
      const leftRow=document.querySelector('.resource-left-row');
      const rightRow=document.querySelector('.resource-right-row');
      const rowAlignment=leftRow&&rightRow?Math.abs(leftRow.getBoundingClientRect().top-rightRow.getBoundingClientRect().top):0;
      if(rowAlignment>1) throw new Error('Resource panes are misaligned: '+rowAlignment+'px');
      if(document.querySelectorAll('.resource-left-row').length>40) throw new Error('Resource rows are not virtualized');
      frames.sort((a,b)=>a-b);renderTimes.sort((a,b)=>a-b);
      return {source:window.benchmarkPayload?'isolated PostgreSQL restore':'representative fixture',
        defaultExternalLinks,externalLinks:showExternalLinks,expanded:window.benchmarkOptions.expanded,maxLinkNodes,inspectedDependencies,
        projects:payload.project_summaries?.length || new Set(payload.tasks.map(t=>t.project_id)).size,tasks:tasksData.length,
        pools:payload.resource_pools.length,renderMs,
        scrollFrameP95:frames[Math.floor(frames.length*.95)],scrollWorkMaxMs:renderTimes.at(-1),
        scrollWorkP95Ms:renderTimes[Math.floor(renderTimes.length*.95)],
        resourceCells:document.querySelectorAll('.resource-demand-cell').length,
        ganttRows:document.querySelectorAll('.frozen-row').length,
        resourceRows:document.querySelectorAll('.resource-left-row').length,
        resourceTop:resource.scrollTop,resourcePaneAlignmentPx:rowAlignment};
    })()`);
    if(server && process.argv.includes('--move-task')) {
      const before=serverTimings.length;
      await evaluate(`(() => {const task=tasksData[0]; if(!task) throw new Error('No loaded task to move');
        Streamlit.setComponentValue({action:'update_dates',id:Number(task.id),
          start_date:formatDate(addDays(parseDate(task.start),1)),end_date:formatDate(addDays(parseDate(task.end),1)),nonce:'benchmark_move'});})()`);
      const deadline=Date.now()+15000;
      while(serverTimings.length===before && Date.now()<deadline) await new Promise(resolve=>setTimeout(resolve,30));
      await eventQueue;
    }
    if(server) result.serverTimings=serverTimings;
    result.fitCheck=await evaluate(`(() => {
      const task={id:'1',project_id:'1',project_name:'Fit check',name:'Task',start:'2026-01-01',end:'2026-01-02',dependenciesList:[]};
      window.dispatchEvent(new MessageEvent('message',{data:{type:'streamlit:render',args:{tasks:[task],all_projects:[{id:'1',name:'Fit check'}],
        project_id:'1',is_multi_project:true,resource_pools:[{id:1,name:'Pool',capacity:3,theoretical_capacity:3,daily_usage:{},daily_assigned_capacity:{}}],
        resource_pool_hierarchy:[],data_revision:'fit-check'}}}));
      setViewMode('Year');
      const gantt=document.getElementById('timeline-body-scroller'), resource=document.getElementById('resource-right-pane-scroller');
      const available=gantt.clientWidth;
      if(totalTimelineWidth < available-1) throw new Error('Gantt does not fill available width');
      if(Math.abs(resource.clientWidth-available)>1) throw new Error('Gantt/resource viewport widths differ');
      return {ganttWidth:available,resourceWidth:resource.clientWidth,timelineWidth:totalTimelineWidth,
        ganttVerticalScrollbar:gantt.scrollHeight>gantt.clientHeight+1,
        resourceVerticalScrollbar:document.getElementById('resource-grid-main').scrollHeight>document.getElementById('resource-grid-main').clientHeight+1};
    })()`);
    console.log(JSON.stringify(result, null, 2));
    await call('Browser.close');
    closeBrowser = null;
  } finally {
    if (closeBrowser && socket?.readyState === WebSocket.OPEN) {
      await Promise.race([closeBrowser().catch(() => {}), new Promise(resolve => setTimeout(resolve, 1000))]);
    }
    if (socket) socket.close();
    browser.kill();
    if(server) server.stdin.end();
    // Keep the isolated temporary profile for OS cleanup; never touch user profiles.
  }
}
main().catch(error => {console.error(error); process.exitCode = 1;});
