/** Delegated selection, menus, hover and pointer edits owned by one workspace. */
import {shiftTask} from '../calendar/index.js';
import {createActionController,validateActions,actionAllowed} from './actions.js';
import {createContextMenu} from './menu.js';
import {createEditor} from './editor.js';
import {createDiagnostics} from './diagnostics.js';

/** @param {HTMLElement} node Rendered entity. @returns {object|null} Opaque target. */
function targetOf(node) {
  if(!node?.dataset.targetId)return null;
  return {kind:node.dataset.targetKind,id:node.dataset.targetId,...(node.dataset.overlayId?{overlayId:node.dataset.overlayId}:{})};
}

/** @param {HTMLElement} node Rendered resource row/cell. @returns {object} Delivered period context. */
function contextOf(node) {
  const result={};for(const field of ['start','end','scope','periodLabel','resourceNode'])if(node?.dataset[field]!==undefined)result[field]=node.dataset[field];return result;
}

/** Compose instance-owned interactions without retaining stale entity objects.
 * @param {HTMLElement} frame Owned root. @param {HTMLElement} toolbar Toolbar.
 * @param {object} store Store. @param {object} lifetime Lifetime.
 * @param {object} options Event sink and declarative actions. @param {Function} calendar Read current scale.
 */
export function createInteractions({frame,toolbar,store,lifetime,options,calendar}) {
  const doc=frame.ownerDocument,win=doc.defaultView,actions=createActionController({store,onEvent:options.onEvent});
  const commands=validateActions(options.contextActions),menu=createContextMenu(frame,lifetime);
  const commandIndex=new Map(),pendingCommands=[...commands];
  while(pendingCommands.length){const command=pendingCommands.pop();commandIndex.set(command.id,command);for(const child of command.children ?? [])pendingCommands.push(child);}
  const editor=createEditor({frame,store,actions,lifetime,options});
  const diagnostics=createDiagnostics({frame,store,actions,lifetime,options});
  const openTarget=target=>{
    if(target.kind!=='dependencies' || options.dependencyEditor!=='successor')return actions.open(target);
    const resolved=actions.resolve(target);if(!resolved)return false;
    const endpoint=resolved.record.successor,owner={kind:endpoint.kind==='project'?'projects':'tasks',id:endpoint.id,...(target.overlayId?{overlayId:target.overlayId}:{})};
    if(endpoint.kind==='task')return actions.open(owner);
    if(endpoint.kind==='project' && options.projectDependenciesCommand){actions.command({id:options.projectDependenciesCommand},owner);return true;}
    return false;
  };
  const tooltip=doc.createElement('div');tooltip.className='planning-tooltip';tooltip.setAttribute('role','tooltip');tooltip.hidden=true;frame.append(tooltip);
  const status=doc.createElement('p');status.className='planning-error planning-status';status.setAttribute('role','alert');status.hidden=true;toolbar.after(status);
  const editLabel=doc.createElement('label'),edit=doc.createElement('input'),hoverLabel=doc.createElement('label'),hover=doc.createElement('input');
  edit.type='checkbox';edit.dataset.control='edit';hover.type='checkbox';hover.dataset.control='hover';
  editLabel.append(edit,doc.createTextNode(''));hoverLabel.append(hover,doc.createTextNode(''));toolbar.append(editLabel,hoverLabel);
  let hoverTimer=null,hovered=null,drag=null,suppressClick=false,selectionTimer=null;
  const cancelSelection=()=>{selectionTimer?.();selectionTimer=null;};
  const hideHover=()=>{hoverTimer?.();hoverTimer=null;hovered=null;tooltip.hidden=true;};
  const place=event=>{
    tooltip.style.left=Math.max(4,Math.min(event.clientX+12,win.innerWidth-tooltip.offsetWidth-8))+'px';
    tooltip.style.top=Math.max(4,Math.min(event.clientY+16,win.innerHeight-tooltip.offsetHeight-8))+'px';
  };
  const stopDrag=()=>{
    if(!drag)return;
    const current=drag;drag=null;
    if(current.node.hasPointerCapture(current.pointerId))current.node.releasePointerCapture(current.pointerId);
    current.node.classList.remove('planning-dragging');tooltip.hidden=true;
  };
  /** @param {object} target Current target. @param {MouseEvent} event Invocation. */
  const openMenu=(target,event,context={})=>{
    const {data,view}=store.read(),entries=[];hideHover();cancelSelection();
    if(['tasks','dependencies'].includes(target.kind))entries.push({label:data.labels.edit || 'Edit',disabled:!actions.canEdit(target,target.kind==='dependencies'?'dependency':'task'),run:()=>openTarget(target)});
    // Each entry is checked again on invocation; a formerly enabled menu is safe.
    const pending=[{source:commands,destination:entries}];
    while(pending.length) {
      const {source,destination}=pending.pop();
      for(const command of source) {
        if(!actionAllowed(command,data,view,target))continue;
        const entry={label:data.labels['command_'+command.id] || command.label,run:()=>{
          const latest=store.read();if(!actionAllowed(command,latest.data,latest.view,target))return;
          if(command.editor==='createTask')actions.openCreate(target);
          else if(command.editor==='diagnostics')diagnostics.open(target);
          else if(command.editor==='predecessors')diagnostics.open(target,'predecessors');
          else return actions.command(command,target,context);
        }};destination.push(entry);
        if(command.children){entry.children=[];pending.push({source:command.children,destination:entry.children});}
      }
    }
    menu.open(entries,event.clientX,event.clientY);
  };
  lifetime.listen(edit,'change',()=>{
    const {data,view}=store.read();store.setView({filters:{...view.filters,editEnabled:edit.checked}});
    if(options.editCommand && data.projects.length)actions.command({id:options.editCommand},{kind:'projects',id:data.projects[0].id},{enabled:edit.checked});
  });
  lifetime.listen(hover,'change',()=>{hideHover();const {view}=store.read();store.setView({filters:{...view.filters,hover:hover.checked}});});
  lifetime.listen(frame,'contextmenu',event=>{
    const node=event.target.closest('[data-target-id]'),target=targetOf(node);
    if(target){event.preventDefault();openMenu(target,event,contextOf(node));}
  });
  lifetime.listen(frame,'click',event=>{
    if(event.target.closest('.planning-editor,.planning-menu,.planning-inspector'))return;
    const extension=event.target.closest('[data-host-action]');
    if(extension){const command=commandIndex.get(extension.dataset.hostAction);if(command)actions.command(command,targetOf(extension),contextOf(extension));return;}
    if(suppressClick){suppressClick=false;return;}
    const node=event.target.closest('[data-target-id]'),target=targetOf(node);
    if(target && event.target.closest('[data-diagnostics]')){cancelSelection();diagnostics.open(target);return;}
    if(target && !event.target.closest('[data-expand],[data-toggle-resource]') && !node.dataset.scope?.startsWith('alternative_')) {
      cancelSelection();selectionTimer=lifetime.timeout(()=>{selectionTimer=null;actions.select(target,contextOf(node));},300);
    }
  });
  lifetime.listen(frame,'dblclick',event=>{
    if(event.target.closest('.planning-editor,.planning-menu,.planning-inspector'))return;
    cancelSelection();const target=targetOf(event.target.closest('[data-target-id]'));if(target?.kind==='tasks'){hideHover();actions.open(target);}
  });
  lifetime.listen(frame,'keydown',event=>{
    if(event.key==='Escape' && drag){event.preventDefault();stopDrag();store.setView({preview:null});return;}
    if(event.target.closest('.planning-editor,.planning-menu,.planning-inspector'))return;
    const node=event.target.closest('[data-target-id]'),target=targetOf(node);if(!target)return;
    if(event.key==='ContextMenu' || (event.key==='F10' && event.shiftKey)) {
      event.preventDefault();const bounds=node.getBoundingClientRect();openMenu(target,{clientX:bounds.left,clientY:bounds.bottom},contextOf(node));return;
    }
    if(event.key==='Enter' && target.kind==='tasks'){event.preventDefault();actions.open(target);}
    if(event.key===' ' && !node.dataset.scope?.startsWith('alternative_')){event.preventDefault();actions.select(target,contextOf(node));}
  });
  lifetime.listen(frame,'pointerover',event=>{
    const node=event.target.closest('[data-target-id]');
    if(!node || node.contains(event.relatedTarget) || drag || store.read().view.filters.hover===false)return;
    hideHover();const target=targetOf(node),resolved=actions.resolve(target);if(!resolved)return;
    hovered=node;
    hoverTimer=lifetime.timeout(()=>{
      hoverTimer=null;if(!node.isConnected || hovered!==node)return;
      const {record}=actions.resolve(target) ?? {};if(!record)return;
      tooltip.textContent=node.dataset.tooltip ?? record.tooltip ?? [record.name,record.start && record.start+' → '+record.end,record.description].filter(Boolean).join('\n');
      if(node.matches('.planning-resource-cell') && node.dataset.excess!=='') {
        const lines=tooltip.textContent.split('\n'),title=doc.createElement('strong'),status=doc.createElement('div');
        title.textContent=lines[0];status.textContent=lines.at(-1);status.className='planning-tooltip-status';status.dataset.overallocated=node.dataset.overallocated;
        tooltip.replaceChildren(title,doc.createTextNode('\n'),status,doc.createTextNode(lines.slice(1,-1).join('\n')));
      }
      tooltip.hidden=false;place(event);
    },options.tooltipDelay ?? 1000);
  });
  lifetime.listen(frame,'pointerout',event=>{if(hovered && !hovered.contains(event.relatedTarget))hideHover();});
  lifetime.listen(frame,'pointermove',event=>{
    if(!tooltip.hidden)place(event);
    if(!drag || drag.pointerId!==event.pointerId)return;
    if(!actions.canEdit(drag.target,drag.edge==='progress'?'progress':'dates')){stopDrag();store.setView({preview:null});return;}
    const delta=event.clientX-drag.x;
    const fields=drag.edge==='progress'?{progress:Math.max(0,Math.min(100,Math.round(drag.record.progress+delta/drag.width*100)))}:
      (()=>{const shifted=shiftTask(drag.record,calendar().dragDays(drag.startX,delta),drag.edge);return {start:shifted.start,end:shifted.end};})();
    drag.moved=Math.abs(delta)>=3;
    tooltip.textContent=drag.record.name+'\n'+(drag.edge==='progress'?fields.progress+'%':fields.start+' → '+fields.end);tooltip.hidden=false;place(event);
    store.setView({preview:{target:drag.target,...fields}});
  });
  lifetime.listen(frame,'pointerdown',event=>{
    if(event.button!==0)return;
    const node=event.target.closest('.planning-bar[data-target-kind=tasks]'),target=targetOf(node);if(!target)return;
    const edge=event.target.dataset.edge ?? 'move',{data,view}=store.read(),operation=edge==='progress'?'progress':'dates';
    if(view.pendingRequestId || !actions.canEdit(target,operation))return;
    event.preventDefault();hideHover();menu.close();node.focus();node.setPointerCapture(event.pointerId);node.classList.add('planning-dragging');
    const {record,overlay}=actions.resolve(target);
    drag={node,target,pointerId:event.pointerId,x:event.clientX,startX:calendar().dateToX(record.start),record:{...record,progress:record.progress ?? 0},
      width:parseFloat(node.style.width),edge,moved:false,scope:data.scope,revision:data.revision,overlayRevision:overlay?.revision};
  });
  lifetime.listen(frame,'pointerup',event=>{
    if(!drag || event.pointerId!==drag.pointerId)return;
    const current=drag,preview=store.read().view.preview;stopDrag();
    if(!current.moved || !preview){store.setView({preview:null});return;}
    suppressClick=true;lifetime.timeout(()=>{suppressClick=false;},0);
    const values=current.edge==='progress'?{progress:preview.progress}:{start:preview.start,end:preview.end};
    const changed=current.edge==='progress'?values.progress!==current.record.progress:values.start!==current.record.start || values.end!==current.record.end;
    if(!changed || !actions.request(current.edge==='progress'?'progress':'dates',current.target,values))store.setView({preview:null});
  });
  lifetime.listen(frame,'pointercancel',()=>{stopDrag();store.setView({preview:null});});
  lifetime.listen(frame,'lostpointercapture',()=>{if(drag){stopDrag();store.setView({preview:null});}});
  let menuScope=store.read().data.scope,menuRevision=store.read().data.revision;
  lifetime.own(store.subscribe(reason=>{
    if(reason==='destroy')return;
    const {data,view}=store.read();
    if(reason==='data') {
      hideHover();cancelSelection();
      if(data.scope!==menuScope || data.revision!==menuRevision)menu.close();
      menuScope=data.scope;menuRevision=data.revision;
    }
    if(drag && (data.scope!==drag.scope || data.revision!==drag.revision || actions.resolve(drag.target)?.overlay?.revision!==drag.overlayRevision || !actions.canEdit(drag.target,drag.edge==='progress'?'progress':'dates'))) {
      stopDrag();store.setView({preview:null});
    }
    const target=view.draft?.values?.target;
    if(target && !actions.resolve(target)){store.setView({draft:null,error:'The edited item is no longer available.'});}
  }));
  lifetime.own(()=>{stopDrag();hideHover();cancelSelection();actions.destroy();tooltip.remove();status.remove();commandIndex.clear();});
  return {
    cancelSelection,
    openDependency(entry){hideHover();return openTarget({kind:'dependencies',id:entry.dependency.id,...(entry.overlay?{overlayId:entry.overlay.id}:{})});},
    render() {
      const {data,view}=store.read();editLabel.hidden=!data.capabilities.edit;edit.checked=!!view.filters.editEnabled;
      status.hidden=!view.error || !!view.draft;status.textContent=view.error ?? '';
      editLabel.lastChild.textContent=data.labels.editMode || 'Enable editing';hover.checked=view.filters.hover!==false;hoverLabel.lastChild.textContent=data.labels.hover || 'Hover details';
      for(const node of frame.querySelectorAll('[data-target-id]')) {
        const target=targetOf(node),resolved=actions.resolve(target);if(!resolved)continue;
        const allowed=actions.canEdit(target,'dates'),progressAllowed=actions.canEdit(target,'progress');
        node.dataset.editable=String(allowed || progressAllowed);
        for(const handle of node.querySelectorAll('.planning-handle'))handle.dataset.editable=String(handle.dataset.edge==='progress'?progressAllowed:allowed);
        if(view.filters.hover===false)node.title=node.getAttribute('aria-label') || resolved.record.name || '';else node.removeAttribute('title');
        const selection=view.selection?.values?.target;node.classList.toggle('planning-selected',JSON.stringify(selection)===JSON.stringify(target));
        if(!node.classList.contains('planning-bar') || target.kind!=='tasks')continue;
        const record=resolved.record,preview=view.preview?.target;
        const current=preview && JSON.stringify(preview)===JSON.stringify(target)?{...record,...view.preview}:record;
        node.style.left=calendar().dateToX(current.start)+'px';
        if(record.start!==record.end)node.style.width=Math.max(24,calendar().endDateToX(current.end)-calendar().dateToX(current.start))+'px';
        const progress=node.querySelector('.planning-progress');if(progress)progress.style.width=(current.progress ?? 0)+'%';
        const handle=node.querySelector('.planning-handle-progress');if(handle)handle.style.left=(current.progress ?? 0)+'%';
      }
      editor.render();
    }
  };
}
