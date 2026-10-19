/** Virtual timeline DOM ownership; all interactions are delegated to one instance. */
import {projectRows,rowWindow,ROW_HEIGHT} from './rows.js';
import {bindColumnWidths} from './columns.js';

/** @param {Document} doc Document. @param {string} tag Tag. @param {string} className Scoped class. @param {string} text Plain text. */
function node(doc,tag,className,text='') {
  const result=doc.createElement(tag);result.className=className;result.textContent=text;return result;
}

/** @param {HTMLElement} owner Row. @param {object} task Dated record. @param {object} calendar Calendar. @param {string} lane Current/baseline/alternative. @param {string} targetKind Public entity collection. @param {string} overlayId Comparison owner. */
function bar(owner,task,calendar,lane,targetKind,overlayId='',overlay=null) {
  const milestone=targetKind==='tasks' && task.start===task.end;
  const el=node(owner.ownerDocument,'div','planning-bar planning-'+lane+(milestone?' planning-milestone':''));
  const x=calendar.dateToX(task.start),end=calendar.endDateToX(task.end);
  Object.assign(el.style,{left:x+'px',width:(milestone?14:Math.max(targetKind==='projects'?16:24,end-x))+'px'});
  Object.assign(el.dataset,{targetId:task.id ?? '',targetKind,lane,overlayId,start:task.start,end:task.end});
  if(overlay?.revision!==undefined)el.dataset.planRevision=overlay.revision;
  if(overlay?.newScenario)el.classList.add('planning-new-scenario');
  if(targetKind==='projects' && typeof overlay?.tooltip==='string')el.dataset.tooltip=overlay.tooltip;
  el.dataset.scheduleLabel=(milestone?'Milestone: ':'')+(overlay?.name?overlay.name+' · ':'')+task.start+' → '+task.end;
  el.tabIndex=0;el.setAttribute('role','button');el.setAttribute('aria-label',(task.name ?? lane)+' · '+task.start+' → '+task.end);
  if(targetKind==='projects')el.dataset.expand=task.id;
  if(task.progress>=100)el.classList.add('planning-complete');
  if(task.violations?.length)el.classList.add('planning-violated');
  if(!milestone && targetKind==='tasks') {
    const progress=node(owner.ownerDocument,'div','planning-progress');progress.style.width=(task.progress ?? 0)+'%';el.append(progress);
    for(const edge of ['start','end','progress']) {
      const handle=node(owner.ownerDocument,'span','planning-handle planning-handle-'+edge);handle.dataset.edge=edge;el.append(handle);
    }
  }
  owner.append(el);
  for(const edge of ['S','F']) {
    const connector=node(owner.ownerDocument,'span','planning-connector planning-connector-'+edge);
    connector.dataset.connect=edge;connector.setAttribute('role','button');connector.hidden=true;el.append(connector);
  }
}

/** @param {object} panel Private timeline DOM slots. @param {object} store Store. @param {object} lifetime Instance lifetime. @param {object} options Presentation configuration. */
export function createTimelineRenderer({panel,store,lifetime,options}) {
  const doc=panel.root.ownerDocument;
  bindColumnWidths(panel,lifetime);
  let projection=null,previous=null,window=null,windowHeight=null,signature='',headerLabels=null;
  lifetime.own(()=>{projection=null;previous=null;window=null;headerLabels=null;});
  const toggle=id=>{
    const expanded=new Set(store.read().view.expandedProjects);
    if(expanded.has(id))expanded.delete(id);else expanded.add(id);
    store.setView({expandedProjects:[...expanded]});
  };
  lifetime.listen(panel.root,'click',event=>{
    const target=event.target.closest('[data-expand]');if(target)toggle(target.dataset.expand);
    const sort=event.target.closest('[data-sort]');
    if(sort) {
      const filters=store.read().view.filters,old=filters.sort;
      const direction=old?.field!==sort.dataset.sort?'asc':old.direction==='asc'?'desc':old.direction==='desc'?'none':'asc';
      store.setView({filters:{...filters,sort:{field:sort.dataset.sort,direction}}});
    }
  });
  lifetime.listen(panel.root,'keydown',event=>{
    const target=event.target.closest('[data-expand]');
    if(target && ['Enter',' '].includes(event.key)){event.preventDefault();toggle(target.dataset.expand);}
  });
  /** @param {object} labels Localized text. */
  const header=labels=>{
    if(headerLabels===labels)return;headerLabels=labels;panel.leftHeader.replaceChildren();
    for(const field of ['id','name','start','end']) {
      const label=labels['column'+field[0].toUpperCase()+field.slice(1)] || labels[field] || ({id:'ID',name:labels.projectTask || 'Project / task',start:'Start',end:'End'}[field]);
      const cell=node(doc,'div','planning-column planning-column-'+field),button=node(doc,'button','',label),handle=node(doc,'span','planning-column-resizer');
      button.type='button';button.dataset.sort=field;handle.dataset.resizeColumn=field;handle.tabIndex=0;
      handle.setAttribute('role','separator');handle.setAttribute('aria-orientation','vertical');handle.setAttribute('aria-label',(labels.resize || 'Resize')+' '+label);
      cell.append(button,handle);panel.leftHeader.append(cell);
    }
  };
  return {
    render(data,view,calendar,loader) {
      header(data.labels);
      const expanded=JSON.stringify(view.expandedProjects),filters=JSON.stringify(['projectIds','query','sort','taskSort','descriptions'].map(key=>view.filters[key] ?? null));
      const changed=!previous || previous.data!==data || previous.expanded!==expanded || previous.filters!==filters;
      if(changed)projection=projectRows(data,view,{grouped:options.grouped!==false});
      previous={data,expanded,filters};
      if(options.timelineHeight) {
        const height=Math.min(options.timelineHeight.max,Math.max(options.timelineHeight.min,projection.rows.length*ROW_HEIGHT));
        panel.root.style.gridTemplateRows='56px '+height+'px';
      }
      let next=rowWindow(projection.rows.length,view.scrollTop,panel.body.clientHeight);
      if(!changed && window && windowHeight===panel.body.clientHeight && next.visibleStart>=window.start && next.visibleEnd<=window.end)next={...next,start:window.start,end:window.end};
      panel.canvas.style.backgroundSize=calendar.bottomCells[0].width+'px 100%';
      const height=Math.max(ROW_HEIGHT,projection.rows.length*ROW_HEIGHT);
      for(const canvas of [panel.canvas,panel.leftCanvas])canvas.style.height=height+'px';
      const currentSignature=next.start+':'+next.end+':'+calendar.width+':'+calendar.start+':'+calendar.end+':'+view.mode;
      if(changed || signature!==currentSignature) {
        panel.canvas.replaceChildren();panel.leftCanvas.replaceChildren();
        for(let index=next.start;index<=next.end;index++) {
          const row=projection.rows[index],left=node(doc,'div','planning-row planning-frozen-row planning-'+row.kind+'-row');
          const right=node(doc,'div','planning-row planning-timeline-row planning-'+row.kind+'-row');
          for(const item of [left,right]) {
            item.style.top=index*ROW_HEIGHT+'px';item.dataset.rowKey=row.key;item.dataset.projectId=row.projectId;item.dataset.rowIndex=index;
          }
          if(row.kind==='loading')left.textContent=data.labels.loading || 'Loading…';
          else {
            const record=row.record,range=row.summary ?? record;
            const alternative=row.kind==='task'?row.comparisons.find(item=>item.overlay.kind==='alternative'):null;
            Object.assign(left.dataset,{targetId:record.id,targetKind:row.kind==='project'?'projects':'tasks',lane:row.current || row.kind==='project'?'current':row.comparisons[0].overlay.kind});
            left.tabIndex=0;
            if(row.kind==='task' && !row.current)left.dataset.overlayId=row.comparisons[0].overlay.id;
            if(alternative)Object.assign(left.dataset,{targetId:alternative.task.id,overlayId:alternative.overlay.id,lane:'alternative'});
            if(row.kind==='project') {
              const button=node(doc,'button','planning-expand',row.expanded?'▾':'▸');button.dataset.expand=row.projectId;
              button.setAttribute('aria-label',(row.expanded?(data.labels.collapse || 'Collapse'):(data.labels.expand || 'Expand'))+' '+record.name);
              button.setAttribute('aria-expanded',String(row.expanded));left.append(button);
            }
            for(const field of ['id','name','start','end']) {
              const cell=node(doc,'span','planning-column planning-column-'+field,String(field==='start'||field==='end'?range?.[field] ?? '':record[field] ?? ''));
              if(field==='name' && row.kind==='task' && view.filters.descriptions!==false && record.description)cell.append(node(doc,'small','planning-description',record.description));
              if(field==='name' && alternative && alternative.task.name!==record.name)cell.append(node(doc,'small','planning-comparison-title',alternative.task.name));
              left.append(cell);
            }
            if(row.kind==='project') {
              const counts=node(doc,'span','planning-counts'),currentCount=node(doc,'span','planning-count',String(row.taskCount));
              currentCount.dataset.taskCount='current';currentCount.title='Tasks in '+(record.scenarioName ?? record.name);counts.append(currentCount);
              for(const {overlay} of row.comparisons) {
                const count=node(doc,'button','planning-count planning-comparison-count',String(overlay.tasks.length));count.type='button';
                Object.assign(count.dataset,{targetId:record.id,targetKind:'projects',overlayId:overlay.id,diagnostics:'true',lane:overlay.kind});counts.append(count);
                count.dataset.taskCount=overlay.kind;count.dataset.nativeTitle='true';count.title='Tasks in '+(overlay.name ?? overlay.kind);
              }
              left.querySelector('.planning-column-name').append(counts);
            }
            if((alternative?.task ?? record).violations?.length) {
              const warning=node(doc,'button','planning-diagnostic-mark','⚠');warning.type='button';warning.dataset.diagnostics='true';warning.setAttribute('aria-label',data.labels.diagnostics || 'Constraint diagnostics');left.querySelector('.planning-column-name').append(warning);
            }
            if(row.summary)bar(right,{...row.summary,id:record.id,name:record.name},calendar,'current','projects');
            if(row.current)bar(right,row.current,calendar,'current','tasks');
            for(const {overlay,task} of row.comparisons)bar(right,row.kind==='project'?{...task,id:record.id,name:record.name}:task,calendar,overlay.kind,row.kind==='project'?'projects':'tasks',overlay.id,overlay);
            if(row.comparisons.some(item=>item.overlay.kind==='alternative'))right.classList.add('planning-comparing');
            if(row.comparisons.some(item=>item.overlay.kind==='baseline'))right.classList.add('planning-baseline-paired');
            if(row.comparisons.some(item=>item.overlay.newScenario))left.classList.add('planning-new-scenario');
          }
          panel.leftCanvas.append(left);panel.canvas.append(right);
        }
        signature=currentSignature;
      }
      window=next;windowHeight=panel.body.clientHeight;
      if(loader) {
        const ids=(start,end)=>[...new Set(projection.rows.slice(start,end+1).map(row=>row.projectId))];
        loader.request(ids(next.visibleStart,next.visibleEnd),ids(next.start,next.end));
      }
      return {projection,window,changed};
    }
  };
}
