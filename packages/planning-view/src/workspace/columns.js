/** Shared today/hover positions without coupling either pane's row renderer. */

/** @param {object[]} panels Timeline and optional resource slots. @param {object} lifetime Lifetime. @param {Function} calendar Current calendar. */
export function createColumnGuides(panels,lifetime,calendar) {
  const guides=panels.map(panel=>{
    const doc=panel.root.ownerDocument,hover=doc.createElement('div'),today=doc.createElement('div');
    hover.className='planning-column-hover';today.className='planning-today-line';hover.hidden=true;
    for(const guide of [hover,today])guide.setAttribute('aria-hidden','true');
    return {panel,hover,today};
  });
  const hide=()=>{for(const {hover} of guides)hover.hidden=true;};
  for(const {panel} of guides) {
    lifetime.listen(panel.root,'pointermove',event=>{
      const owner=event.target.closest('.planning-header,.planning-body');if(!owner)return;
      const x=event.clientX-owner.getBoundingClientRect().left+panel.body.scrollLeft;
      const cell=calendar()?.bottomCells.find(cell=>x>=cell.x && x<cell.x+cell.width);
      for(const {hover} of guides) {
        hover.hidden=!cell;if(cell){hover.style.left=cell.x+'px';hover.style.width=cell.width+'px';}
      }
    });
    lifetime.listen(panel.root,'pointerleave',hide);
  }
  lifetime.own(()=>{for(const {hover,today} of guides){hover.remove();today.remove();}});
  return {
    render(model,date) {
      for(const {panel,hover,today} of guides) {
        if(!panel.canvas.contains(hover))panel.canvas.append(hover,today);
        today.hidden=date<model.start || date>=model.end;
        if(!today.hidden)today.style.left=model.dateToX(date)+'px';
      }
    }
  };
}
