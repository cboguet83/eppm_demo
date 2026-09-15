"""Two-lane project-plan Gantt with stable task pairing and alternative-only dragging."""

import streamlit as st

from app.domain.planning.plans import PlanContent, compare_tasks


_CSS = '''
.plan-gantt {position:relative;font:inherit;border:1px solid var(--st-border-color);border-radius:8px;overflow:auto;max-height:620px;}
.plan-table {border-collapse:collapse;min-width:100%;table-layout:fixed;}
.plan-table th,.plan-table td {border-bottom:1px solid var(--st-border-color);padding:4px 8px;}
.plan-label {width:230px;min-width:230px;position:sticky;left:0;background:var(--st-background-color);z-index:2;}
.plan-project {font-weight:700;background:var(--st-secondary-background-color);}
.plan-track {height:50px;position:relative;min-width:650px;}
.plan-bar {position:absolute;height:17px;border-radius:3px;min-width:4px;box-sizing:border-box;}
.plan-reference {top:4px;background:#8191a8;}
.plan-alternative {top:28px;background:#147d92;}
.plan-bar.editable {cursor:grab;touch-action:none;}
.plan-milestone {border-radius:0;clip-path:polygon(50% 0,100% 50%,50% 100%,0 50%);min-width:17px;}
.plan-links {position:absolute;top:0;left:0;pointer-events:none;overflow:visible;}
.plan-bar:focus-visible {outline:2px solid var(--st-primary-color);outline-offset:2px;}
.plan-difference {font-size:11px;color:var(--st-text-color);opacity:.8;margin-left:6px;}
.plan-legend {display:flex;gap:24px;padding:8px;font-size:13px;}
.plan-legend span:first-child {border-left:12px solid #8191a8;padding-left:6px;}
.plan-legend span:last-child {border-left:12px solid #147d92;padding-left:6px;}
.plan-axis {position:relative;height:26px;min-width:650px;font-size:11px;}
.plan-axis span {position:absolute;white-space:nowrap;}
'''

_JS = r'''
export default function({data,parentElement,setTriggerValue}) {
 const root=parentElement.querySelector('.plan-gantt'); root.replaceChildren();
 const MS=86400000, day=s=>Date.parse(s+'T00:00:00Z')/MS;
 const iso=n=>new Date(n*MS).toISOString().slice(0,10);
 const values=data.projects.flatMap(p=>p.rows.flatMap(r=>[r.reference,r.alternative].filter(Boolean)));
 if(!values.length){root.textContent='No tasks in the selected plans.';return;}
 const first=Math.min(...values.map(t=>day(t.start_date)))-2;
 const last=Math.max(...values.map(t=>day(t.end_date)))+3, span=last-first;
 const legend=document.createElement('div');legend.className='plan-legend';
 for(const label of ['Reference · upper lane','Alternative · lower lane']){const x=document.createElement('span');x.textContent=label;legend.append(x);}root.append(legend);
 const table=document.createElement('table');table.className='plan-table';table.setAttribute('aria-label','Project plan comparison');
 const header=document.createElement('tr'), title=document.createElement('th');title.className='plan-label';title.textContent='Project / task';header.append(title);
 const time=document.createElement('th'),axis=document.createElement('div');axis.className='plan-axis';
 for(let i=0;i<6;i++){const x=document.createElement('span');x.style.left=(i*17)+'%';x.textContent=iso(Math.round(first+span*i*.17));axis.append(x);}time.append(axis);header.append(time);table.append(header);
 const anchors=new Map();
 const taskKey=(project,id)=>id<0?'draft:'+project+':'+id:'task:'+id;
 const bar=(task,side,project,identity,summary=false)=>{
   const el=document.createElement('div');el.className='plan-bar plan-'+side;
   el.style.left=((day(task.start_date)-first)/span*100)+'%';el.style.width=((day(task.end_date)-day(task.start_date)+1)/span*100)+'%';
   el.title=side+': '+task.task_name+' · '+task.start_date+' → '+task.end_date;
   if(task.start_date===task.end_date&&!summary)el.classList.add('plan-milestone');
   anchors.set(side+':'+(summary?'project:'+project.id:taskKey(project.id,identity)),el);
   el.setAttribute('role','img');el.setAttribute('aria-label',el.title);
   if(side==='alternative'&&project.editable&&!summary){
     el.classList.add('editable');el.tabIndex=0;el.setAttribute('role','button');
     const move=delta=>setTriggerValue('edit',{project_id:project.id,id:identity,days:delta,nonce:Date.now()});
     el.onkeydown=e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();move(e.key==='ArrowLeft'?-1:1);}};
     el.onpointerdown=e=>{if(e.button!==0)return;e.preventDefault();const x=e.clientX,width=el.parentElement.clientWidth,base=el.style.left;el.setPointerCapture(e.pointerId);
       el.onpointermove=m=>{el.style.transform=`translateX(${m.clientX-x}px)`;};
       el.onpointerup=u=>{el.onpointermove=null;el.onpointerup=null;el.style.transform='';el.style.left=base;const delta=Math.round((u.clientX-x)/width*span);if(delta)move(delta);};
       el.onpointercancel=()=>{el.onpointermove=null;el.onpointerup=null;el.style.transform='';};};
   }return el;
 };
 for(const project of data.projects){
   const tr=document.createElement('tr');tr.className='plan-project';const name=document.createElement('td');name.className='plan-label';name.textContent=project.name;
   name.title=project.reference_label+' / '+project.alternative_label;tr.append(name);const td=document.createElement('td'),track=document.createElement('div');track.className='plan-track';
   for(const side of ['reference','alternative']){const tasks=project.rows.map(r=>r[side]).filter(Boolean);if(tasks.length)track.append(bar({task_name:project.name,start_date:tasks.map(t=>t.start_date).sort()[0],end_date:tasks.map(t=>t.end_date).sort().at(-1)},side,project,0,true));}td.append(track);tr.append(td);table.append(tr);
   for(const row of project.rows){const tr=document.createElement('tr');tr.dataset.taskId=row.id;const label=document.createElement('td');label.className='plan-label';
     const taskName=document.createElement('span');taskName.textContent=(row.alternative||row.reference).task_name;label.append(taskName);
     if(row.change!=='unchanged'){const mark=document.createElement('span');mark.className='plan-difference';mark.textContent=row.change;label.append(mark);}tr.append(label);
     const td=document.createElement('td'),track=document.createElement('div');track.className='plan-track';
     for(const side of ['reference','alternative'])if(row[side])track.append(bar(row[side],side,project,row.id));td.append(track);tr.append(td);table.append(tr);
   }
 }root.append(table);
 const drawLinks=()=>{
   root.querySelector('.plan-links')?.remove();
   const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.classList.add('plan-links');
   svg.setAttribute('width',root.scrollWidth);svg.setAttribute('height',root.scrollHeight);
   const origin=root.getBoundingClientRect();
   for(const project of data.projects)for(const side of ['reference','alternative'])for(const dep of project[side+'_dependencies']||[]){
     const from=anchors.get(side+':'+(dep.predecessor_task_id!==null?taskKey(project.id,dep.predecessor_task_id):'project:'+dep.predecessor_project_id));
     const to=anchors.get(side+':'+(dep.task_id!==null?taskKey(project.id,dep.task_id):'project:'+project.id));
     if(!from||!to)continue;
     const a=from.getBoundingClientRect(),b=to.getBoundingClientRect();
     const x1=(dep.link_type[0]==='S'?a.left:a.right)-origin.left+root.scrollLeft;
     const x2=(dep.link_type[1]==='S'?b.left:b.right)-origin.left+root.scrollLeft;
     const y1=a.top+a.height/2-origin.top+root.scrollTop,y2=b.top+b.height/2-origin.top+root.scrollTop;
     const path=document.createElementNS(ns,'path');path.setAttribute('d',`M${x1},${y1} H${x1+8} V${y2} H${x2}`);
     path.setAttribute('stroke',side==='reference'?'#8191a8':'#147d92');path.setAttribute('fill','none');path.setAttribute('stroke-width','1.2');
     if(side==='reference')path.setAttribute('stroke-dasharray','3 2');svg.append(path);
   }root.append(svg);
 };
 const resize=new ResizeObserver(drawLinks);resize.observe(table);drawLinks();
 const beforeUnload=e=>{e.preventDefault();e.returnValue='';};
 if(data.projects.some(p=>p.editable))window.addEventListener('beforeunload',beforeUnload);
 return ()=>{resize.disconnect();window.removeEventListener('beforeunload',beforeUnload);};
}
'''


def plan_gantt(projects: list[dict]) -> dict | None:
    """Render paired task transport and validate editable drag-event identities."""
    component = st.components.v2.component('eppm_plan_gantt', html='<div class="plan-gantt"></div>', css=_CSS, js=_JS)
    result = component(data={'projects': projects}, key='plan_gantt', height='content',
                       on_edit_change=lambda: None)
    event = getattr(result, 'edit', None)
    if not isinstance(event, dict) or type(event.get('days')) is not int or abs(event['days']) > 36500:
        return None
    for project in projects:
        if project['id'] == event.get('project_id') and project['editable']:
            if any(row['id'] == event.get('id') and row['alternative'] for row in project['rows']):
                return event
    return None


def comparison_project(identity: int, name: str, reference: PlanContent, alternative: PlanContent,
                       reference_label: str, alternative_label: str, *, editable: bool) -> dict:
    """Package one project's stable task union for the comparison component."""
    return dict(id=identity, name=name, rows=compare_tasks(reference, alternative),
                reference_dependencies=reference.dependencies, alternative_dependencies=alternative.dependencies,
                reference_label=reference_label, alternative_label=alternative_label, editable=editable)
