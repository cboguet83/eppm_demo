/** Local visibility and expansion controls shared by every host. */

/** Compose retained view controls without adding host persistence commands.
 * @param {object} options Toolbar, store and owner lifetime.
 * @returns {Function} Render controls from current labels/view.
 */
export function createViewControls({toolbar,store,lifetime}) {
  const doc=toolbar.ownerDocument,controls=new Map();
  for(const [key,fallback] of [['internalLinks','Internal dependencies'],['externalLinks','External dependencies'],['descriptions','Description']]) {
    const label=doc.createElement('label'),input=doc.createElement('input'),text=doc.createTextNode(fallback);
    input.type='checkbox';input.dataset.control=key;label.append(input,text);toolbar.append(label);controls.set(key,{input,text,fallback});
    lifetime.listen(input,'change',()=>{const {view}=store.read();store.setView({filters:{...view.filters,[key]:input.checked}});});
  }
  const expand=doc.createElement('button'),collapse=doc.createElement('button'),count=doc.createElement('span');
  expand.type='button';collapse.type='button';expand.dataset.control='expandAll';collapse.dataset.control='collapseAll';count.dataset.part='project-count';toolbar.append(expand,collapse,count);
  lifetime.listen(expand,'click',()=>store.setView({expandedProjects:store.read().data.projects.map(row=>row.id),collapsedResources:[]}));
  lifetime.listen(collapse,'click',()=>{
    const {data}=store.read(),collapsed=[],pending=data.hierarchy.flatMap(node=>node.children ?? []);
    while(pending.length){const node=pending.pop();if(node.children?.length)collapsed.push(node.id);for(const child of node.children ?? [])pending.push(child);}
    store.setView({expandedProjects:[],collapsedResources:collapsed,scrollTop:0});
  });
  const setText=(node,value)=>{if(node.textContent!==value)node.textContent=value;};
  return ()=>{
    const {data,view}=store.read();
    for(const [key,{input,text,fallback}] of controls){input.checked=view.filters[key]!==false;setText(text,data.labels[key] || fallback);}
    setText(expand,data.labels.expandAll || 'Expand all');setText(collapse,data.labels.collapseAll || 'Collapse all');
    expand.hidden=collapse.hidden=data.projects.length===0;setText(count,data.projects.length+' '+(data.projects.length===1?(data.labels.project || 'Project'):(data.labels.projects || 'Projects')));
  };
}
