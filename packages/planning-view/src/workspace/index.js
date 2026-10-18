/** Scoped planning workspace shell; renderers compose through private DOM slots. */
import {ContractError} from '../contracts/index.js';
import {createCalendar,timelineBounds} from '../calendar/index.js';
import {createPlanningStore} from '../state/store.js';
import {createLoadingController} from '../state/loader.js';
import {createLifetime} from './lifetime.js';
import {createTimelineRenderer} from '../timeline/render.js';
import {createDependencyRenderer} from '../timeline/dependency-render.js';
import {createInteractions} from './interactions.js';
import {validateActions,canEdit} from './actions.js';
import {createResourceRenderer} from '../resources/render.js';
import {createColumnGuides} from './columns.js';

/** @param {Document} doc Document. @param {string} tag HTML tag. @param {string} name Part. @param {string} className Scoped style. */
function element(doc,tag,name,className) {
  const node=doc.createElement(tag);node.dataset.part=name;node.className=className;return node;
}

/** @param {Document} doc Document. @param {string} prefix Timeline or resource. */
function panel(doc,prefix) {
  const root=element(doc,'div',prefix+'-panel','planning-panel'+(prefix==='resource'?' planning-resource-panel':''));
  const leftHeader=element(doc,'div',prefix+'-left-header','planning-left-header');
  const header=element(doc,'div',prefix+'-header','planning-header');
  const headerInner=element(doc,'div',prefix+'-header-inner','');
  const left=element(doc,'div',prefix+'-left','planning-left-body');
  const leftCanvas=element(doc,'div',prefix+'-left-canvas','planning-canvas');
  const body=element(doc,'div',prefix+'-body','planning-body');
  const canvas=element(doc,'div',prefix+'-canvas','planning-canvas');
  header.append(headerInner);left.append(leftCanvas);body.append(canvas);
  root.append(leftHeader,header,left,body);
  return {root,leftHeader,header,headerInner,left,leftCanvas,body,canvas};
}

/** @param {object} data Valid snapshot. @param {string} mode View mode. @param {string} today Date. @param {number} width Viewport. */
function calendarFor(data,mode,today,width) {
  const ranges=[...data.tasks,...data.projects.filter(project=>project.start && project.end),
    ...data.overlays.flatMap(overlay=>overlay.tasks)];
  return createCalendar({...timelineBounds(ranges,mode,today),mode,today,viewportWidth:width});
}

/** @param {HTMLElement} container Header owner. @param {object} calendar Shared model. */
function renderHeader(container,calendar) {
  const doc=container.ownerDocument;
  container.replaceChildren();container.style.width=calendar.width+'px';
  for(const cells of [calendar.topCells,calendar.bottomCells]) {
    const tier=element(doc,'div','header-tier','planning-header-tier');
    for(const cell of cells) {
      const node=element(doc,'div','header-cell','planning-header-cell'+(cell.isCurrent?' planning-current':''));
      node.style.width=cell.width+'px';node.textContent=cell.label;
      if(cell.start){node.dataset.start=cell.start;node.dataset.end=cell.end;}
      tier.append(node);
    }
    container.append(tier);
  }
}

/** @param {object} panels Both panels. @param {object} store Instance store. @param {object} lifetime Lifetime. @param {Function} schedule Render invalidation. */
function bindScrolling(panels,store,lifetime,schedule) {
  const {timeline,resource}=panels;
  const horizontal=source=>{
    for(const target of [timeline.body,timeline.header,resource.body,resource.header]) {
      if(target.scrollLeft!==source.scrollLeft) target.scrollLeft=source.scrollLeft;
    }
  };
  lifetime.listen(timeline.body,'scroll',()=>{
    timeline.left.scrollTop=timeline.body.scrollTop;horizontal(timeline.body);
    const {view}=store.read();
    if(view.scrollTop!==timeline.body.scrollTop || view.scrollLeft!==timeline.body.scrollLeft) {
      store.setView({scrollTop:timeline.body.scrollTop,scrollLeft:timeline.body.scrollLeft});
    }
    schedule();
  },{passive:true});
  lifetime.listen(resource.body,'scroll',()=>{
    resource.left.scrollTop=resource.body.scrollTop;horizontal(resource.body);
    const {view}=store.read();
    if(view.scrollLeft!==resource.body.scrollLeft || view.resourceScrollTop!==resource.body.scrollTop)store.setView({scrollLeft:resource.body.scrollLeft,resourceScrollTop:resource.body.scrollTop});
    schedule();
  },{passive:true});
  for(const item of [timeline,resource]) {
    lifetime.listen(item.left,'wheel',event=>{
      if(!event.deltaY)return;
      item.body.scrollTop+=event.deltaY;
      if(Math.abs(event.deltaY)>=Math.abs(event.deltaX))event.preventDefault();
    },{passive:false});
    lifetime.listen(item.left,'scroll',()=>{item.leftHeader.scrollLeft=item.left.scrollLeft;},{passive:true});
  }
}

/** @param {HTMLElement} frame Root. @param {HTMLElement} splitter Handle. @param {object} lifetime Lifetime. @param {Function} change Set logical width. @param {Function} width Read actual width. */
function bindSplitter(frame,splitter,lifetime,change,width) {
  let drag=null;
  const stop=()=>{
    if(drag && splitter.hasPointerCapture(drag.id))splitter.releasePointerCapture(drag.id);
    drag=null;frame.classList.remove('planning-resizing');
  };
  lifetime.listen(splitter,'pointerdown',event=>{
    if(event.button!==0)return;
    event.preventDefault();drag={id:event.pointerId,x:event.clientX,width:width()};
    splitter.setPointerCapture(event.pointerId);frame.classList.add('planning-resizing');
  });
  lifetime.listen(splitter,'pointermove',event=>{
    if(drag && drag.id===event.pointerId)change(drag.width+event.clientX-drag.x);
  });
  lifetime.listen(splitter,'pointerup',stop);lifetime.listen(splitter,'pointercancel',stop);
  lifetime.listen(splitter,'keydown',event=>{
    if(!['ArrowLeft','ArrowRight'].includes(event.key))return;
    event.preventDefault();change(width()+(event.key==='ArrowLeft'?-10:10));
  });
  lifetime.own(stop);
}

/** Mount an independently owned workspace in a supplied host element.
 * @param {HTMLElement} root Host element; existing host children are retained.
 * @param {object} options Initial snapshot, today, loader, resources and callbacks.
 * @returns {{update:Function,destroy:Function}} Small public lifecycle interface.
 */
export function mountPlanningView(root,options) {
  if(!root || root.nodeType!==1 || !root.ownerDocument?.defaultView)throw new ContractError('root');
  if(!options || typeof options!=='object')throw new ContractError('options');
  for(const name of ['onHeight','onEvent','load','onLoadError']) {
    if(options[name]!==undefined && typeof options[name]!=='function')throw new ContractError('options.'+name);
  }
  for(const name of ['showResources','grouped','editEnabled'])if(options[name]!==undefined && typeof options[name]!=='boolean')throw new ContractError('options.'+name);
  if(options.tooltipDelay!==undefined && (!Number.isFinite(options.tooltipDelay) || options.tooltipDelay<0 || options.tooltipDelay>60000))throw new ContractError('options.tooltipDelay');
  if(options.resourceUnit!==undefined && typeof options.resourceUnit!=='string')throw new ContractError('options.resourceUnit');
  if(options.resourceMaxHeight!==undefined && (!Number.isFinite(options.resourceMaxHeight) || options.resourceMaxHeight<50 || options.resourceMaxHeight>2000))throw new ContractError('options.resourceMaxHeight');
  if(options.resourceOptions!==undefined && (!options.resourceOptions || typeof options.resourceOptions!=='object' || Array.isArray(options.resourceOptions) || Object.entries(options.resourceOptions).some(([key,value])=>!['hideUnused','onlyOverallocated','showTotal','showSelected','collapsed'].includes(key) || typeof value!=='boolean')))throw new ContractError('options.resourceOptions');
  options={...options,contextActions:validateActions(options.contextActions)};
  const doc=root.ownerDocument,win=doc.defaultView;
  const now=new Date();
  const today=options.today ?? [now.getFullYear(),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');
  const store=createPlanningStore(options.snapshot);
  if(options.mode)store.setView({mode:options.mode});
  if(options.editEnabled || options.resourceOptions)store.setView({filters:{editEnabled:!!options.editEnabled,resources:options.resourceOptions ?? {}}});
  // Fail invalid geometry before allocating DOM/listeners or notifying a host.
  calendarFor(store.read().data,store.read().view.mode,today,0);
  const lifetime=createLifetime(win),instanceId=win.crypto.randomUUID();
  const frame=element(doc,'div','workspace','planning-view');
  frame.dataset.instanceId=instanceId;frame.setAttribute('role','group');frame.setAttribute('aria-label','Planning');
  const sheet=doc.createElement('link');sheet.rel='stylesheet';sheet.href=new URL('./styles.css',import.meta.url).href;
  const toolbar=element(doc,'div','toolbar','planning-toolbar');
  for(const mode of ['Day','Week','Month','Quarter','Year']) {
    const button=doc.createElement('button');button.type='button';button.dataset.mode=mode;button.textContent=mode;toolbar.append(button);
  }
  const timeline=panel(doc,'timeline'),resource=panel(doc,'resource');
  const splitter=element(doc,'div','splitter','planning-splitter');
  splitter.tabIndex=0;splitter.setAttribute('role','separator');splitter.setAttribute('aria-orientation','vertical');
  splitter.setAttribute('aria-label','Resize planning columns');timeline.root.append(splitter);
  resource.root.append(element(doc,'div','resource-spacer','planning-resource-spacer'));
  const resourceHeading=element(doc,'div','resource-heading','planning-resource-heading');
  frame.append(sheet,toolbar,timeline.root,resourceHeading,resource.root);root.append(frame);
  lifetime.own(()=>frame.remove());lifetime.own(()=>store.destroy());
  let leftWidth=425,cancelRender=null,loader=null,geometry=null,geometryKey=null,lastHeight=null;
  lifetime.own(()=>{geometry=null;geometryKey=null;});
  const timelineRenderer=createTimelineRenderer({panel:timeline,store,lifetime,options});
  const interactions=createInteractions({frame,toolbar,store,lifetime,options,calendar:()=>geometry});
  const resources=createResourceRenderer({panel:resource,heading:resourceHeading,store,lifetime,options,cancelSelection:interactions.cancelSelection});
  const columns=createColumnGuides([timeline,resource],lifetime,()=>geometry);
  const dependencies=createDependencyRenderer({panel:timeline,frame,lifetime,instanceId,
    onEdit:entry=>interactions.openDependency(entry),
    canEditEntry:entry=>{const {data,view}=store.read();return canEdit(data,view,{kind:'dependencies',id:entry.dependency.id,...(entry.overlay?{overlayId:entry.overlay.id}:{})},'dependency');}});
  const draw=()=>{
    cancelRender=null;
    const {data,view}=store.read();
    const left=Math.max(120,Math.min(leftWidth,frame.clientWidth-200));
    frame.style.setProperty('--planning-left-width',left+'px');
    const key=[data.tasks,data.projects,data.overlays,view.mode,timeline.body.clientWidth];
    if(!geometryKey || key.some((value,index)=>value!==geometryKey[index])) {
      geometry=calendarFor(data,view.mode,today,timeline.body.clientWidth);geometryKey=key;
      renderHeader(timeline.headerInner,geometry);renderHeader(resource.headerInner,geometry);
    }
    const calendar=geometry;
    for(const item of [timeline,resource])item.canvas.style.width=calendar.width+'px';
    for(const button of toolbar.querySelectorAll('[data-mode]')) {
      button.textContent=data.labels[button.dataset.mode.toLowerCase()] || button.dataset.mode;
      button.setAttribute('aria-pressed',String(view.mode===button.dataset.mode));
    }
    const rendered=timelineRenderer.render(data,view,calendar,loader);
    dependencies.render(data,view,calendar,rendered.projection,rendered.window);
    resources.render(data,view,calendar);
    columns.render(calendar,today);
    interactions.render();
    timeline.body.scrollTop=view.scrollTop;timeline.body.scrollLeft=view.scrollLeft;
    const height=Math.ceil(frame.getBoundingClientRect().height);
    if(height!==lastHeight && typeof options.onHeight==='function'){lastHeight=height;options.onHeight(height);}
  };
  const schedule=()=>{if(!lifetime.disposed && !cancelRender)cancelRender=lifetime.frame(draw);};
  lifetime.own(store.subscribe(()=>schedule()));
  lifetime.listen(toolbar,'click',event=>{
    const button=event.target.closest('button[data-mode]');
    if(button && toolbar.contains(button))store.setView({mode:button.dataset.mode});
  });
  bindScrolling({timeline,resource},store,lifetime,schedule);
  bindSplitter(frame,splitter,lifetime,value=>{leftWidth=value;schedule();},()=>timeline.left.getBoundingClientRect().width);
  const observer=new win.ResizeObserver(schedule);observer.observe(timeline.body);observer.observe(frame);
  lifetime.own(()=>observer.disconnect());lifetime.listen(win,'resize',schedule);lifetime.listen(sheet,'load',schedule);
  if(options.load) {
    loader=createLoadingController({store,load:options.load,onError:options.onLoadError});
    lifetime.own(()=>loader.destroy());
  }
  try {draw();} catch(error) {lifetime.destroy();throw error;}
  return {
    update(message){if(lifetime.disposed)return false;return store.update(message);},
    destroy(){lifetime.destroy();}
  };
}
