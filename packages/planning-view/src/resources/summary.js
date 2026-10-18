/** Sparse daily resource summaries; no DOM, transport, or business writes. */
import {ContractError} from '../contracts/index.js';
import {dayIndex,dateFromIndex} from '../calendar/index.js';

const EMPTY = Object.freeze({});
const EPSILON = 0.0001;

/** Decode inclusive intervals, retaining zeroes and missing dates.
 * @param {Array<[string,string,number]>} intervals Ordered nonoverlapping intervals.
 * @param {number} maxDays Maximum expanded entries, default twenty-five years.
 * @returns {Object<string,number>} Independently owned daily series.
 */
export function decodeIntervals(intervals,maxDays=365*25) {
  if (!Array.isArray(intervals) || !Number.isInteger(maxDays) || maxDays<1) throw new ContractError('intervals');
  const result={};
  let previous=-Infinity,count=0;
  for (const interval of intervals) {
    if (!Array.isArray(interval) || interval.length!==3) throw new ContractError('interval');
    const [start,end,value]=interval,first=dayIndex(start),last=dayIndex(end);
    if (last<first || first<=previous || !Number.isFinite(value) || value<0) throw new ContractError('interval.range');
    count+=last-first+1;
    if (count>maxDays) throw new ContractError('interval.limit');
    for (let day=first;day<=last;day++) result[dateFromIndex(day)]=value;
    previous=last;
  }
  return result;
}

/** @param {string[]} dates Sorted dates. @param {string} target Lower bound. */
function lowerBound(dates,target) {
  let low=0,high=dates.length;
  while (low<high) {
    const middle=(low+high)>>>1;
    if (dates[middle]<target) low=middle+1; else high=middle;
  }
  return low;
}

/** Own identity-keyed indexes/caches for one instance's immutable daily series.
 * @returns {{summarize:Function,clear:Function}} Resource period interface.
 */
export function createResourceSummaries() {
  let indexes=new WeakMap(),cache=new WeakMap();
  /** @param {object} series Immutable validated daily series. */
  const dates = series => {
    let result=indexes.get(series);
    if (!result) { result=Object.keys(series).sort(); indexes.set(series,result); }
    return result;
  };
  /** @param {object} series Series. @param {string} start First date. @param {string} end Last date. */
  const inPeriod = (series,start,end) => {
    const keys=dates(series),result=[];
    for (let i=lowerBound(keys,start);i<keys.length && keys[i]<=end;i++) result.push(keys[i]);
    return result;
  };
  /** Summarize already validated, immutable series. Missing overrides use base.
   * @param {object} options Period and series.
   * @returns {object} Frozen extrema and capacity status.
   */
  const summarize = ({usage=EMPTY,assignedCapacity=EMPTY,capacity,start,end}) => {
    const days=dayIndex(end)-dayIndex(start)+1;
    if (days<1 || !Number.isFinite(capacity) || capacity<0) throw new ContractError('resource.period');
    let byCapacity=cache.get(usage);
    if (!byCapacity) { byCapacity=new WeakMap(); cache.set(usage,byCapacity); }
    let periods=byCapacity.get(assignedCapacity);
    if (!periods) { periods=new Map(); byCapacity.set(assignedCapacity,periods); }
    const key=capacity+':'+start+':'+end;
    if (periods.has(key)) return periods.get(key);
    const overrideDays=inPeriod(assignedCapacity,start,end);
    const demandDays=inPeriod(usage,start,end);
    const covered=new Set([...overrideDays,...demandDays]);
    const capacities=overrideDays.map(day=>assignedCapacity[day]);
    if (overrideDays.length<days) capacities.push(capacity);
    let maxDemand=0,maxExcess=0,minAvailable=Infinity;
    for (const day of covered) {
      const effective=Object.hasOwn(assignedCapacity,day)?assignedCapacity[day]:capacity;
      const demand=usage[day] ?? 0;
      maxDemand=Math.max(maxDemand,demand);
      maxExcess=Math.max(maxExcess,demand-effective);
      minAvailable=Math.min(minAvailable,effective-demand);
    }
    if (covered.size<days) minAvailable=Math.min(minAvailable,capacity);
    const minCapacity=capacities.reduce((value,item)=>Math.min(value,item),Infinity);
    const maxCapacity=capacities.reduce((value,item)=>Math.max(value,item),-Infinity);
    const result=Object.freeze({minCapacity,maxCapacity,
      maxDemand,maxExcess:Math.max(0,maxExcess),isOverallocated:maxExcess>EPSILON,
      minAvailable:Math.max(0,minAvailable)});
    periods.set(key,result);
    return result;
  };
  return {summarize,clear(){indexes=new WeakMap();cache=new WeakMap();}};
}

/** @param {number} value Valid nonnegative FTE. @returns {string} Existing display precision. */
export function formatResourceValue(value) {
  if (!Number.isFinite(value) || value<0) throw new ContractError('resource.value');
  return value>=100?String(Math.round(value)):value.toFixed(1);
}
