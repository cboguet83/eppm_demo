/** Frozen-column widths and accessible resize ownership, independent of host I/O. */

/** Bind one header's delegated column resize controls.
 * @param {object} panel Timeline slots. @param {object} lifetime Owned cleanup.
 */
export function bindColumnWidths(panel,lifetime) {
  const defaults={id:55,name:190,start:90,end:90},widths={...defaults};let drag=null;
  const change=(field,value)=>{
    widths[field]=Math.round(Math.max(field==='name'?80:40,Math.min(field==='name'?1200:300,value)));
    panel.root.style.setProperty('--planning-column-'+field+'-width',widths[field]+'px');
    panel.leftCanvas.style.minWidth=Object.values(widths).reduce((sum,width)=>sum+width,0)+'px';
  };
  const stop=()=>{
    if(drag?.node.hasPointerCapture(drag.id))drag.node.releasePointerCapture(drag.id);
    drag=null;
  };
  lifetime.listen(panel.leftHeader,'pointerdown',event=>{
    const node=event.target.closest('[data-resize-column]');if(!node || event.button!==0)return;
    event.preventDefault();event.stopPropagation();const field=node.dataset.resizeColumn;
    drag={node,id:event.pointerId,field,x:event.clientX,width:node.parentElement.getBoundingClientRect().width};node.setPointerCapture(event.pointerId);
  });
  lifetime.listen(panel.leftHeader,'pointermove',event=>{if(drag && event.pointerId===drag.id)change(drag.field,drag.width+event.clientX-drag.x);});
  lifetime.listen(panel.leftHeader,'pointerup',stop);lifetime.listen(panel.leftHeader,'pointercancel',stop);lifetime.listen(panel.leftHeader,'lostpointercapture',stop);
  lifetime.listen(panel.leftHeader,'click',event=>{if(event.target.closest('[data-resize-column]')){event.preventDefault();event.stopPropagation();}});
  lifetime.listen(panel.leftHeader,'keydown',event=>{
    const node=event.target.closest('[data-resize-column]');if(!node || !['ArrowLeft','ArrowRight','Home'].includes(event.key))return;
    event.preventDefault();event.stopPropagation();const field=node.dataset.resizeColumn;
    change(field,event.key==='Home'?defaults[field]:widths[field]+(event.key==='ArrowRight'?8:-8));
  });
  lifetime.own(stop);
}
