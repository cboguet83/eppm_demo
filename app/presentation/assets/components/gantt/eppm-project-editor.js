/** EPPM's revision-checked batch project-dependency workflow, scoped to one host. */
import {createEndpointChoices} from './planning-view/src/workspace/choices.js';
import {dependencyFor,dependencyValues} from './eppm-contract.js';

/** Compose the application-owned project dependency panel.
 * @param {HTMLElement} frame Workspace. @param {object} transport Application transport.
 * @param {object} choices Cancellable authorized predecessor reader.
 * @param {object} lifetime Owning host lifetime.
 * @returns {object} Open/receive/close interface.
 */
export function createProjectEditor({frame,transport,choices,lifetime}) {
  const doc=frame.ownerDocument,form=doc.createElement('form'),title=doc.createElement('h3'),rows=doc.createElement('fieldset');
  const status=doc.createElement('p'),add=doc.createElement('button'),reload=doc.createElement('button'),save=doc.createElement('button'),cancel=doc.createElement('button');
  form.className='planning-inspector eppm-project-editor';form.dataset.part='project-dependency-editor';form.setAttribute('role','dialog');form.setAttribute('aria-modal','true');form.hidden=true;
  status.setAttribute('role','alert');add.type='button';add.textContent='Add predecessor';reload.type='button';reload.textContent='Reload dependencies (discard edits)';
  save.type='submit';save.textContent='Save';cancel.type='button';cancel.textContent='Cancel';
  form.append(title,rows,status,add,reload,save,cancel);frame.append(form);
  let draft=null,disposers=[],restore=null;
  const clear=()=>{for(const dispose of disposers)dispose();disposers=[];rows.replaceChildren();};
  const allowed=()=>{
    if(!draft)return false;
    const host=transport.host(),permissions=host.permissions ?? {},plan=host.alternatives?.[draft.project];
    return host.edit_enabled===true && (permissions.edit_all===true || (permissions.editable_projects ?? []).some(id=>String(id)===draft.project)) &&
      (!Object.keys(host.alternatives ?? {}).length || plan?.editable===true);
  };
  const state=(message,busy=false,failed=false)=>{
    status.textContent=message;rows.disabled=busy || !allowed();add.disabled=busy || !allowed() || !draft?.revision;save.disabled=add.disabled;reload.hidden=!failed;
  };
  const close=()=>{clear();draft=null;form.hidden=true;if(restore?.isConnected)restore.focus();restore=null;};
  const append=dependency=>{
    const host=transport.host(),row=doc.createElement('div'),select=doc.createElement('select'),label=doc.createElement('label');
    const type=doc.createElement('select'),typeLabel=doc.createElement('label'),lag=doc.createElement('input'),lagLabel=doc.createElement('label'),remove=doc.createElement('button');
    row.className='planning-dependency-field';row.dataset.dependencyId=dependency.id;label.textContent='Predecessor';select.setAttribute('aria-label','Predecessor');label.append(select);row.append(label);
    typeLabel.textContent='Link type';type.dataset.field='type';for(const code of ['FS','SS','FF','SF']){const option=doc.createElement('option');option.value=code;option.textContent=code;type.append(option);}type.value=dependency.type;typeLabel.append(type);
    lagLabel.textContent='Lag';lag.type='number';lag.step='1';lag.min='-2147483648';lag.max='2147483647';lag.value=dependency.lagDays ?? 0;lag.dataset.field='lagDays';lagLabel.append(lag);
    remove.type='button';remove.textContent='Remove';row.append(typeLabel,lagLabel,remove);rows.append(row);
    const data={scope:host.view_scope ?? host.scope_token,revision:host.task_revision,labels:{},projects:[],tasks:[],
      choiceProjects:(host.all_projects ?? []).filter(project=>String(project.id)!==draft.project).map(project=>({id:String(project.id),name:project.name}))};
    const overlay=draft.plan?{id:'alternative:'+draft.plan.id,tasks:[]}:null;
    const entry={dependency,row,select,type,lag};draft.rows.push(entry);
    const selected=doc.createElement('option');selected.value=JSON.stringify(dependency.predecessor);selected.textContent='Loading…';select.append(selected);
    const dispose=createEndpointChoices({owner:row,select,value:dependency.predecessor,data,overlay,target:{kind:'projects',id:draft.project},
      loadChoices:request=>choices.read(request),label,onChange:endpoint=>{entry.dependency={...entry.dependency,predecessor:endpoint};}});
    const selectChange=()=>{if(select.value && !select.disabled)entry.dependency={...entry.dependency,predecessor:JSON.parse(select.value)};};
    const removeRow=()=>{dispose();row.remove();if(draft)draft.rows=draft.rows.filter(item=>item!==entry);};
    select.addEventListener('change',selectChange);remove.addEventListener('click',removeRow);
    disposers.push(()=>{dispose();select.removeEventListener('change',selectChange);remove.removeEventListener('click',removeRow);});
  };
  const load=()=>{
    if(!allowed())return;clear();draft.rows=[];draft.revision=null;state('Loading dependencies…',true);
    const plan=transport.host().alternatives?.[draft.project];draft.plan=plan?{id:plan.id,revision:plan.revision}:null;
    if(plan) {
      draft.revision=plan.revision;draft.baseline=(plan.dependencies ?? []).filter(row=>row.task_id==null);
      for(const dep of draft.baseline)append(dependencyFor(dep,draft.project));
      state('Links produce scheduling warnings; they never change dates automatically.');return;
    }
    draft.nonce=transport.event('load_project_dependencies',{projectId:draft.project},draft.project);
  };
  const receive=response=>{
    if(!draft || response.nonce!==draft.nonce || String(response.project_id)!==draft.project)return;
    if(response.error){state(response.error+' Retry saving, or reload dependencies to discard your edits and review the latest source.',false,true);return;}
    if(response.action==='save_project_dependencies'){close();return;}
    draft.revision=response.panel.revision;draft.baseline=response.panel.dependencies;clear();draft.rows=[];
    for(const dep of draft.baseline)append(dependencyFor(dep,draft.project));
    state(draft.baseline.some(dep=>dep.is_evaluable===false)?'Some dependencies cannot yet be evaluated because project or step dates are missing. Links never change dates automatically.':'Links produce scheduling warnings; they never change dates automatically.');
  };
  lifetime.listen(add,'click',()=>{
    if(!allowed() || !draft?.revision)return;
    const project=(transport.host().all_projects ?? []).find(row=>String(row.id)!==draft.project);
    if(project)append({id:'new-'+doc.defaultView.crypto.randomUUID(),predecessor:{kind:'project',id:String(project.id)},type:'FS',lagDays:0});
  });
  lifetime.listen(cancel,'click',close);lifetime.listen(reload,'click',load);
  lifetime.listen(form,'keydown',event=>{if(event.key==='Escape'){event.preventDefault();close();}});
  lifetime.listen(form,'submit',event=>{
    event.preventDefault();if(!allowed() || save.disabled)return;
    if(draft.rows.some(row=>row.select.disabled || !row.lag.value.trim() || !Number.isInteger(Number(row.lag.value)))){state('Choose a loaded predecessor and enter a whole number of calendar days for each link.',false,true);return;}
    const values=draft.rows.map(entry=>({...dependencyValues([{...entry.dependency,type:entry.type.value,lagDays:Number(entry.lag.value)}])[0],id:entry.dependency.id}));
    const retained=new Set(),upserts=[];
    for(const row of values) {
      const identity=String(row.id).replace('project:',''),original=draft.baseline.find(dep=>String(dep.id)===identity);
      const {id:_,...fields}=row;
      if(original)retained.add(original.id);
      if(!original || Object.entries(fields).some(([key,value])=>original[key]!==value))upserts.push({...fields,...(original?{id:original.id}:{})});
    }
    const deleted_ids=draft.baseline.filter(dep=>!retained.has(dep.id)).map(dep=>dep.id);
    const command=draft.plan?'manage_dependencies':'save_project_dependencies';
    const payload=draft.plan?{dependencies:values.map(({id:_,...row})=>row),revision:draft.plan.revision}:{upserts,deleted_ids,revision:draft.revision};
    draft.nonce=transport.event(command,{projectId:draft.project,planRevision:draft.plan?.revision ?? null,values:payload},draft.project,draft.plan?'alternative:'+draft.plan.id:null);
    state('Saving dependencies…',true);
  });
  lifetime.own(()=>{close();form.remove();});
  return {
    open(project) {
      close();restore=doc.activeElement;draft={project:String(project),rows:[],baseline:[],revision:null,nonce:null,plan:null};
      if(!allowed()){close();return false;}
      const name=(transport.host().all_projects ?? []).find(row=>String(row.id)===draft.project)?.name ?? draft.project;
      title.textContent='Manage dependencies — '+name;form.setAttribute('aria-label',title.textContent);form.hidden=false;load();cancel.focus();return true;
    },receive,close,
    refresh(){if(draft && !allowed())state('Editing permission is no longer available.',true);}
  };
}
