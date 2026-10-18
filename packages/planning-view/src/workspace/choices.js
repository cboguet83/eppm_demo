/** Optional host-provided predecessor choices, separate from hydrated schedules. */
import {ContractError} from '../contracts/index.js';

/** Append a project-scoped endpoint chooser with cancellable host reads.
 * @param {object} options DOM owner, delivered data, endpoint and injected reader.
 * @returns {Function} Cancel this field's pending read.
 */
export function createEndpointChoices({owner,select,value,data,overlay,target,loadChoices,onChange,label}) {
  const doc=owner.ownerDocument,projectLabel=doc.createElement('label'),project=doc.createElement('select');
  projectLabel.textContent=data.labels.predecessorProject || 'Predecessor project';project.dataset.choiceProject='true';projectLabel.append(project);owner.prepend(projectLabel);
  project.setAttribute('aria-label',projectLabel.firstChild.textContent);
  const projects=data.choiceProjects ?? data.projects,ownerId=target.kind==='projects'?target.id:
    (overlay?.tasks ?? data.tasks).find(row=>row.id===target.id)?.projectId;
  const selectedProject=value.projectId ?? (value.kind==='project'?value.id:null) ??
    (overlay?.tasks ?? data.tasks).find(row=>row.id===value.id)?.projectId ?? ownerId;
  for(const row of projects) {
    const option=doc.createElement('option');option.value=row.id;option.textContent=row.name;option.selected=row.id===selectedProject;project.append(option);
  }
  if(!projects.some(row=>row.id===selectedProject)) {
    const unavailable=doc.createElement('option');unavailable.value=selectedProject ?? '';unavailable.textContent=data.labels.unavailable || 'Unavailable';unavailable.selected=true;project.prepend(unavailable);
  }
  const error=doc.createElement('p');error.className='planning-error';error.hidden=true;owner.append(error);
  let controller=null,disposed=false,selected=value,lastProject=project.value;
  const append=(endpoint,name,chosen)=>{
    const option=doc.createElement('option');option.value=JSON.stringify(endpoint);option.textContent=name;
    option.selected=endpoint.kind===chosen?.kind && endpoint.id===chosen?.id;select.append(option);
  };
  const read=async(initial=false)=>{
    controller?.abort();controller=new doc.defaultView.AbortController();const active=controller;
    const chosen=project.value===lastProject?selected:null;lastProject=project.value;
    select.disabled=true;select.setAttribute('aria-busy','true');
    try {
      const choices=await loadChoices({projectId:project.value,scope:data.scope,revision:data.revision,overlayId:overlay?.id ?? null,signal:active.signal});
      if(disposed || active.signal.aborted)return;
      if(!Array.isArray(choices) || choices.some(row=>!row || typeof row.id!=='string' || !row.id.trim() || typeof row.name!=='string') || new Set(choices.map(row=>row.id)).size!==choices.length)throw new ContractError('choices');
      select.replaceChildren();
      if(project.value!==ownerId)append({kind:'project',id:project.value},data.labels.wholeProject || 'Whole project',chosen);
      for(const row of choices)if(!(target.kind==='tasks' && row.id===target.id))append({kind:'task',id:row.id,projectId:project.value},row.name,chosen);
      if(chosen && ![...select.options].some(option=>JSON.parse(option.value).id===chosen.id && JSON.parse(option.value).kind===chosen.kind))append(chosen,data.labels.unavailable || 'Unavailable',chosen);
      select.disabled=select.options.length===0;
      if(select.value)selected=JSON.parse(select.value);
      if(!initial && select.value)onChange(selected);
      label.dataset.choiceError='';error.hidden=true;error.textContent='';error.removeAttribute('role');
    }catch(_) {
      if(disposed || active.signal.aborted)return;
      select.disabled=true;label.dataset.choiceError='true';error.hidden=false;error.setAttribute('role','alert');
      error.textContent=data.labels.choicesFailed || 'Predecessors could not be loaded. Choose the project again to retry.';
    }finally {
      if(!disposed && controller===active)select.removeAttribute('aria-busy');
    }
  };
  const remember=()=>{if(!select.disabled && select.value)selected=JSON.parse(select.value);};select.addEventListener('change',remember);
  const change=()=>{void read();};project.addEventListener('change',change);void read(true);
  return ()=>{disposed=true;controller?.abort();error.remove();project.removeEventListener('change',change);select.removeEventListener('change',remember);};
}
