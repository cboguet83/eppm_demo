/** One scoped, keyboard-operated context menu with bounded declarative submenus. */

/** @param {HTMLElement} frame Owned root. @param {object} lifetime Lifetime. */
export function createContextMenu(frame,lifetime) {
  const doc=frame.ownerDocument,menu=doc.createElement('div');
  menu.className='planning-menu';menu.setAttribute('role','menu');menu.hidden=true;frame.append(menu);
  let stack=[],restore=null;
  const close=()=>{menu.hidden=true;stack=[];if(restore?.isConnected)restore.focus();};
  const render=()=>{
    const entries=stack.at(-1);menu.replaceChildren();
    for(const [index,entry] of entries.entries()) {
      const button=doc.createElement('button');button.type='button';button.setAttribute('role','menuitem');button.dataset.menuIndex=index;
      button.textContent=entry.label+(entry.children?.length?' ▸':'');button.disabled=entry.disabled===true;
      if(entry.children?.length)button.setAttribute('aria-haspopup','menu');menu.append(button);
    }
    const rect=menu.getBoundingClientRect(),win=doc.defaultView;
    menu.style.left=Math.max(4,Math.min(parseFloat(menu.style.left),win.innerWidth-rect.width-4))+'px';
    menu.style.top=Math.max(4,Math.min(parseFloat(menu.style.top),win.innerHeight-rect.height-4))+'px';
    menu.querySelector('button:not(:disabled)')?.focus();
  };
  const activate=index=>{
    const entry=stack.at(-1)?.[index];if(!entry || entry.disabled)return;
    if(entry.children?.length){stack.push(entry.children);render();return;}
    close();entry.run?.();
  };
  lifetime.listen(menu,'click',event=>{const button=event.target.closest('[data-menu-index]');if(button)activate(Number(button.dataset.menuIndex));});
  lifetime.listen(menu,'keydown',event=>{
    const buttons=[...menu.querySelectorAll('button:not(:disabled)')],index=buttons.indexOf(doc.activeElement);
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
      event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length;
      buttons[next]?.focus();return;
    }
    if(event.key==='ArrowRight'){event.preventDefault();if(stack.at(-1)?.[Number(doc.activeElement?.dataset.menuIndex)]?.children)activate(Number(doc.activeElement.dataset.menuIndex));}
    if(event.key==='ArrowLeft' && stack.length>1){event.preventDefault();stack.pop();render();}
    if(event.key==='Escape'){event.preventDefault();close();}
  });
  lifetime.listen(doc,'pointerdown',event=>{if(!menu.hidden && !menu.contains(event.target))close();});
  lifetime.own(()=>{menu.remove();stack=[];restore=null;});
  return {
    open(entries,x,y){close();if(!entries.length)return;restore=doc.activeElement;stack=[entries];menu.style.left=x+'px';menu.style.top=y+'px';menu.hidden=false;render();},
    close
  };
}
