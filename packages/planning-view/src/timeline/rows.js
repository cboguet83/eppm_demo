/** Pure task/project projection; comparison identity never depends on row labels. */
import {ContractError} from '../contracts/index.js';

export const ROW_HEIGHT=41.4;
const key=(...parts)=>JSON.stringify(parts);
const stable=task=>task.stableId ?? task.id;

/** @param {object[]} tasks Dated records. @returns {object|null} Inclusive summary. */
export function summarizeDates(tasks) {
  if(!tasks.length)return null;
  let start=tasks[0].start,end=tasks[0].end;
  for(const task of tasks){if(task.start<start)start=task.start;if(task.end>end)end=task.end;}
  return {start,end};
}

/** Pair current and comparison records, retaining added/removed rows.
 * @param {object[]} tasks Current records. @param {object[]} overlays Project overlays.
 * @returns {object[]} Rows with explicit current and comparison targets.
 */
export function pairTasks(tasks,overlays) {
  const rows=[],byStable=new Map();
  const ensure=task=>{
    const identity=stable(task);
    if(!byStable.has(identity)) {
      const row={key:key('task',task.projectId,identity),kind:'task',projectId:task.projectId,current:null,comparisons:[]};
      rows.push(row);byStable.set(identity,row);
    }
    return byStable.get(identity);
  };
  for(const task of tasks)ensure(task).current=task;
  for(const overlay of overlays) {
    for(const task of overlay.tasks)ensure(task).comparisons.push({overlay,task});
  }
  return rows.map(row=>({...row,record:row.current ?? row.comparisons[0].task}));
}

/** @param {object} sort Sort field/direction. @returns {Function} Stable comparator. */
function comparator(sort={}) {
  const field=['id','name','start','end'].includes(sort.field)?sort.field:'start';
  const direction=sort.direction==='desc'?-1:1;
  return (a,b)=>String(a[field] ?? '').localeCompare(String(b[field] ?? ''),undefined,{numeric:true})*direction;
}

/** Project rows without changing supplied data or crossing project boundaries.
 * @param {object} data Valid complete snapshot. @param {object} view View state.
 * @param {{grouped?:boolean}} options Show project headers by default.
 * @returns {object} Rows and indexed project/task row positions.
 */
export function projectRows(data,view,{grouped=true}={}) {
  const tasks=new Map(),overlays=new Map(),loaded=new Set(data.loadedProjectIds),expanded=new Set(view.expandedProjects);
  for(const task of data.tasks){if(!tasks.has(task.projectId))tasks.set(task.projectId,[]);tasks.get(task.projectId).push(task);}
  for(const overlay of data.overlays){if(!overlays.has(overlay.projectId))overlays.set(overlay.projectId,[]);overlays.get(overlay.projectId).push(overlay);}
  const rows=[],projectIndexes=new Map(),taskIndexes=new Map(),comparisonIndexes=new Map();
  let projects=data.projects;
  if(view.filters.projectIds)projects=projects.filter(project=>view.filters.projectIds.includes(project.id));
  if(view.filters.query)projects=projects.filter(project=>project.name.toLocaleLowerCase().includes(view.filters.query.toLocaleLowerCase()));
  if(view.filters.sort?.direction!=='none' && view.filters.sort)projects=projects.toSorted(comparator(view.filters.sort));
  for(const project of projects) {
    const current=tasks.get(project.id) ?? [],comparisons=overlays.get(project.id) ?? [];
    const summary=project.start && project.end?{start:project.start,end:project.end}:summarizeDates(current);
    if(grouped) {
      projectIndexes.set(project.id,rows.length);
      rows.push({key:key('project',project.id),kind:'project',projectId:project.id,record:project,summary,
        expanded:expanded.has(project.id),taskCount:project.taskCount ?? current.length,
        comparisons:comparisons.map(overlay=>({overlay,task:summarizeDates(overlay.tasks)})).filter(item=>item.task)});
    }
    if(grouped && !expanded.has(project.id))continue;
    if(!loaded.has(project.id)) {
      for(let index=0;index<(project.taskCount ?? 1);index++)rows.push({key:key('loading',project.id,index),kind:'loading',projectId:project.id});
      continue;
    }
    const paired=pairTasks(current,comparisons);
    const compare=comparator(view.filters.taskSort);
    paired.sort((a,b)=>compare(a.record,b.record) || a.record.id.localeCompare(b.record.id,undefined,{numeric:true}));
    for(const row of paired) {
      if(row.current)taskIndexes.set(row.current.id,rows.length);
      for(const comparison of row.comparisons)comparisonIndexes.set(key(comparison.overlay.id,comparison.task.id),rows.length);
      rows.push(row);
    }
  }
  return {rows,projectIndexes,taskIndexes,comparisonIndexes};
}

/** Compute a bounded inclusive virtual row window.
 * @param {number} count Total rows. @param {number} top Scroll position.
 * @param {number} height Viewport. @param {number} overscan Extra rows each side.
 */
export function rowWindow(count,top,height,overscan=15) {
  if(!Number.isInteger(count) || count<0 || !Number.isFinite(top) || top<0 || !Number.isFinite(height) || height<0 || !Number.isInteger(overscan) || overscan<0)throw new ContractError('viewport');
  const visibleStart=Math.min(Math.max(0,count-1),Math.floor(top/ROW_HEIGHT));
  const visibleEnd=Math.min(count-1,Math.ceil((top+height)/ROW_HEIGHT));
  return {start:Math.max(0,visibleStart-overscan),end:Math.min(count-1,visibleEnd+overscan),visibleStart,visibleEnd};
}
