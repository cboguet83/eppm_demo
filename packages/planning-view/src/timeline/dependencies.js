/** Indexed dependency layout; diagnostics expose delivered metadata only. */
import {ROW_HEIGHT,summarizeDates} from './rows.js';

/** @param {object} data Complete snapshot. @param {object} projection Timeline rows/indexes. */
function endpointResolver(data,projection) {
  const current=new Map(data.tasks.map(task=>[task.id,task]));
  const projects=new Map(data.projects.map(project=>[project.id,project]));
  const comparisons=new Map(data.overlays.map(overlay=>[overlay.id,new Map(overlay.tasks.map(task=>[task.id,task]))]));
  return (endpoint,overlay)=>{
    if(endpoint.kind==='unavailable')return null;
    const task=endpoint.kind==='task'?(comparisons.get(overlay?.id)?.get(endpoint.id) ?? current.get(endpoint.id)):null;
    const projectId=task?.projectId ?? (endpoint.kind==='project'?endpoint.id:endpoint.projectId);
    const projectIndex=projection.projectIndexes.get(projectId),projectRow=projection.rows[projectIndex];
    let rowIndex=endpoint.kind==='project'?projectIndex:projection.comparisonIndexes.get(JSON.stringify([overlay?.id,endpoint.id]));
    if(rowIndex===undefined && (!overlay || !comparisons.get(overlay.id)?.has(endpoint.id)))rowIndex=projection.taskIndexes.get(endpoint.id);
    const collapsed=projectRow && !projectRow.expanded;
    if(rowIndex===undefined && collapsed)rowIndex=projectIndex;
    if(rowIndex===undefined)return null;
    const row=projection.rows[rowIndex];
    const summary=row.comparisons.find(item=>item.overlay.id===overlay?.id)?.task;
    const dates=row.kind==='project'?(summary ?? row.summary):task;
    if(!dates?.start || !dates?.end)return null;
    const record=endpoint.kind==='task'?task:projects.get(projectId);
    return {rowIndex,projectId,record,dates,kind:endpoint.kind,isProject:row.kind==='project',collapsed,
      lane:overlay && (summary || comparisons.get(overlay.id)?.has(endpoint.id))?overlay.kind:'current',comparing:row.comparisons.some(item=>item.overlay.kind==='alternative')};
  };
}

/** Create an interval index so window queries include crossing links without scans.
 * @param {object} data Complete snapshot. @param {object} projection Projected rows.
 * @returns {object} Candidate query and endpoint inspection seam.
 */
export function createDependencyIndex(data,projection) {
  const resolve=endpointResolver(data,projection),buckets=new Map();
  let base=1;while(base<projection.rows.length)base*=2;
  const add=(index,entry)=>{if(!buckets.has(index))buckets.set(index,[]);buckets.get(index).push(entry);};
  const entries=[];
  const append=(dependency,overlay=null)=>{
    const predecessor=resolve(dependency.predecessor,overlay),successor=resolve(dependency.successor,overlay);
    if(!predecessor && !successor)return;
    if(predecessor && successor && predecessor.rowIndex===successor.rowIndex && predecessor.collapsed && successor.collapsed)return;
    const entry={key:JSON.stringify([overlay?.id ?? '',dependency.id]),dependency,overlay,predecessor,successor};
    entries.push(entry);
    let left=Math.min(predecessor?.rowIndex ?? successor.rowIndex,successor?.rowIndex ?? predecessor.rowIndex)+base;
    let right=Math.max(predecessor?.rowIndex ?? successor.rowIndex,successor?.rowIndex ?? predecessor.rowIndex)+base;
    while(left<=right) {
      if(left%2)add(left++,entry);if(!(right%2))add(right--,entry);
      left=Math.floor(left/2);right=Math.floor(right/2);
    }
  };
  for(const dependency of data.dependencies)append(dependency);
  for(const overlay of data.overlays)for(const dependency of overlay.dependencies ?? [])append(dependency,overlay);
  return {
    query(start,end) {
      const found=new Set();
      for(let row=Math.max(0,start);row<=Math.min(end,projection.rows.length-1);row++) {
        for(let index=row+base;index>=1;index=Math.floor(index/2))for(const entry of buckets.get(index) ?? [])found.add(entry);
      }
      return [...found];
    },
    get size(){return entries.length;}
  };
}

/** @param {object} endpoint Resolved delivered endpoint. @param {object} calendar Calendar. @param {string} side S/F edge. */
function anchor(endpoint,calendar,side) {
  const dates=endpoint.dates,milestone=!endpoint.isProject && dates.start===dates.end;
  const start=calendar.dateToX(dates.start);
  const end=Math.max(start+(endpoint.isProject?16:24),calendar.endDateToX(dates.end));
  const y=endpoint.rowIndex*ROW_HEIGHT+(endpoint.lane==='alternative'?30:endpoint.lane==='baseline'?37:endpoint.comparing?12:20.7);
  return {x:milestone?start+(side==='S'?-9:9):side==='S'?start:end,y};
}

/** Convert a window's indexed candidates into bundled, vertically clipped paths.
 * @param {object[]} entries Candidate records. @param {object} calendar Shared scale.
 * @param {object} window Inclusive row window. @param {object} filters Link visibility.
 * @returns {object[]} Bundles retaining every member for inspection.
 */
export function layoutDependencies(entries,calendar,window,filters={}) {
  const bundles=new Map(),top=window.start*ROW_HEIGHT,bottom=(window.end+1)*ROW_HEIGHT;
  for(const entry of entries) {
    const {predecessor,successor,dependency,overlay}=entry;
    const external=dependency.external===true || !predecessor || !successor || predecessor.projectId!==successor.projectId;
    if((external && filters.externalLinks===false) || (!external && filters.internalLinks===false))continue;
    let pred=predecessor?anchor(predecessor,calendar,dependency.type[0]):null;
    let succ=successor?anchor(successor,calendar,dependency.type[1]):null;
    if(!pred)pred={x:succ.x-24,y:succ.y};
    if(!succ)succ={x:pred.x+24,y:pred.y};
    const py=Math.max(top,Math.min(bottom,pred.y)),sy=Math.max(top,Math.min(bottom,succ.y));
    const bend=dependency.type[0]==='F'?pred.x+10:pred.x-10;
    const path=`M ${pred.x} ${py} H ${bend} V ${sy} H ${succ.x}`;
    const key=JSON.stringify([path,dependency.type,!!dependency.violated,external,overlay?.id ?? '']);
    if(!bundles.has(key))bundles.set(key,{key,path,x:succ.x,y:sy,direction:succ.x>=bend?-1:1,violated:!!dependency.violated,
      external,lane:overlay?.kind ?? 'current',members:[],top,bottom});
    bundles.get(key).members.push(entry);
  }
  return [...bundles.values()];
}

/** Return safe delivered endpoint details; never infer hidden identity or dates.
 * @param {object} entry Dependency index entry. @returns {object} Inspection data.
 */
export function inspectDependency(entry) {
  const details=(supplied,resolved)=>{
    if(supplied.kind==='unavailable')return {kind:'unavailable'};
    const result={kind:supplied.kind,id:supplied.id};
    if(supplied.name!==undefined)result.name=supplied.name;
    if(supplied.start && supplied.end)Object.assign(result,{start:supplied.start,end:supplied.end});
    if(resolved?.record)Object.assign(result,{name:resolved.record.name,projectId:resolved.projectId});
    // A collapsed anchor supplies no task dates beyond explicitly delivered metadata.
    if(resolved?.record && (supplied.kind==='project' || resolved.record.id===supplied.id)) {
      const dates=supplied.kind==='project'?resolved.dates:resolved.record;
      if(dates.start && dates.end)Object.assign(result,{start:dates.start,end:dates.end});
    }
    return result;
  };
  const dep=entry.dependency;
  return {id:dep.id,type:dep.type,lagDays:dep.lagDays ?? 0,lane:entry.overlay?.kind ?? 'current',overlayId:entry.overlay?.id ?? null,
    predecessor:details(dep.predecessor,entry.predecessor),successor:details(dep.successor,entry.successor),
    violated:!!dep.violated,evaluable:dep.evaluable ?? !!(entry.predecessor && entry.successor),diagnostics:dep.diagnostics ?? []};
}
