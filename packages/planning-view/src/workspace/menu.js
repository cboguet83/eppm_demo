/** Scoped sibling menu panels keep nested actions outside parent scroll boxes. */

/** @param {HTMLElement} frame Owned root. @param {object} lifetime Lifetime. */
export function createContextMenu(frame,lifetime) {
  const doc=frame.ownerDocument,win=doc.defaultView;
  let layers=[],restore=null,cancelHover=null,suppressFocus=false,sequence=0,position={x:10,y:10};
  const trim=depth=>{
    for(const layer of layers.splice(depth)){layer.parent?.setAttribute('aria-expanded','false');layer.parent?.removeAttribute('aria-controls');layer.panel.remove();}
  };
  const close=(focus=true)=>{
    cancelHover?.();cancelHover=null;trim(0);
    if(focus && restore?.isConnected)restore.focus();
  };
  const clamp=panel=>{
    const rect=panel.getBoundingClientRect();
    panel.style.left=Math.max(10,Math.min(parseFloat(panel.style.left),win.innerWidth-rect.width-10))+'px';
    panel.style.top=Math.max(10,Math.min(parseFloat(panel.style.top),win.innerHeight-rect.height-10))+'px';
  };
  const addLayer=(entries,x,y,parent=null,parentIndex=null)=>{
    const panel=doc.createElement('div');panel.className='planning-menu';panel.setAttribute('role','menu');
    panel.id='planning-menu-'+frame.dataset.instanceId+'-'+(++sequence);panel.dataset.menuDepth=layers.length;
    panel.style.left=x+'px';panel.style.top=y+'px';
    for(const [index,entry] of entries.entries()) {
      const button=doc.createElement('button');button.type='button';button.setAttribute('role','menuitem');button.dataset.menuIndex=index;
      if(entry.id)button.dataset.command=entry.id;
      if(entry.icon){const icon=doc.createElement('span');icon.textContent=entry.icon;icon.setAttribute('aria-hidden','true');button.append(icon,doc.createTextNode(' '));}
      button.append(doc.createTextNode(entry.label+(entry.children?.length?' ▸':'')));button.disabled=entry.disabled===true;
      if(entry.children?.length){button.setAttribute('aria-haspopup','menu');button.setAttribute('aria-expanded','false');}panel.append(button);
    }
    frame.append(panel);clamp(panel);const layer={panel,entries,parent,parentIndex};layers.push(layer);return layer;
  };
  const buttonAt=(layer,index)=>layer?.panel.querySelector('[data-menu-index="'+index+'"]');
  const focus=button=>{suppressFocus=true;button?.focus();suppressFocus=false;};
  const children=(depth,index,moveFocus=false)=>{
    const layer=layers[depth],entry=layer?.entries[index],parent=buttonAt(layer,index);
    if(!entry?.children?.length || entry.disabled)return;
    if(layers[depth+1]?.parent===parent){if(moveFocus)layers[depth+1].panel.querySelector('button:not(:disabled)')?.focus();return;}
    trim(depth+1);const bounds=parent.getBoundingClientRect(),menu=layer.panel.getBoundingClientRect();
    const child=addLayer(entry.children,menu.right,bounds.top,parent,index),width=child.panel.getBoundingClientRect().width;
    if(menu.right+width>win.innerWidth-10){child.panel.style.left=menu.left-width+'px';clamp(child.panel);}
    parent.setAttribute('aria-controls',child.panel.id);parent.setAttribute('aria-expanded','true');
    if(moveFocus)child.panel.querySelector('button:not(:disabled)')?.focus();
  };
  const activate=(depth,index)=>{
    const entry=layers[depth]?.entries[index];if(!entry || entry.disabled)return;
    if(entry.children?.length){children(depth,index);return;}
    const previous=layers.map(layer=>({entries:layer.entries,parentIndex:layer.parentIndex}));close();
    if(entry.run?.()!==false)return;
    addLayer(previous[0].entries,position.x,position.y);
    for(let level=1;level<previous.length;level++)children(level-1,previous[level].parentIndex);
    focus(buttonAt(layers[depth],index));
  };
  const target=event=>{
    const button=event.target.closest('[data-menu-index]'),panel=button?.closest('.planning-menu');
    if(!panel || !frame.contains(panel))return null;
    return {button,depth:Number(panel.dataset.menuDepth),index:Number(button.dataset.menuIndex)};
  };
  lifetime.listen(frame,'pointerover',event=>{
    const current=target(event);if(!current || current.button.contains(event.relatedTarget))return;
    cancelHover?.();cancelHover=null;
    const layer=layers[current.depth],entry=layer?.entries[current.index];
    if(!entry?.children?.length){trim(current.depth+1);return;}
    cancelHover=lifetime.timeout(()=>{cancelHover=null;if(layers[current.depth]===layer)children(current.depth,current.index);},150);
  });
  lifetime.listen(frame,'focusin',event=>{const current=target(event);if(current && !suppressFocus)children(current.depth,current.index);});
  lifetime.listen(frame,'pointerout',event=>{const current=target(event);if(current && !current.button.contains(event.relatedTarget)){cancelHover?.();cancelHover=null;}});
  lifetime.listen(frame,'click',event=>{const current=target(event);if(current)activate(current.depth,current.index);});
  lifetime.listen(frame,'keydown',event=>{
    const current=target(event);if(!current)return;
    const layer=layers[current.depth],buttons=[...layer.panel.querySelectorAll('button:not(:disabled)')],index=buttons.indexOf(current.button);
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
      event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length;
      trim(current.depth+1);buttons[next]?.focus();return;
    }
    if(event.key==='ArrowRight' || event.key==='Tab' && !event.shiftKey && layer.entries[current.index]?.children?.length) {
      event.preventDefault();children(current.depth,current.index,true);return;
    }
    if(event.key==='ArrowLeft' && current.depth>0){event.preventDefault();const parent=layer.parent;trim(current.depth);focus(parent);}
    if(event.key==='Escape'){event.preventDefault();close();}
  });
  lifetime.listen(doc,'pointerdown',event=>{if(layers.length && !layers.some(layer=>layer.panel.contains(event.target)))close();});
  lifetime.own(()=>{close(false);restore=null;});
  return {
    open(entries,x,y,invoker=doc.activeElement){close(false);if(!entries.length)return;position={x,y};restore=invoker;const root=addLayer(entries,x,y);root.panel.querySelector('button:not(:disabled)')?.focus();},
    close
  };
}
