/** Bounded SVG reconciliation and keyboard-accessible delivered-link inspection. */
import {createDependencyIndex,layoutDependencies,inspectDependency} from './dependencies.js';
import {ROW_HEIGHT} from './rows.js';

const NS='http://www.w3.org/2000/svg';

/** @param {object} panel Private timeline slots. @param {HTMLElement} frame Owned root. @param {object} lifetime Instance lifetime. @param {string} instanceId Unique scope. */
export function createDependencyRenderer({panel,frame,lifetime,instanceId,onEdit,canEditEntry}) {
  const doc=frame.ownerDocument,svg=doc.createElementNS(NS,'svg'),defs=doc.createElementNS(NS,'defs');
  const clip=doc.createElementNS(NS,'clipPath'),rect=doc.createElementNS(NS,'rect'),group=doc.createElementNS(NS,'g');
  const clipId='planning-clip-'+instanceId;
  clip.id=clipId;clip.append(rect);defs.append(clip);group.setAttribute('clip-path','url(#'+clipId+')');svg.append(defs,group);
  svg.classList.add('planning-dependencies');svg.dataset.part='dependencies';
  const inspector=doc.createElement('div');inspector.className='planning-inspector';inspector.dataset.part='dependency-inspector';
  inspector.setAttribute('role','dialog');inspector.setAttribute('aria-label','Dependency details');inspector.hidden=true;frame.append(inspector);
  let index=null,previousData=null,previousProjection=null,bundles=new Map(),nodes=new Map(),selected=null,labels={},signature='';
  const close=()=>{inspector.hidden=true;selected=null;};
  const show=(bundle,memberIndex=0)=>{
    selected={key:bundle.key,memberIndex};inspector.replaceChildren();inspector.hidden=false;
    const closeButton=doc.createElement('button');closeButton.type='button';closeButton.textContent=labels.close || 'Close';
    closeButton.dataset.closeInspector='true';inspector.append(closeButton);
    const select=doc.createElement('select');select.setAttribute('aria-label',labels.dependency || 'Dependency');
    bundle.members.forEach((entry,index)=>{
      const option=doc.createElement('option');option.value=String(index);option.textContent=entry.dependency.id;option.selected=index===memberIndex;select.append(option);
    });
    inspector.append(select);
    const details=inspectDependency(bundle.members[memberIndex]),list=doc.createElement('dl');
    const add=(label,value)=>{const term=doc.createElement('dt'),description=doc.createElement('dd');term.textContent=label;description.textContent=value;list.append(term,description);};
    add(labels.linkType || 'Link type',details.type);add(labels.lag || 'Lag',String(details.lagDays));
    for(const side of ['predecessor','successor']) {
      const endpoint=details[side];
      add(labels[side] || side,endpoint.kind==='unavailable'?(labels.unavailable || 'Unavailable'):endpoint.name ?? endpoint.id);
      if(endpoint.start)add(labels.dates || 'Dates',endpoint.start+' → '+endpoint.end);
    }
    add(labels.status || 'Status',details.evaluable?(details.violated?(labels.violated || 'Violated'):(labels.satisfied || 'Satisfied')):(labels.unavailable || 'Unavailable'));
    for(const diagnostic of details.diagnostics)add(labels.diagnostic || 'Diagnostic',typeof diagnostic==='string'?diagnostic:diagnostic.message ?? '');
    inspector.append(list);select.focus();
    if(onEdit) {
      const edit=doc.createElement('button');edit.type='button';edit.textContent=labels.edit || 'Edit';edit.dataset.editDependency='true';
      edit.disabled=!canEditEntry(bundle.members[memberIndex]);inspector.append(edit);
    }
  };
  const open=event=>{
    const target=event.target.closest('[data-bundle-key]');
    if(!target || !svg.contains(target))return;
    event.preventDefault();const bundle=bundles.get(target.dataset.bundleKey);if(bundle)show(bundle);
  };
  lifetime.listen(svg,'click',open);lifetime.listen(svg,'contextmenu',open);
  lifetime.listen(svg,'keydown',event=>{if(['Enter',' '].includes(event.key))open(event);});
  lifetime.listen(inspector,'click',event=>{
    if(event.target.closest('[data-close-inspector]'))close();
    if(event.target.closest('[data-edit-dependency]') && selected) {
      const entry=bundles.get(selected.key)?.members[selected.memberIndex];if(entry && onEdit(entry))close();
    }
  });
  lifetime.listen(inspector,'change',event=>{if(selected && event.target.tagName==='SELECT')show(bundles.get(selected.key),Number(event.target.value));});
  lifetime.listen(frame,'keydown',event=>{if(event.key==='Escape')close();});
  lifetime.own(()=>{svg.remove();inspector.remove();bundles.clear();nodes.clear();index=null;previousData=null;previousProjection=null;labels={};selected=null;});
  return {
    render(data,view,calendar,projection,window) {
      labels=data.labels;inspector.setAttribute('aria-label',labels.dependencyDetails || 'Dependency details');
      const changed=previousData!==data || previousProjection!==projection;
      if(changed) {
        index=createDependencyIndex(data,projection);previousData=data;previousProjection=projection;
        if(selected)close();
      }
      const nextSignature=JSON.stringify([window.start,window.end,calendar.width,calendar.start,calendar.end,view.mode,view.filters]);
      if(!changed && signature===nextSignature && panel.canvas.contains(svg))return;
      signature=nextSignature;
      const laidOut=layoutDependencies(index.query(window.start,window.end),calendar,window,view.filters);
      bundles=new Map(laidOut.map(bundle=>[bundle.key,bundle]));
      for(const [key,node] of nodes)if(!bundles.has(key)){node.remove();nodes.delete(key);}
      const top=window.start*ROW_HEIGHT,height=Math.max(ROW_HEIGHT,(window.end-window.start+1)*ROW_HEIGHT);
      svg.style.top=top+'px';svg.setAttribute('width',calendar.width);svg.setAttribute('height',height);
      svg.setAttribute('viewBox',`0 ${top} ${calendar.width} ${height}`);
      rect.setAttribute('x',0);rect.setAttribute('y',top);rect.setAttribute('width',calendar.width);rect.setAttribute('height',height);
      for(const bundle of laidOut) {
        let owner=nodes.get(bundle.key);
        if(!owner) {
          const path=doc.createElementNS(NS,'path'),arrow=doc.createElementNS(NS,'path');owner=doc.createElementNS(NS,'g');
          path.setAttribute('d',bundle.path);arrow.setAttribute('d',`M ${bundle.x+bundle.direction*5} ${bundle.y-3} L ${bundle.x} ${bundle.y} L ${bundle.x+bundle.direction*5} ${bundle.y+3}`);
          owner.append(path,arrow);group.append(owner);nodes.set(bundle.key,owner);
        }
        owner.dataset.bundleKey=bundle.key;owner.dataset.memberCount=bundle.members.length;owner.dataset.lane=bundle.lane;
        owner.setAttribute('tabindex','0');owner.setAttribute('role','button');
        owner.setAttribute('aria-label',(labels.dependency || 'Dependency')+' '+bundle.members.map(entry=>entry.dependency.id).join(', '));
        owner.classList.add('planning-link');if(bundle.violated)owner.classList.add('planning-link-violated');
      }
      if(!panel.canvas.contains(svg))panel.canvas.append(svg);
      if(selected && !bundles.has(selected.key))close();
    }
  };
}
