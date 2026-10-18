/** Draft-preserving task/dependency forms; authoritative saves stay with the host. */
import {canEdit,resolveTarget} from './actions.js';
import {ContractError} from '../contracts/index.js';
import {createEndpointChoices} from './choices.js';

/** @param {HTMLElement} frame Owned root. @param {object} store Store. @param {object} actions Correlated actions. @param {object} lifetime Lifetime. */
export function createEditor({frame,store,actions,lifetime,options={}}) {
  const doc=frame.ownerDocument,form=doc.createElement('form'),title=doc.createElement('h3'),fields=doc.createElement('fieldset');
  const error=doc.createElement('p'),save=doc.createElement('button'),cancel=doc.createElement('button');
  form.className='planning-inspector planning-editor';form.setAttribute('role','dialog');form.setAttribute('aria-modal','true');form.hidden=true;
  error.setAttribute('role','alert');error.className='planning-error';save.type='submit';cancel.type='button';cancel.dataset.cancelEditor='true';
  form.append(title,fields,error,save,cancel);frame.append(form);
  let signature='',target=null,restore=null,choiceDisposers=[];
  const clearChoices=()=>{for(const dispose of choiceDisposers)dispose();choiceDisposers=[];};
  const update=patch=>{
    const {view}=store.read();if(view.draft)store.setView({draft:{...view.draft,values:{...view.draft.values,fields:{...view.draft.values.fields,...patch}}}});
  };
  /** @param {string} name Stable field. @param {string} label Text. @param {string} type Input type. @param {unknown} value Initial value. */
  const input=(name,label,type,value,owner=fields,dependencyIndex=null)=>{
    const row=doc.createElement('label');row.textContent=label;
    const control=doc.createElement(type==='textarea'?'textarea':'input');control.dataset.field=name;
    if(type!=='textarea')control.type=type;control.value=String(value ?? '');
    if(dependencyIndex!==null)control.dataset.dependencyIndex=dependencyIndex;
    if(type==='number'){control.step='1';if(name==='progress'){control.min='0';control.max='100';}}
    row.append(control);owner.append(row);return control;
  };
  const endpointSelect=(name,label,value,data,overlay,owner=fields,dependencyIndex=null)=>{
    const row=doc.createElement('label'),select=doc.createElement('select');row.textContent=label;select.dataset.field=name;
    select.setAttribute('aria-label',label);
    if(dependencyIndex!==null)select.dataset.dependencyIndex=dependencyIndex;
    const choices=[...data.projects.map(record=>({kind:'project',id:record.id,name:record.name})),
      ...(overlay?.tasks ?? data.tasks).map(record=>({kind:'task',id:record.id,name:record.name}))];
    if(!choices.some(choice=>choice.kind===value.kind && choice.id===value.id))choices.unshift({...value,name:value.kind!=='unavailable' && value.name?value.name:data.labels.unavailable || 'Unavailable'});
    for(const choice of choices) {
      const option=doc.createElement('option');option.value=JSON.stringify({kind:choice.kind,...(choice.id?{id:choice.id}:{})});
      option.textContent=choice.name;option.selected=choice.kind===value.kind && choice.id===value.id;select.append(option);
    }
    row.append(select);owner.append(row);
    if(name==='predecessor' && options.loadChoices)choiceDisposers.push(createEndpointChoices({owner,select,value,data,overlay,target,loadChoices:options.loadChoices,label:row,
      onChange:endpoint=>{
        const {view}=store.read();if(!view.draft)return;
        if(dependencyIndex===null)update({predecessor:endpoint});
        else update({dependencies:view.draft.values.fields.dependencies.map((dep,index)=>index===dependencyIndex?{...dep,predecessor:endpoint}:dep)});
      }}));
  };
  const typeSelect=(value,labels,owner=fields,dependencyIndex=null)=>{
    const row=doc.createElement('label'),select=doc.createElement('select');row.textContent=labels.linkType || 'Link type';select.dataset.field='type';
    select.setAttribute('aria-label',row.textContent);
    if(dependencyIndex!==null)select.dataset.dependencyIndex=dependencyIndex;
    for(const type of ['FS','SS','FF','SF']){const option=doc.createElement('option');option.value=type;option.textContent=type;option.selected=type===value;select.append(option);}
    row.append(select);owner.append(row);
  };
  const render=()=>{
    const {data,view}=store.read(),draft=view.draft;
    if(!draft?.values?.target){clearChoices();form.hidden=true;signature='';target=null;if(restore?.isConnected)restore.focus();restore=null;return;}
    target=draft.values.target;const resolved=resolveTarget(data,target);
    if(!resolved){form.hidden=true;signature='';return;}
    const nextSignature=JSON.stringify([target,draft.values.create===true]),operation=target.kind==='dependencies'?'dependency':'task';
    const labels=data.labels,values=draft.values.fields;
    form.hidden=false;title.textContent=(draft.values.create?(labels.addTask || 'Add step'):(labels.edit || 'Edit'))+': '+(resolved.record.name ?? resolved.record.id);form.setAttribute('aria-label',title.textContent);
    error.textContent=view.error ?? '';save.textContent=view.pendingRequestId?(labels.saving || 'Saving…'):(labels.save || 'Save');cancel.textContent=labels.cancel || 'Cancel';
    const allowed=canEdit(data,view,target,draft.values.create?'command':operation);fields.disabled=!allowed || !!view.pendingRequestId;save.disabled=!allowed || !!view.pendingRequestId;
    if(signature===nextSignature)return;
    if(!signature)restore=doc.activeElement;
    signature=nextSignature;clearChoices();fields.replaceChildren();
    if(operation==='task') {
      for(const [name,type] of [['name','text'],['phase','text'],['start','date'],['end','date'],['progress','number'],['description','textarea']])input(name,labels[name] || name,type,values[name]);
      // Existing incoming links are part of the task save, so removals are explicit.
      const dependencies=doc.createElement('fieldset'),legend=doc.createElement('legend');
      legend.textContent=labels.dependencies || 'Dependencies';dependencies.dataset.part='incoming-dependencies';dependencies.append(legend);fields.append(dependencies);
      values.dependencies.forEach((dependency,index)=>{
        const row=doc.createElement('div'),remove=doc.createElement('button');row.className='planning-dependency-field';
        endpointSelect('predecessor',labels.predecessor || 'Predecessor',dependency.predecessor,data,resolved.overlay,row,index);
        typeSelect(dependency.type,labels,row,index);input('lagDays',labels.lag || 'Lag','number',dependency.lagDays ?? 0,row,index);
        remove.type='button';remove.dataset.removeDependency=index;remove.textContent=labels.remove || 'Remove';row.append(remove);dependencies.append(row);
      });
      const add=doc.createElement('button');add.type='button';add.dataset.addDependency='true';add.textContent=labels.addDependency || 'Add dependency';dependencies.append(add);
    }else {
      endpointSelect('predecessor',labels.predecessor || 'Predecessor',values.predecessor,data,resolved.overlay);
      endpointSelect('successor',labels.successor || 'Successor',values.successor,data,resolved.overlay);
      typeSelect(values.type,labels);input('lagDays',labels.lag || 'Lag','number',values.lagDays);
    }
    fields.querySelector('input,select,textarea')?.focus();
  };
  const fieldChange=event=>{
    const name=event.target.dataset.field;if(!name)return;
    const value=['predecessor','successor'].includes(name)?JSON.parse(event.target.value):event.target.type==='number'?Number(event.target.value):event.target.value;
    if(event.target.dataset.dependencyIndex!==undefined) {
      const index=Number(event.target.dataset.dependencyIndex),{view}=store.read();
      update({dependencies:view.draft.values.fields.dependencies.map((dep,i)=>i===index?{...dep,[name]:value}:dep)});return;
    }
    update({[name]:value});
  };
  lifetime.listen(form,'input',fieldChange);lifetime.listen(form,'change',fieldChange);
  lifetime.listen(form,'submit',event=>{
    event.preventDefault();const {view}=store.read();if(!target || !view.draft)return;
    if(fields.querySelector('select:disabled')){store.setView({error:dataLabel('choicesPending','Choose a loaded predecessor before saving.')});return;}
    try{
      if(view.draft.values.create)actions.requestCreate(target,view.draft.values.fields);
      else actions.request(target.kind==='dependencies'?'dependency':'task',target,view.draft.values.fields);
    }
    catch(error){if(!(error instanceof ContractError))throw error;store.setView({error:store.read().data.labels.invalidEdit || 'Check the dates and values before saving.'});}
  });
  lifetime.listen(form,'click',event=>{
    if(event.target.closest('[data-cancel-editor]')){actions.close();return;}
    const remove=event.target.closest('[data-remove-dependency]');
    if(remove){const {view}=store.read();signature='';update({dependencies:view.draft.values.fields.dependencies.filter((_,i)=>i!==Number(remove.dataset.removeDependency))});}
    if(event.target.closest('[data-add-dependency]')) {
      const {data,view}=store.read(),resolved=resolveTarget(data,target),choices=(resolved.overlay?.tasks ?? data.tasks).filter(row=>target.kind!=='tasks' || row.id!==target.id);
      const project=(data.choiceProjects ?? data.projects).find(row=>row.id!==resolved.projectId);
      const predecessor=choices[0]?{kind:'task',id:choices[0].id}:project?{kind:'project',id:project.id}:null;
      if(predecessor){signature='';update({dependencies:[...view.draft.values.fields.dependencies,{id:'new-'+doc.defaultView.crypto.randomUUID(),type:'FS',lagDays:0,predecessor,successor:view.draft.values.create?{kind:'unavailable'}:{kind:'task',id:target.id}}]});}
    }
  });
  lifetime.listen(form,'keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();actions.close();}
    if(event.key==='Enter' && (event.ctrlKey || event.metaKey)){event.preventDefault();form.requestSubmit();}
    if(event.key==='Tab') {
      const controls=[...form.querySelectorAll('input,select,textarea,button')].filter(control=>!control.matches(':disabled'));
      if(event.shiftKey && doc.activeElement===controls[0]){event.preventDefault();controls.at(-1)?.focus();}
      if(!event.shiftKey && doc.activeElement===controls.at(-1)){event.preventDefault();controls[0]?.focus();}
    }
  });
  const dataLabel=(key,fallback)=>store.read().data.labels[key] || fallback;
  lifetime.own(store.subscribe(render));lifetime.own(()=>{clearChoices();form.remove();target=null;restore=null;});
  return {render};
}
