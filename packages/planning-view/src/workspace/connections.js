/** Instance-owned endpoint gestures; authoritative creation stays with the host. */
const targetOf=node=>({kind:node.dataset.targetKind,id:node.dataset.targetId,...(node.dataset.overlayId?{overlayId:node.dataset.overlayId}:{})});
const identity=target=>JSON.stringify(target);

/** Bind direct linking independently from date editing.
 * @param {object} options Workspace, lifetime, store, action controller and hooks.
 * @returns {object} Render and active-state interface.
 */
export function createConnections({frame,store,actions,lifetime,onStart,onInspect}) {
  const doc=frame.ownerDocument,ns='http://www.w3.org/2000/svg';
  const svg=doc.createElementNS(ns,'svg'),path=doc.createElementNS(ns,'path');
  const defs=doc.createElementNS(ns,'defs'),marker=doc.createElementNS(ns,'marker'),arrow=doc.createElementNS(ns,'path');
  marker.id='planning-connection-'+doc.defaultView.crypto.randomUUID();
  for(const [key,value] of Object.entries({viewBox:'0 0 10 10',refX:'9',refY:'5',markerWidth:'6',markerHeight:'6',orient:'auto-start-reverse'}))marker.setAttribute(key,value);
  arrow.setAttribute('d','M0,0 L10,5 L0,10 Z');arrow.style.fill='#2563eb';marker.append(arrow);defs.append(marker);svg.append(defs);
  path.setAttribute('marker-end',`url(#${marker.id})`);
  svg.classList.add('planning-connection-preview');svg.append(path);frame.append(svg);
  const status=doc.createElement('span');status.className='planning-connection-status';status.setAttribute('role','status');frame.append(status);
  let state=null,down=null,consume=false,lastPoint=null,wasPending=false;
  const controls=()=>[...frame.querySelectorAll('[data-connect]')];
  const bar=node=>node.closest('.planning-bar');
  const target=node=>targetOf(bar(node));
  const labels=()=>store.read().data.labels;
  const enabled=()=>{const {data,view}=store.read();return data.capabilities.createDependencies===true && data.capabilities.edit && view.filters.editEnabled && !view.pendingRequestId;};
  const cancel=()=>{
    const pointer=down?.id;state=null;down=null;lastPoint=null;svg.style.display='none';
    if(pointer!==undefined && frame.hasPointerCapture(pointer))frame.releasePointerCapture(pointer);
    frame.classList.remove('planning-connecting');for(const n of controls())n.removeAttribute('data-connect-eligible');
    status.textContent=labels().dependencyCancelled || 'Connection cancelled.';
  };
  const findSource=()=>controls().find(n=>identity(target(n))===identity(state.source) && n.dataset.connect===state.edge);
  const point=node=>{const r=node.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};};
  const draw=()=>{
    if(!state)return;
    const source=findSource();if(!source){cancel();return;}
    const a=point(source),b=lastPoint ?? a,origin=frame.getBoundingClientRect();
    svg.style.display='block';svg.setAttribute('width',String(frame.clientWidth));svg.setAttribute('height',String(frame.clientHeight));
    path.setAttribute('d',`M${a.x-origin.x},${a.y-origin.y} L${b.x-origin.x},${b.y-origin.y}`);
  };
  const arm=node=>{
    if(!enabled())return;
    onStart();const {data}=store.read();
    state={source:target(node),edge:node.dataset.connect,scope:data.scope,revision:data.revision,
      overlayRevision:actions.resolve(target(node))?.overlay?.revision};
    frame.classList.add('planning-connecting');status.textContent=labels().chooseDependencyTarget || 'Choose a destination connector. Escape cancels.';render();
  };
  const finish=node=>{
    if(!state)return;
    if(!node || !actions.canCreateDependency(state.source,target(node))){cancel();return;}
    const source=state.source,destination=target(node),type=state.edge+node.dataset.connect;
    const resolved=actions.resolve(destination),{data}=store.read();
    const existing=(resolved.overlay?.dependencies ?? data.dependencies).find(dep=>dep.type===type && (dep.lagDays ?? 0)===0 &&
      dep.predecessor.id===source.id && dep.predecessor.kind===(source.kind==='tasks'?'task':'project') &&
      dep.successor.id===destination.id && dep.successor.kind===(destination.kind==='tasks'?'task':'project'));
    const a=point(findSource()),b=point(node);cancel();
    if(existing){onInspect({kind:'dependencies',id:existing.id,...(destination.overlayId?{overlayId:destination.overlayId}:{})});return;}
    if(actions.requestDependency(source,destination,type)) {
      svg.style.display='block';const r=frame.getBoundingClientRect();path.setAttribute('d',`M${a.x-r.x},${a.y-r.y} L${b.x-r.x},${b.y-r.y}`);
      status.textContent=labels().savingDependency || 'Saving dependency…';
    }
  };
  const hit=event=>doc.elementFromPoint(event.clientX,event.clientY)?.closest('[data-connect]');
  lifetime.listen(frame,'pointerdown',event=>{
    const node=event.target.closest('[data-connect]');if(!node || event.button!==0)return;
    event.preventDefault();event.stopImmediatePropagation();consume=true;
    if(state){finish(node);return;}
    arm(node);if(state){down={id:event.pointerId,x:event.clientX,y:event.clientY,moved:false};frame.setPointerCapture(event.pointerId);}
  },{capture:true});
  lifetime.listen(frame,'pointermove',event=>{
    if(!state)return;
    lastPoint={x:event.clientX,y:event.clientY};
    if(down && down.id===event.pointerId)down.moved ||= Math.hypot(event.clientX-down.x,event.clientY-down.y)>=3;
    draw();
  });
  lifetime.listen(frame,'pointerup',event=>{
    if(!down || down.id!==event.pointerId)return;
    event.preventDefault();event.stopImmediatePropagation();const moved=down.moved;down=null;
    if(frame.hasPointerCapture(event.pointerId))frame.releasePointerCapture(event.pointerId);
    if(moved){const node=hit(event);finish(node && frame.contains(node)?node:null);}
  },{capture:true});
  lifetime.listen(frame,'click',event=>{
    if(event.target.closest('[data-connect]') || consume){consume=false;event.preventDefault();event.stopImmediatePropagation();return;}
    if(event.target.closest('.planning-toolbar'))return;
    if(state){cancel();event.preventDefault();event.stopImmediatePropagation();}
  },{capture:true});
  lifetime.listen(frame,'pointercancel',cancel);
  lifetime.listen(frame,'lostpointercapture',()=>{if(down)cancel();});
  lifetime.listen(frame,'keydown',event=>{
    if(event.key==='Escape' && state){cancel();event.preventDefault();event.stopImmediatePropagation();return;}
    const node=event.target.closest('[data-connect]');
    if(node && ['Enter',' '].includes(event.key)){event.preventDefault();event.stopImmediatePropagation();if(state)finish(node);else arm(node);}
  },{capture:true});
  const render=()=>{
    const {data,view}=store.read();
    if(state && (!enabled() || state.scope!==data.scope || state.revision!==data.revision ||
      state.overlayRevision!==actions.resolve(state.source)?.overlay?.revision))cancel();
    for(const node of controls()) {
      const owner=bar(node),resolved=actions.resolve(target(node));
      const visible=enabled() && resolved && resolved.lane!=='baseline';
      node.hidden=!visible;node.tabIndex=visible?0:-1;
      node.setAttribute('aria-label',(labels()[node.dataset.connect==='S'?'connectStart':'connectFinish'] || (node.dataset.connect==='S'?'Link start':'Link finish'))+' · '+(resolved?.record.name ?? ''));
      node.dataset.connectEligible=String(!!state && actions.canCreateDependency(state.source,target(node)));
      owner.classList.toggle('planning-connectable',!!visible);
    }
    if(state)draw();else if(!view.pendingRequestId){
      svg.style.display='none';
      if(wasPending)status.textContent=view.error ?? (labels().dependencyCreated || 'Dependency created.');
    }
    wasPending=!!view.pendingRequestId && !!view.preview?.dependency;
  };
  lifetime.own(store.subscribe(reason=>{if(reason!=='destroy')render();}));
  lifetime.own(()=>{cancel();svg.remove();status.remove();});
  return {render,get active(){return !!state;}};
}
