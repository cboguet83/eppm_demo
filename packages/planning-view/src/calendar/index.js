/** Date-only calendar arithmetic and shared, DOM-independent timeline geometry. */
import {ContractError, validateDate} from '../contracts/index.js';

const DAY_MS = 86400000;
const MONTHS = Object.freeze(['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']);
const WIDTHS = Object.freeze({Day:38,Week:65,Month:45,Quarter:28,Year:40});

/** @param {string} date Valid ISO calendar date. @returns {number} UTC day index. */
export function dayIndex(date) {
  validateDate(date);
  if (date.startsWith('0000')) throw new ContractError('date.year');
  return Date.parse(date + 'T00:00:00Z') / DAY_MS;
}

/** @param {number} index Integer UTC day index. @returns {string} ISO date. */
export function dateFromIndex(index) {
  if (!Number.isInteger(index) || !Number.isFinite(index)) throw new ContractError('dayIndex');
  const stamp = new Date(index * DAY_MS);
  if (!Number.isFinite(stamp.getTime())) throw new ContractError('dayIndex');
  const result = stamp.toISOString().slice(0,10);
  dayIndex(result);
  return result;
}

/** @param {string} date ISO date. @param {number} count Whole calendar days. */
export function addDays(date, count) {
  return dateFromIndex(dayIndex(date) + count);
}

/** @param {string} date ISO date. @param {number} count Whole months from month start. */
function monthStart(date, count = 0) {
  const stamp = new Date(dayIndex(date) * DAY_MS);
  stamp.setUTCDate(1);
  stamp.setUTCMonth(stamp.getUTCMonth() + count);
  return dateFromIndex(stamp.getTime() / DAY_MS);
}

/** @param {string} date ISO date. @returns {number} Zero-based month. */
function monthOf(date) { return Number(date.slice(5,7)) - 1; }

/** @param {string} mode Calendar view mode. */
function requireMode(mode) {
  if (!Object.hasOwn(WIDTHS, mode)) throw new ContractError('calendar.mode');
}

/** Compute existing padded display bounds, including milestone and empty views.
 * @param {Array<{start:string,end:string}>} rows Current and overlay ranges.
 * @param {string} mode View mode. @param {string} today Injected current date.
 * @returns {{start:string,end:string}} Start and exclusive display end.
 */
export function timelineBounds(rows, mode, today) {
  requireMode(mode);
  dayIndex(today);
  if (!rows.length) return {start:today,end:addDays(today,90)};
  let first = Infinity, last = -Infinity;
  for (const row of rows) {
    const start = dayIndex(row.start), end = dayIndex(row.end);
    if (end < start) throw new ContractError('calendar.range');
    first = Math.min(first,start);
    last = Math.max(last,end + Number(end !== start));
  }
  const start = dateFromIndex(first), end = dateFromIndex(last);
  if (mode === 'Day') return {start:addDays(start,-3),end:addDays(end,14)};
  if (mode === 'Week') return {start:addDays(start,-14),end:addDays(end,30)};
  if (mode === 'Quarter') return {start:monthStart(start,-monthOf(start)%3),end:monthStart(end,15-monthOf(end)%3)};
  if (mode === 'Year') return {start:monthStart(start,-monthOf(start)-12),end:monthStart(end,24-monthOf(end))};
  return {start:monthStart(start,-1),end:monthStart(end,4)};
}

/** @param {string} date Initial date. @param {string} mode View mode. */
function alignStart(date, mode) {
  if (mode === 'Month') return monthStart(date);
  if (mode === 'Quarter') return monthStart(date,-monthOf(date)%3);
  if (mode === 'Year') return monthStart(date,-monthOf(date));
  return date;
}

/** @param {string} date Period start. @param {string} mode View mode. */
function nextPeriod(date, mode) {
  if (mode === 'Day') return addDays(date,1);
  if (mode === 'Week') return addDays(date,7);
  return monthStart(date,{Month:1,Quarter:3,Year:6}[mode]);
}

/** @param {string} date Period start. @param {string} mode Mode. @param {string[]} months Labels. */
function labels(date, mode, months) {
  const month = monthOf(date), year = date.slice(0,4);
  if (mode === 'Day') return [months[month]+' '+year.slice(-2),String(Number(date.slice(8)))];
  if (mode === 'Week') return [months[month]+' '+year.slice(-2),'W'+Math.ceil(Number(date.slice(8))/7)];
  if (mode === 'Quarter') return [year,'Q'+(Math.floor(month/3)+1)];
  if (mode === 'Year') return [year,month < 6 ? 'H1' : 'H2'];
  return [year,months[month]];
}

/** Build aligned inclusive period cells and exact shared date/x conversion.
 * @param {{start:string,end:string,mode:string,viewportWidth?:number,today:string,months?:string[],maxPeriods?:number}} options Calendar options; end is exclusive.
 * @returns {object} Header cells, width, and conversion functions.
 */
export function createCalendar({start,end,mode,viewportWidth=0,today,months=MONTHS,maxPeriods=10000}) {
  requireMode(mode);
  if (dayIndex(end) <= dayIndex(start)) throw new ContractError('calendar.range');
  dayIndex(today);
  if (!Number.isFinite(viewportWidth) || viewportWidth < 0) throw new ContractError('calendar.width');
  if (!Number.isInteger(maxPeriods) || maxPeriods < 1) throw new ContractError('calendar.maxPeriods');
  if (!Array.isArray(months) || months.length !== 12 || !months.every(x=>typeof x==='string')) throw new ContractError('calendar.months');
  const bottomCells = [], topCells = [];
  let cursor = alignStart(start,mode);
  const lastIncluded = addDays(end,-1);
  const stop = mode === 'Year' ? monthStart(lastIncluded,12-monthOf(lastIncluded)) : end;
  while (cursor < stop) {
    if (bottomCells.length >= maxPeriods) throw new ContractError('calendar.periodLimit');
    const next = nextPeriod(cursor,mode), [group,label] = labels(cursor,mode,months);
    bottomCells.push({label,start:cursor,end:addDays(next,-1),width:WIDTHS[mode],isCurrent:cursor<=today && today<next});
    const previous = topCells.at(-1);
    if (previous?.label === group) previous.width += WIDTHS[mode];
    else topCells.push({label:group,width:WIDTHS[mode]});
    cursor = next;
  }
  const scale = Math.max(1,viewportWidth/(bottomCells.length*WIDTHS[mode]));
  let width = 0;
  for (const cell of bottomCells) { cell.width *= scale; cell.x = width; width += cell.width; }
  for (const cell of topCells) cell.width *= scale;
  const points = bottomCells.map(cell=>({...cell,first:dayIndex(cell.start),last:dayIndex(cell.end)+1}));

  /** @param {number} day Fractional day. @returns {number} Horizontal position. */
  const position = day => {
    const cell = points.find(cell=>day<cell.last) || points.at(-1);
    return cell.x + (day-cell.first)/(cell.last-cell.first)*cell.width;
  };
  /** @param {number} x Horizontal position. @returns {number} Fractional day. */
  const dayAt = x => {
    if (!Number.isFinite(x)) throw new ContractError('calendar.x');
    const cell = points.find(cell=>x<cell.x+cell.width) || points.at(-1);
    return cell.first+(x-cell.x)/cell.width*(cell.last-cell.first);
  };
  return {topCells,bottomCells,width,start:points[0].start,end:cursor,
    dateToX:date=>position(dayIndex(date)),
    endDateToX:date=>position(dayIndex(date)+1),
    dateAtX:x=>dateFromIndex(Math.floor(dayAt(x)+1e-9)),
    dragDays:(x,delta)=>Math.round(dayAt(x+delta)-dayAt(x))};
}

/** Apply a date edit without changing its input; moving milestones retains one day.
 * @param {{start:string,end:string}} task Original range. @param {number} days Day delta.
 * @param {'move'|'start'|'end'} edge Drag target. @returns {object} Updated range.
 */
export function shiftTask(task, days, edge='move') {
  const start=dayIndex(task.start),end=dayIndex(task.end);
  if (!Number.isInteger(days) || end<start || !['move','start','end'].includes(edge)) throw new ContractError('calendar.edit');
  if (edge === 'move' || start === end) return {...task,start:dateFromIndex(start+days),end:dateFromIndex(end+days)};
  if (edge === 'start') return {...task,start:dateFromIndex(Math.min(end,start+days))};
  return {...task,end:dateFromIndex(Math.max(start,end+days))};
}
