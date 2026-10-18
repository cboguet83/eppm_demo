/** Virtual resource rows/cells with independent vertical and shared date geometry. */
import {createResourceSummaries,formatResourceValue,capacityDetails} from './summary.js';
import {resourceRows,resourceWindow,resourceCell,periodSummary,RESOURCE_ROW_HEIGHT} from './rows.js';

const FILTERS=['hideUnused','onlyOverallocated','showTotal','showSelected'];

/** @param {Document} doc Document. @param {string} className Scoped class. @param {string} text Plain text. */
function node(doc,className,text=''){const el=doc.createElement('div');el.className=className;el.textContent=text;return el;}

/** @param {object} panel Private resource slots. @param {HTMLElement} heading Section controls. @param {object} store Store. @param {object} lifetime Lifetime. @param {object} options Presentation configuration. @param {Function} cancelSelection Cancel delayed single selection on double-click. */
export function createResourceRenderer({panel,heading,store,lifetime,options,cancelSelection}) {
  const doc=panel.root.ownerDocument,summaries=createResourceSummaries(),toggle=doc.createElement('button'),title=doc.createElement('span');
  toggle.type='button';toggle.dataset.resourceControl='collapse';
  const count=node(doc,'planning-resource-count'),filter=node(doc,'planning-resource-filter');filter.dataset.part='resource-filter';
  heading.append(toggle,title,count,filter);
  const checks=new Map();
  for(const name of FILTERS) {
    const label=doc.createElement('label'),input=doc.createElement('input');input.type='checkbox';input.dataset.resourceControl=name;
    label.append(input,doc.createTextNode(''));heading.append(label);checks.set(name,{label,input});
  }
  let model=null,previousKey='',previousData=null,signature='',focusTarget=null;
  const focusCell=cell=>{panel.canvas.querySelector('[tabindex="0"]')?.setAttribute('tabindex','-1');cell.tabIndex=0;cell.focus();};
  const settings=()=>({hideUnused:true,onlyOverallocated:false,showTotal:true,showSelected:true,...store.read().view.filters.resources});
  const changeSettings=patch=>{const {view}=store.read();store.setView({filters:{...view.filters,resources:{...settings(),...patch}}});};
  const toggleNode=id=>{
    cancelSelection();const collapsed=new Set(store.read().view.collapsedResources);
    if(collapsed.has(id))collapsed.delete(id);else collapsed.add(id);
    store.setView({collapsedResources:[...collapsed]});
  };
  lifetime.listen(heading,'click',event=>{if(event.target.closest('[data-resource-control=collapse]'))changeSettings({collapsed:!settings().collapsed});});
  lifetime.listen(heading,'change',event=>{if(FILTERS.includes(event.target.dataset.resourceControl))changeSettings({[event.target.dataset.resourceControl]:event.target.checked});});
  lifetime.listen(panel.root,'click',event=>{
    const button=event.target.closest('[data-toggle-resource]');if(button)toggleNode(button.dataset.toggleResource);
    const cell=event.target.closest('.planning-resource-cell');if(cell)focusCell(cell);
  });
  lifetime.listen(panel.root,'dblclick',event=>{
    cancelSelection();const row=event.target.closest('[data-double-toggle]');
    if(row && !event.target.closest('button')){event.preventDefault();toggleNode(row.dataset.doubleToggle);}
  });
  lifetime.listen(panel.root,'keydown',event=>{
    const cell=event.target.closest('.planning-resource-cell'),row=event.target.closest('[data-double-toggle]');
    if(event.key==='Enter' && row && !event.target.closest('button')){event.preventDefault();toggleNode(row.dataset.doubleToggle);return;}
    if(!cell || !['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
    event.preventDefault();let index=Number(cell.dataset.rowIndex),column=Number(cell.dataset.columnIndex);
    if(event.key==='ArrowLeft')column--;if(event.key==='ArrowRight')column++;
    if(event.key==='ArrowUp')index--;if(event.key==='ArrowDown')index++;
    if(event.key==='Home')column=0;if(event.key==='End')column=Number(panel.body.getAttribute('aria-colcount'))-1;
    index=Math.max(0,Math.min(model.rows.length-1,index));column=Math.max(0,Math.min(Number(panel.body.getAttribute('aria-colcount'))-1,column));
    focusTarget={index,column};const candidate=panel.canvas.querySelector(`[data-row-index="${index}"] [data-column-index="${column}"]`);
    if(candidate){focusCell(candidate);focusTarget=null;return;}
    const first=panel.canvas.querySelector('.planning-resource-cell'),width=first?parseFloat(first.style.width):1;
    const {view}=store.read();store.setView({resourceScrollTop:index*RESOURCE_ROW_HEIGHT,scrollLeft:column*width});
  });
  lifetime.own(()=>{summaries.clear();model=null;previousData=null;focusTarget=null;});
  return {
    render(data,view,calendar) {
      const visible=options.showResources!==false && data.resources.length>0,filters=settings(),labels=data.labels;
      heading.hidden=!visible;panel.root.hidden=!visible || !!filters.collapsed;
      if(!visible) {
        if(model){panel.canvas.replaceChildren();panel.leftCanvas.replaceChildren();summaries.clear();model=null;previousData=null;previousKey='';signature='';}
        return;
      }
      const key=JSON.stringify([view.collapsedResources,filters,calendar.start,calendar.end,calendar.width,view.mode]);
      const changed=data!==previousData || key!==previousKey;
      const active=data.resourceFilter;
      if(changed) {
        model=resourceRows(data,view,calendar,summaries);previousData=data;previousKey=key;
        title.textContent=labels.resourceUsage || 'Resource usage';toggle.textContent=filters.collapsed?'▸':'▾';toggle.setAttribute('aria-expanded',String(!filters.collapsed));
        toggle.setAttribute('aria-label',(filters.collapsed?(labels.expand || 'Expand'):(labels.collapse || 'Collapse'))+' '+title.textContent);
        const defaults={hideUnused:'Hide unused pools',onlyOverallocated:'Only overallocated',showTotal:'Total assignments',showSelected:'Selected assignments'};
        for(const [name,{label,input}] of checks){input.checked=!!filters[name];label.lastChild.textContent=labels[name] || defaults[name];}
        count.textContent=String(model.pools.size)+' '+(model.pools.size===1?(labels.pool || 'Pool'):(labels.pools || 'Pools'));
        filter.hidden=!active;filter.textContent=active?[active.name || active.resourceId || active.groupId,active.start,active.end].filter(Boolean).join(' · '):'';
        if(active?.clearAction) {
          const clear=doc.createElement('button');clear.type='button';clear.textContent='×';clear.setAttribute('aria-label',labels.clearFilter || 'Clear resource filter');
          Object.assign(clear.dataset,{hostAction:active.clearAction,targetKind:active.resourceId?'resources':'hierarchy',targetId:active.resourceId ?? active.groupId});filter.append(clear);
        }
        panel.leftHeader.textContent=(labels.resource || 'Resource pool')+' · '+(options.resourceUnit || 'FTE');
        const height=Math.max(34,model.rows.length*RESOURCE_ROW_HEIGHT)+16;
        panel.root.style.gridTemplateRows='56px '+Math.min(options.resourceMaxHeight ?? 324,height)+'px';
        for(const canvas of [panel.canvas,panel.leftCanvas])canvas.style.height=height+'px';
        panel.leftCanvas.style.minWidth='425px';
      }
      if(filters.collapsed)return;
      panel.body.scrollTop=view.resourceScrollTop;panel.left.scrollTop=view.resourceScrollTop;panel.body.scrollLeft=view.scrollLeft;
      const window=resourceWindow(model.rows.length,view.resourceScrollTop,panel.body.clientHeight,calendar.bottomCells,view.scrollLeft,panel.body.clientWidth);
      const nextSignature=JSON.stringify(window);
      panel.body.setAttribute('role','grid');panel.body.setAttribute('aria-rowcount',model.rows.length);panel.body.setAttribute('aria-colcount',calendar.bottomCells.length);
      if(changed || signature!==nextSignature) {
        panel.leftCanvas.replaceChildren();panel.canvas.replaceChildren();
        if(!model.rows.length){panel.leftCanvas.textContent=labels.noResources || 'No matching resource pools';panel.canvas.textContent='—';}
        for(let index=window.start;index<=window.end;index++) {
          const row=model.rows[index],left=node(doc,'planning-resource-row planning-resource-left'),right=node(doc,'planning-resource-row planning-resource-right');
          const target={kind:row.pool?'resources':'hierarchy',id:row.pool?.id ?? row.node.id};
          const name=row.pool?.name ?? row.node.name ?? row.node.id;
          const scope=(row.comparison?'alternative_':'')+row.scope;
          const activeMatch=active && ((active.resourceId!==undefined && active.resourceId===row.pool?.id) || active.groupId===row.node.id);
          for(const owner of [left,right]) {
            owner.style.top=index*RESOURCE_ROW_HEIGHT+'px';owner.dataset.rowIndex=index;owner.dataset.rowKey=row.key;
            Object.assign(owner.dataset,{targetKind:target.kind,targetId:target.id,scope,resourceNode:row.node.id});
            if(row.scope==='assigned' || !row.pool || row.collapsed)owner.dataset.doubleToggle=row.node.id;
            if(row.comparison)owner.classList.add('planning-resource-comparison');
          }
          left.style.paddingLeft=row.depth*16+'px';left.tabIndex=0;
          right.setAttribute('role','row');right.setAttribute('aria-rowindex',index+1);
          if(row.scope==='assigned' || !row.pool || row.collapsed) {
            const button=doc.createElement('button');button.type='button';button.className='planning-resource-toggle';button.dataset.toggleResource=row.node.id;
            button.textContent=row.collapsed?'▸':'▾';button.setAttribute('aria-expanded',String(!row.collapsed));
            button.setAttribute('aria-label',(row.collapsed?(labels.expand || 'Expand'):(labels.collapse || 'Collapse'))+' '+name);left.append(button);
          }
          const label=doc.createElement('span');label.dataset.part='resource-label';
          if(row.scope==='assigned' || !row.pool || row.collapsed)label.append(doc.createTextNode(name+(!row.pool && !row.comparison?'':' · ')));
          else {const branch=doc.createElement('span');branch.dataset.part='resource-branch';branch.textContent='↳ ';label.append(branch);}
          const scopeLabel=doc.createElement('span');scopeLabel.dataset.part='resource-scope';
          scopeLabel.textContent=row.comparison?(row.scope==='selected'?(labels.comparisonSelected || 'Alternative Selected Projects'):(labels.comparisonTotal || 'Alternative Total Assignments')):
            !row.pool?'':({assigned:labels.assignedCapacity || 'Pool capacity',total:labels.total || 'Total assignments',selected:labels.selected || 'Selected projects'}[row.scope]);
          label.append(scopeLabel);
          left.append(label);
          if(row.pool) {
            const range={start:calendar.start,end:calendar.bottomCells.at(-1).end};
            left.dataset.tooltip=capacityDetails(row.pool,periodSummary(row.pool,range,summaries),{labels,unit:options.resourceUnit || 'FTE'});
          }
          if(row.scope==='assigned' && row.pool.hasAssignments!==false) {
            const whole={start:calendar.start,end:calendar.bottomCells.at(-1).end},capacity=periodSummary(row.pool,whole,summaries),defined=row.pool.definedCapacity ?? row.pool.capacity;
            for(const [condition,text,kind] of [[capacity.minCapacity<defined-.0001,labels.underassignment || 'Underassignment','under'],[capacity.maxCapacity>defined+.0001,labels.overassignment || 'Overassignment','over']]) {
              if(condition){const badge=doc.createElement('span');badge.className='planning-capacity-badge';badge.dataset.capacityStatus=kind;badge.textContent=text;left.append(badge);}
            }
          }
          if(activeMatch)left.classList.add('planning-resource-filtered');
          for(let column=window.colFirst;column<=window.colLast;column++) {
            const period=calendar.bottomCells[column],result=resourceCell(row,period,model.pools,summaries),cell=node(doc,'planning-resource-cell');
            Object.assign(cell.style,{left:period.x+'px',width:period.width+'px'});
            Object.assign(cell.dataset,{targetKind:target.kind,targetId:target.id,rowIndex:index,columnIndex:column,start:period.start,end:period.end,periodLabel:period.label,scope,resourceNode:row.node.id});
            cell.setAttribute('role','gridcell');cell.tabIndex=index===window.start && column===window.colFirst?0:-1;
            cell.setAttribute('aria-colindex',column+1);
            cell.textContent=result.value===null?'':result.value===0 && row.scope!=='assigned'?'—':formatResourceValue(result.value);
            cell.dataset.capacity=String(result.minCapacity ?? '');cell.dataset.demand=String(result.maxDemand ?? '');cell.dataset.excess=String(result.maxExcess ?? '');
            cell.dataset.overallocated=String(result.isOverallocated);
            const details=row.pool?capacityDetails(row.pool,result,{labels,unit:options.resourceUnit || 'FTE'}).split('\n'):[name];
            const description=[name,period.start+' → '+period.end,...details.slice(1)];
            if(result.value!==null) {
              description.push((labels.demand || 'Demand')+': '+formatResourceValue(result.maxDemand),
                (labels.capacity || 'Capacity')+': '+formatResourceValue(result.minCapacity),
                (result.isOverallocated?(labels.excess || 'Overallocated'):(labels.available || 'Available'))+': '+formatResourceValue(result.isOverallocated?result.maxExcess:result.minAvailable)+' '+(options.resourceUnit || 'FTE'));
            }
            const tooltip=options.resourceTooltipDetails==='capacity'?[...details,...(result.value!==null?[description.at(-1)]:[])]:description;
            cell.dataset.tooltip=tooltip.join('\n');cell.setAttribute('aria-label',description.join(' · '));
            if(row.scope==='assigned') {
              const defined=row.pool.definedCapacity ?? row.pool.capacity;
              if(row.pool.hasAssignments===false)cell.classList.add('planning-capacity-unassigned');
              else {
                if(result.minCapacity<defined-.0001)cell.classList.add('planning-capacity-under');
                if(result.maxCapacity>defined+.0001)cell.classList.add('planning-capacity-over');
              }
            }else if(result.isOverallocated)cell.classList.add('planning-resource-overallocated');
            if(activeMatch && (!active.start || period.start<=active.end && period.end>=active.start))cell.classList.add('planning-resource-filtered');
            right.append(cell);
          }
          panel.leftCanvas.append(left);panel.canvas.append(right);
        }
        signature=nextSignature;
      }
      // Only visible header periods need warnings; summary caches are instance-owned.
      const headerCells=panel.headerInner.querySelectorAll('.planning-header-tier:last-child > .planning-header-cell');
      for(let column=window.colFirst;column<=window.colLast;column++) {
        const period=calendar.bottomCells[column],warning=[...model.pools.values()].some(pool=>['total','selected'].some(scope=>periodSummary(pool,period,summaries,scope).isOverallocated));
        const cell=headerCells[column];if(cell){cell.classList.toggle('planning-resource-overallocated',warning);cell.title=warning?(labels.periodOverallocated || 'Overallocated during this period'):period.label;}
      }
      if(focusTarget) {
        const cell=panel.canvas.querySelector(`[data-row-index="${focusTarget.index}"] [data-column-index="${focusTarget.column}"]`);
        if(cell){focusCell(cell);focusTarget=null;}
      }
    }
  };
}
