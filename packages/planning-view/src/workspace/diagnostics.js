/** Delivered scheduling diagnostics; fixes remain checked host requests. */

/** Create an instance-owned task/project diagnostics inspector.
 * @param {object} options Owned frame, store, action controller, lifetime and commands.
 * @returns {object} Open/close seam.
 */
export function createDiagnostics({frame,store,actions,lifetime,options}) {
  const doc=frame.ownerDocument,panel=doc.createElement('div');panel.className='planning-inspector';panel.dataset.part='constraint-diagnostics';
  panel.setAttribute('role','dialog');panel.hidden=true;frame.append(panel);let target=null,mode='diagnostics';
  const close=()=>{target=null;panel.hidden=true;};
  const render=()=>{
    if(!target)return;const resolved=actions.resolve(target);if(!resolved){close();return;}
    const {data}=store.read(),{record,overlay}=resolved;panel.replaceChildren();
    const title=doc.createElement('h3');title.textContent=(mode==='predecessors'?(data.labels.predecessors || 'Predecessors'):(data.labels.diagnostics || 'Constraint diagnostics'))+' — '+(record.name ?? record.id);panel.append(title);
    panel.setAttribute('aria-label',title.textContent);
    const tasks=overlay?.tasks ?? data.tasks,owners=new Map(tasks.map(task=>[task.id,task.projectId]));
    const dependencies=(overlay?.dependencies ?? data.dependencies).filter(dep=>target.kind==='projects'?
      (dep.successor.kind==='project'?dep.successor.id:dep.successor.projectId ?? owners.get(dep.successor.id))===target.id:
      dep.successor.kind==='task' && dep.successor.id===target.id);
    const diagnostics=[...(target.kind==='projects' && overlay?[]:record.violations ?? []),...dependencies.flatMap(dep=>(dep.diagnostics ?? []).map(text=>{
      const message=typeof text==='string'?text:text.message,name=tasks.find(task=>task.id===dep.successor.id)?.name;
      return target.kind==='projects' && name?name+' — '+message:message;
    }))];
    if(mode==='predecessors')for(const dependency of dependencies) {
      const predecessor=dependency.predecessor,row=doc.createElement('p');
      const supplied=predecessor.kind==='unavailable'?(data.labels.unavailable || 'Unavailable'):
        tasks.find(task=>predecessor.kind==='task' && task.id===predecessor.id)?.name ?? data.projects.find(project=>predecessor.kind==='project' && project.id===predecessor.id)?.name ?? predecessor.name ?? dependency.predecessorTaskName ?? dependency.predecessorName ?? predecessor.id;
      const dates=predecessor.kind==='unavailable'?null:tasks.find(task=>predecessor.kind==='task' && task.id===predecessor.id) ?? predecessor;
      row.textContent=supplied+' · '+dependency.type+' · '+(dependency.lagDays ?? 0)+(dates?.start?' · '+dates.start+' → '+dates.end:'');panel.append(row);
    }
    for(const text of new Set(diagnostics.map(item=>typeof item==='string'?item:item.message))) {
      const row=doc.createElement('p');row.textContent=text;panel.append(row);
    }
    if(!diagnostics.length){const text=doc.createElement('p');text.textContent=data.labels.noDiagnostics || 'No scheduling violations.';panel.append(text);}
    const fix=doc.createElement('button');fix.type='button';fix.dataset.fixDiagnostic='true';fix.textContent=target.kind==='projects'?(data.labels.manageDependencies || 'Manage dependencies'):(data.labels.edit || 'Fix');
    fix.disabled=!actions.canEdit(target,target.kind==='projects'?'command':'task');panel.append(fix);
    const button=doc.createElement('button');button.type='button';button.dataset.closeDiagnostics='true';button.textContent=data.labels.close || 'Close';panel.append(button);
  };
  lifetime.listen(panel,'click',event=>{
    if(event.target.closest('[data-close-diagnostics]'))close();
    if(event.target.closest('[data-fix-diagnostic]') && target) {
      if(target.kind==='projects' && options.projectDependenciesCommand){actions.command({id:options.projectDependenciesCommand},target);close();}
      else if(actions.open(target))close();
    }
  });
  lifetime.listen(frame,'keydown',event=>{if(event.key==='Escape')close();});
  lifetime.own(store.subscribe(()=>render()));lifetime.own(()=>{close();panel.remove();});
  return {open(value,kind='diagnostics'){target=value;mode=kind;panel.hidden=false;render();panel.querySelector('button')?.focus();},close};
}
