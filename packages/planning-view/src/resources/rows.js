/** Iterative hierarchy projection and two-dimensional bounded grid windows. */
import {formatResourceValue} from './summary.js';
import {ContractError} from '../contracts/index.js';

export const RESOURCE_ROW_HEIGHT=23.8;
const EMPTY=Object.freeze({});

/** @param {object} resource Resource. @param {string} scope Demand scope. @param {boolean} comparison Alternative data. */
export function demandSeries(resource,scope,comparison=false) {
  return comparison?(resource.comparisonUsage?.[scope] ?? EMPTY):(scope==='selected'?resource.selectedUsage ?? EMPTY:resource.usage ?? EMPTY);
}

/** @param {object} resource Resource. @param {object} cell Inclusive period. @param {object} summaries Instance cache. @param {string} scope Demand scope. @param {boolean} comparison Comparison scope. */
export function periodSummary(resource,cell,summaries,scope='total',comparison=false) {
  return summaries.summarize({capacity:resource.capacity,assignedCapacity:resource.assignedCapacity,usage:demandSeries(resource,scope,comparison),start:cell.start,end:cell.end});
}

/** @param {object} resource Resource. @param {string} scope Scope. @param {object} calendar Calendar. @param {object} summaries Cache. */
function comparisonDiffers(resource,scope,calendar,summaries) {
  if(resource.comparisonUsage?.[scope]===undefined)return false;
  return calendar.bottomCells.some(cell=>formatResourceValue(periodSummary(resource,cell,summaries,scope).maxDemand)!==
    formatResourceValue(periodSummary(resource,cell,summaries,scope,true).maxDemand));
}

/** Preserve resource semantics without recursive visits or HTML ownership.
 * @param {object} data Snapshot. @param {object} view View.
 * @param {object} calendar Shared calendar. @param {object} summaries Cache.
 * @returns {object} Display rows, visible pool records, and hierarchy membership.
 */
export function resourceRows(data,view,calendar,summaries) {
  const filters={hideUnused:true,onlyOverallocated:false,showTotal:true,showSelected:true,...view.filters.resources};
  const range={start:calendar.start,end:calendar.bottomCells.at(-1).end};
  const visible=data.resources.filter(resource=>{
    const used=resource.usedBySelection!==false || Object.values(resource.comparisonUsage?.selected ?? EMPTY).some(value=>value>0);
    if(filters.hideUnused && !used)return false;
    return !filters.onlyOverallocated || ['total','selected'].some(scope=>periodSummary(resource,range,summaries,scope).isOverallocated ||
      periodSummary(resource,range,summaries,scope,true).isOverallocated);
  });
  const pools=new Map(visible.map(resource=>[resource.id,resource]));
  const hierarchy=data.hierarchy.length?data.hierarchy:visible.map(resource=>({id:JSON.stringify(['resource',resource.id]),resourceId:resource.id,name:resource.name}));
  const descendants=new Map(),pending=hierarchy.map(node=>({node,leaving:false}));
  while(pending.length) {
    const {node,leaving}=pending.pop();
    if(!leaving) {
      pending.push({node,leaving:true});for(const child of node.children ?? [])pending.push({node:child,leaving:false});continue;
    }
    const ids=new Set(pools.has(node.resourceId)?[node.resourceId]:[]);
    for(const child of node.children ?? [])for(const id of descendants.get(child.id))ids.add(id);
    descendants.set(node.id,[...ids]);
  }
  const rows=[],collapsed=new Set(view.collapsedResources),walk=hierarchy.toReversed().map(node=>({node,depth:0}));
  const append=(row,scope,comparison=false)=>rows.push({...row,scope,comparison,key:JSON.stringify([row.node.id,scope,comparison])});
  while(walk.length) {
    const {node,depth}=walk.pop(),ids=descendants.get(node.id);
    if(!ids.length)continue;
    const pool=pools.get(node.resourceId),isCollapsed=collapsed.has(node.id);
    const row={node,depth,collapsed:isCollapsed,pool,resourceIds:ids};
    if(!node.resourceId) {
      append(row,'total');
      if(filters.showTotal && ids.some(id=>comparisonDiffers(pools.get(id),'total',calendar,summaries)))append(row,'total',true);
    }else if(pool) {
      append(row,isCollapsed?'total':'assigned');
      if(!isCollapsed)for(const [scope,shown] of [['total',filters.showTotal],['selected',filters.showSelected]]) {
        if(!shown)continue;
        append({...row,depth:depth+1},scope);
        if(comparisonDiffers(pool,scope,calendar,summaries))append({...row,depth:depth+1},scope,true);
      }
    }
    if(!isCollapsed)for(const child of (node.children ?? []).toReversed())walk.push({node:child,depth:depth+1});
  }
  return {rows,pools,descendants};
}

/** @param {object} row Resource display row. @param {object} cell Calendar period. @param {object} pools Visible index. @param {object} summaries Cache. */
export function resourceCell(row,cell,pools,summaries) {
  if(!row.pool) {
    const over=row.resourceIds.some(id=>(row.comparison?[row.scope]:['total','selected']).some(scope=>periodSummary(pools.get(id),cell,summaries,scope,row.comparison).isOverallocated));
    return {value:null,isOverallocated:over};
  }
  const summary=periodSummary(row.pool,cell,summaries,row.scope,row.comparison);
  return {...summary,value:row.scope==='assigned'?summary.minCapacity:summary.maxDemand};
}

/** @param {number} count Rows. @param {number} top Vertical offset. @param {number} height Viewport. @param {object[]} cells Calendar cells. @param {number} left Horizontal offset. @param {number} width Viewport width. */
export function resourceWindow(count,top,height,cells,left,width) {
  if(!Number.isSafeInteger(count) || count<0 || [top,height,left,width].some(value=>!Number.isFinite(value) || value<0))throw new ContractError('resource.viewport');
  const first=Math.min(Math.max(0,count-1),Math.floor(top/RESOURCE_ROW_HEIGHT)),last=Math.min(count-1,Math.ceil((top+height)/RESOURCE_ROW_HEIGHT));
  let low=0,high=cells.length;
  while(low<high){const middle=(low+high)>>>1;if(cells[middle].x+cells[middle].width<=left)low=middle+1;else high=middle;}
  const colFirst=Math.max(0,Math.min(cells.length-1,low)-2);
  while(low<cells.length && cells[low].x<left+width)low++;
  return {start:Math.max(0,first-6),end:Math.min(count-1,last+6),colFirst,colLast:Math.min(cells.length-1,low+2)};
}
