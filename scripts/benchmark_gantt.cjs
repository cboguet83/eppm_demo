// Mounted public-boundary benchmark; see planning-component-benchmark.md.
const {spawn}=require('node:child_process');
const readline=require('node:readline');
const {openPlanningBrowser,fixture,python,root}=require('./planning_browser_harness.cjs');
async function main() {
  const database=process.argv.includes('--database'),expanded=process.argv.includes('--expanded'),external=process.argv.includes('--external-links');
  const executable=process.argv.slice(2).find(value=>!value.startsWith('--')) || process.env.EPPM_BENCHMARK_BROWSER;
  const child=database?spawn(python,['-m','scripts.benchmark_planning_session','--projects',process.argv.includes('--all-projects')?'0':'100',
    ...process.argv.filter(value=>value.startsWith('--env-file=') || value.startsWith('--client-container='))],{cwd:root,stdio:['pipe','pipe','inherit']}):null;
  const waiting=[],received=[],timings=[];let failure=null,harness;
  const failed=()=>{failure=new Error('The isolated PostgreSQL session could not complete.');while(waiting.length)waiting.shift().reject(failure);};
  if(child) {
    child.on('error',failed);child.on('exit',failed);child.stdin.on('error',failed);
    readline.createInterface({input:child.stdout}).on('line',line=>{
      try{const value=JSON.parse(line);if(waiting.length)waiting.shift().resolve(value);else received.push(value);}catch{failed();}
    });
  }
  const next=()=>received.length?Promise.resolve(received.shift()):failure?Promise.reject(failure):new Promise((resolve,reject)=>{
    const timer=setTimeout(failed,180000);waiting.push({resolve:value=>{clearTimeout(timer);resolve(value);},reject:error=>{clearTimeout(timer);reject(error);}});
  });
  try {
    const initial=child?await next():null,payload=initial?.args ?? fixture();
    if(initial)timings.push({action:'initial',seconds:initial.server_seconds,bytes:JSON.stringify(payload).length});
    harness=await openPlanningBrowser(executable);const {page}=harness;
    let queue=Promise.resolve();
    const exchange=request=>{
      const result=queue.then(async()=>{
        child.stdin.write(JSON.stringify(request)+'\n');const response=await next();
        timings.push({action:request.action,seconds:response.server_seconds,bytes:JSON.stringify(response.args).length});
        return response;
      });queue=result.then(()=>{});return result;
    };
    if(child) {
      await page.exposeFunction('benchmarkHostEvent',async request=>{
        const response=await exchange(request);await page.evaluate(args=>planningTest.send(args),response.args);
      });
      await page.evaluate(()=>addEventListener('message',event=>{if(event.data?.type==='streamlit:setComponentValue')void window.benchmarkHostEvent(event.data.value);}));
    }
    const renderMs=await page.evaluate(args=>{const start=performance.now();planningTest.send(args);return performance.now()-start;},payload);
    await page.waitForSelector('.planning-view');
    const defaultExternalLinks=await page.locator('[data-control=externalLinks]').isChecked();
    if(defaultExternalLinks)throw new Error('External links must start disabled');
    if(expanded)await page.locator('[data-control=expandAll]').click();
    await page.locator('[data-control=externalLinks]').setChecked(external);
    if(child && expanded)await page.waitForSelector('.planning-bar[data-target-kind=tasks]');
    const inspectedDependencies=await page.evaluate(async()=>{
      await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);
      const bundle=[...document.querySelectorAll('.planning-link')].find(node=>Number(node.dataset.memberCount)>1);
      if(!bundle)return 0;
      bundle.querySelector('path').dispatchEvent(new MouseEvent('click',{bubbles:true}));
      const inspector=document.querySelector('[data-part=dependency-inspector]'),select=inspector.querySelector('select'),count=Number(bundle.dataset.memberCount);
      if(inspector.hidden || select.options.length!==count)throw new Error('Grouped dependencies are not inspectable');
      const last=select.options[count-1].value;select.value=last;select.dispatchEvent(new Event('change',{bubbles:true}));
      if(inspector.querySelector('select').value!==last)throw new Error('Wrong dependency selected');
      inspector.querySelector('[data-close-inspector]').click();return count;
    });
    const result=await page.evaluate(async(options)=>{
      // Time callbacks through the browser frame API, without renderer globals.
      const original=requestAnimationFrame,work=[],frames=[];
      window.requestAnimationFrame=callback=>original(time=>{const start=performance.now();try{callback(time);}finally{work.push(performance.now()-start);}});
      const frame=()=>new Promise(resolve=>original(resolve)),body=document.querySelector('[data-part=timeline-body]');
      let previous=performance.now(),maxLinkNodes=0;
      for(let i=0;i<100;i++){
        body.scrollTop=i*(options.expanded?180:35);body.scrollLeft=(i%30)*20;await frame();
        const now=performance.now();frames.push(now-previous);previous=now;
        maxLinkNodes=Math.max(maxLinkNodes,document.querySelectorAll('[data-part=dependencies] path').length);
      }
      const resource=document.querySelector('[data-part=resource-body]');resource.scrollTop=5000;resource.dispatchEvent(new Event('scroll'));await frame();await frame();
      const left=document.querySelector('.planning-resource-left'),right=document.querySelector('.planning-resource-right');
      const alignment=left && right?Math.abs(left.getBoundingClientRect().top-right.getBoundingClientRect().top):Infinity;
      const rows=document.querySelectorAll('.planning-resource-left').length,cells=document.querySelectorAll('.planning-resource-cell').length;
      if(!rows || rows>40 || !cells)throw new Error('Resource rows/cells violate virtualization bounds');
      if(alignment>1)throw new Error('Resource panes are misaligned: '+alignment+'px');
      frames.sort((a,b)=>a-b);work.sort((a,b)=>a-b);window.requestAnimationFrame=original;
      return {...options,source:'representative fixture',maxLinkNodes,visibleTasks:document.querySelectorAll('.planning-frozen-row[data-target-kind=tasks]').length,
        scrollFrameP95:frames[Math.floor(frames.length*.95)],scrollWorkMaxMs:work.at(-1) ?? 0,scrollWorkP95Ms:work[Math.floor(work.length*.95)] ?? 0,
        resourceCells:cells,ganttRows:document.querySelectorAll('.planning-frozen-row').length,resourceRows:rows,resourceTop:resource.scrollTop,resourcePaneAlignmentPx:alignment};
    },{expanded,externalLinks:external,renderMs,defaultExternalLinks,inspectedDependencies,projects:payload.project_summaries.length,pools:payload.resource_pools.length,tasks:payload.tasks.length});
    if(child && process.argv.includes('--move-task')){
      await page.locator('[data-control=edit]').check();await queue;
      await page.locator('[data-part=timeline-body]').evaluate(node=>{node.scrollTop=0;node.scrollLeft=0;});
      await page.locator('.planning-frozen-row[data-target-kind=tasks]').first().press('Enter');
      const editor=page.locator('.planning-editor'),start=editor.locator('[data-field=start]'),end=editor.locator('[data-field=end]');
      const plus=value=>new Date(Date.parse(value+'T00:00:00Z')+86400000).toISOString().slice(0,10);
      await start.fill(plus(await start.inputValue()));await end.fill(plus(await end.inputValue()));
      await page.waitForFunction(()=>!document.querySelector('.planning-editor select:disabled'));
      await editor.locator('button[type=submit]').click();
      await page.waitForFunction(()=>planningTest.events.some(event=>event.action==='update_task_full'));
      await queue;
      if(!timings.some(timing=>timing.action==='update_task_full'))throw new Error('The mounted edit did not reach the host');
    }
    if(child){result.source='isolated PostgreSQL restore';result.serverTimings=timings;}
    await page.evaluate(args=>planningTest.send(args),{...fixture({projects:1,tasksPerProject:1,pools:1}),view_scope:'fit-check',scope_token:'fit-check',data_revision:'fit-check'});
    await page.locator('[data-mode=Year]').click();
    result.fitCheck=await page.evaluate(()=>{
      const gantt=document.querySelector('[data-part=timeline-body]'),resource=document.querySelector('[data-part=resource-body]'),canvas=document.querySelector('[data-part=timeline-canvas]');
      const available=gantt.clientWidth,timelineWidth=canvas.getBoundingClientRect().width;
      if(timelineWidth<available-1)throw new Error('Gantt does not fill available width');
      if(Math.abs(resource.clientWidth-available)>1)throw new Error('Gantt/resource viewport widths differ');
      return {ganttWidth:available,resourceWidth:resource.clientWidth,timelineWidth,ganttVerticalScrollbar:gantt.scrollHeight>gantt.clientHeight+1,resourceVerticalScrollbar:resource.scrollHeight>resource.clientHeight+1};
    });
    if(harness.errors.length)throw new Error(harness.errors.join('\n'));
    console.log(JSON.stringify(result,null,2));
  }finally{await harness?.close();child?.stdin.end();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
