const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../app/presentation/components/dashboard_resource_chart.py'),'utf8');
const js = source.match(/_JS = r"""([\s\S]*?)"""/)[1].replace('export default function','function render');

class Element {
  constructor(tag){this.tag=tag;this.attrs={};this.children=[];this.style={setProperty(key,value){this[key]=value;}};this.offsetWidth=100;this.offsetHeight=50;}
  setAttribute(key,value){this.attrs[key]=String(value);}
  appendChild(child){this.children.push(child);child.parent=this;}
  replaceChildren(...children){this.children=[];children.forEach(child=>this.appendChild(child));}
  remove(){this.parent.children=this.parent.children.filter(child=>child!==this);}
  getScreenCTM(){return {inverse(){return {};}};}
  focus(){}
}
function setup(){
  const listeners=new Map();
  const document={createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag),
    addEventListener:(name,fn)=>{if(!listeners.has(name))listeners.set(name,new Set());listeners.get(name).add(fn);},
    removeEventListener:(name,fn)=>listeners.get(name).delete(fn),
    dispatchEvent:event=>{for(const fn of listeners.get(event.type)||[])fn(event);}};
  const context=vm.createContext({document,window:{innerWidth:1500,innerHeight:1000},
    DOMPoint:class {constructor(x,y){this.x=x;this.y=y;}matrixTransform(){return this;}},
    CustomEvent:class {constructor(type,options){this.type=type;this.detail=options.detail;}}});
  vm.runInContext(js,context);
  const build=(metric,capacity=7,extraPools=[],financial={})=>{
    const root=new Element('root'),events=[];
    const cleanup=context.render({parentElement:{querySelector:()=>root},setTriggerValue(name,value){events.push({name,...value});},data:{
      palette:['#000000','#399df4','#09703e','#b1343b','#de00c3','#ffd700','#848486','#0000f0','#fa8775','#8800d2','#ffb14e','#ea5f94','#f10d0d','#0ccd66','#27e0e0'],
      budgetSeries:metric==='finance'?[{name:'Approved',points:[{date:'2026-01-01',value:100},{date:'2026-04-01',value:null},{date:'2026-07-01',value:80}]},{name:'Proposed',points:[{date:'2026-01-01',value:120}]}]:[],
      metric,locale:'en',rows:metric==='finance'?[]:[{quarter:'2026-Q1',value:metric==='allocation'?10:3,capacity}],
      pools:[{pool_id:1,name:'Pool X',allocation:{'2026-Q1':10},overallocation:{'2026-Q1':3},available:{'2026-Q1':-3}},...extraPools],
      totalLabel:'Total',allocatedLabel:'Allocation',availableLabel:'Available',goTo:'Planning',poolDetails:'Pool details',filterPool:'Filter on this pool',
      totalValueLabel:metric==='allocation'?'Total allocation':'Total overallocation',totalCapacityLabel:'Total capacity',
      valueLabel:metric==='overallocation'?'Overallocation':'Allocation',capacityLabel:'Total pools capacity',today:'2026-01-01',start:'2026-01-01',end:'2027-01-01',...financial}});
    return {root,svg:root.children.find(e=>e.tag==='svg'),cleanup,events};
  };
  return {build,listeners};
}
test('resource tooltips render translated labels, quarter and FTE unit',()=>{
  const {build}=setup();
  const chart=build('allocation',7,[],{locale:'fr',fteUnit:'ETP',quarterPrefix:'T',
    totalCapacityLabel:'Capacité minimale',totalValueLabel:'Allocation totale',
    allocatedLabel:'Allocation',availableLabel:'Disponible'});
  chart.svg.children.find(e=>e.tag==='rect').onpointermove({clientX:500,clientY:100});
  const text=chart.root.children.find(e=>e.className==='tip').children
    .map(row=>row.children.map(child=>child.textContent||'').join('')).join('\n');
  assert.equal(text,'2026-T1\nCapacité minimale: 7 ETP\nAllocation totale: 10 ETP\nPool X — Allocation: 10 ETP\nPool X — Disponible: -3 ETP');
  chart.cleanup();
});

test('metric tooltips use the requested line order and omit peak dates',()=>{
  const {build}=setup();
  for(const metric of ['overallocation','allocation']){
    const chart=build(metric),bar=chart.svg.children.find(e=>e.tag==='rect');
    bar.onpointermove({clientX:500,clientY:100});
    const tip=chart.root.children.find(e=>e.className==='tip');
    const text=tip.children.map(row=>row.children.map(child=>child.textContent||'').join('')).join('\n');
    assert.equal(text,metric==='overallocation'
      ?'2026-Q1\nOverallocation\nTotal: 3 FTE\nPool X: 3 FTE'
      :'2026-Q1\nTotal capacity: 7 FTE\nTotal allocation: 10 FTE\nPool X — Allocation: 10 FTE\nPool X — Available: -3 FTE');
    assert.equal(tip.children[3].children[0].style['--series'],bar.attrs.fill);
    assert.equal(tip.children[3].children[0].className,'pool-swatch');
    assert.equal(chart.root.children.some(e=>e.className==='legend'),false);
    chart.cleanup();
  }
});

test('finance legend follows the plot and either budget tooltip includes both values',()=>{
  const {build}=setup(),chart=build('finance');
  assert.equal(chart.root.children[0].tag,'svg');
  assert.equal(chart.root.children[1].className,'legend');
  const markers=chart.svg.children.filter(e=>e.tag==='circle');
  for(const marker of [markers[0],markers[2]]){
    marker.onpointermove({clientX:400,clientY:100});
    const text=chart.root.children.find(e=>e.className==='tip').children.map(row=>row.children[0].textContent);
    assert.deepEqual(text,['2026','Approved: 0 kEUR','Proposed: 0 kEUR']);
  }
  markers[1].onpointermove({clientX:400,clientY:100});
  assert.equal(chart.root.children.find(e=>e.className==='tip').children[2].children[0].textContent,'Proposed: —');
  chart.cleanup();
});

test('tooltip rounding removes decimals without rounding the plotted data',()=>{
  const {build}=setup();
  const chart=build('finance',7,[],{
    budgetSeries:[{name:'Approved',points:[{date:'2026-01-01',value:1234567.89}]}],
    transactions:[{year:2026,actual:2345678.9}],
    transactionSeries:[{key:'actual',name:'Actual',color:'#C41049'}]
  });
  const marker=chart.svg.children.find(e=>e.tag==='circle');
  marker.onpointermove({clientX:400,clientY:100});
  assert.equal(chart.root.children.find(e=>e.className==='tip').children[1].children[0].textContent,'Approved: 1,235 kEUR');
  const bar=chart.svg.children.find(e=>e.attrs['data-financial-year']);
  bar.onpointermove({clientX:400,clientY:100});
  assert.equal(chart.root.children.find(e=>e.className==='tip').children[1].children[1].textContent,'Actual: 2,346 kEUR');
  chart.cleanup();
  const resource=build('allocation',7.6,[],{
    pools:[{pool_id:1,name:'Pool X',allocation:{'2026-Q1':10.6},overallocation:{},available:{'2026-Q1':-3.4}}]
  });
  resource.svg.children.find(e=>e.tag==='rect').onpointermove({clientX:400,clientY:100});
  const labels=resource.root.children.find(e=>e.className==='tip').children.map(row=>row.children.at(-1).textContent);
  assert.ok(labels.some(text=>text.endsWith('11 FTE')));
  assert.ok(labels.some(text=>text.endsWith('-3 FTE')));
  resource.cleanup();
});

test('finance and resources align data positions and synchronize guides using the requested palette',()=>{
  const {build}=setup(),finance=build('finance'),resource=build('allocation');
  for(const chart of [finance,resource]){
    assert.equal(chart.svg.attrs.preserveAspectRatio,'none');
    assert.equal(chart.svg.attrs.viewBox,'0 0 1025 300');
    const gridLine=chart.svg.children.find(e=>e.tag==='line');
    assert.equal(gridLine.attrs.x2,'1025');
  }
  const year=chart=>chart.svg.children.find(e=>e.attrs['data-year']==='2026');
  assert.equal(year(finance).attrs.x,year(resource).attrs.x);
  const lines=finance.svg.children.filter(e=>e.tag==='path');
  assert.deepEqual(lines.map(e=>e.attrs.stroke),['#000000','#399df4']);
  assert.equal((lines[0].attrs.d.match(/M/g)||[]).length,2,'Missing years must break the line');
  assert.equal(resource.svg.children.find(e=>e.tag==='rect').attrs.fill,'#399df4');
  assert.equal(resource.svg.children.find(e=>e.tag==='path').attrs.stroke,'#f10d0d');
  assert.equal(resource.svg.children.find(e=>e.tag==='path').attrs['stroke-dasharray'],'6 4');
  finance.svg.onpointermove({clientX:400,clientY:100});
  assert.equal(resource.svg.children.find(e=>e.attrs['data-hover-line']).attrs.x1,'400');
  finance.cleanup();resource.cleanup();
});
test('hover position and clearing synchronize across both charts without listener leaks',()=>{
  const {build,listeners}=setup(),one=build('overallocation'),two=build('allocation');
  const line=chart=>chart.svg.children.find(e=>e.attrs['data-hover-line']);
  assert.equal(line(one).attrs.stroke,'#374151');
  assert.equal(line(one).attrs['stroke-width'],'3');
  assert.equal(line(two).attrs.stroke,'#374151');
  assert.equal(line(two).attrs['stroke-width'],'3');
  one.svg.onpointermove({clientX:400,clientY:100});
  assert.equal(line(one).attrs.visibility,'visible');
  assert.equal(line(two).attrs.x1,line(one).attrs.x1);
  two.svg.onpointermove({clientX:800,clientY:100});
  assert.equal(line(one).attrs.x1,'800');
  assert.equal(line(two).attrs.x1,'800');
  two.svg.onpointerleave();
  assert.equal(line(one).attrs.visibility,'hidden');
  assert.equal(line(two).attrs.visibility,'hidden');
  one.cleanup();two.cleanup();
  assert.equal(listeners.get('eppm-resource-chart-hover').size,0);
});

test('resource stacks and capacity points align with quarter starts on the shared timeline',()=>{
  const {build}=setup();
  for(const metric of ['allocation','overallocation']){
    const chart=build(metric);
    const bar=chart.svg.children.find(e=>e.attrs['data-quarter']==='2026-Q1');
    const center=Number(bar.attrs.x)+Number(bar.attrs.width)/2;
    const first=Date.UTC(2025,6,1),last=Date.UTC(2027,0,1);
    const expected=110+(1025-110)*(Date.UTC(2026,0,1)-first)/(last-first);
    assert.ok(Math.abs(center-expected)<1e-9);
    if(metric==='allocation'){
      const capacity=chart.svg.children.find(e=>e.tag==='path');
      assert.ok(Math.abs(Number(capacity.attrs.d.match(/^M([^,]+)/)[1])-center)<1e-9);
    }
    chart.cleanup();
  }
});

test('financial axes use round kEUR intervals with at most one decimal',()=>{
  const {build}=setup();
  for(const [euros,expected] of [
    [876000,[0,225,450,675,900]],
    [12345000,[0,5000,10000,15000,20000]], [152,[0,.1,.2,.3,.4]],
    [9654000,[0,2500,5000,7500,10000]], [9800000,[0,2500,5000,7500,10000]],
  ]){
    const chart=build('finance',7,[],{budgetSeries:[{name:'Approved',points:[{date:'2026-01-01',value:euros}]}]});
    const ticks=chart.svg.children.filter(e=>e.attrs['data-axis']==='finance').map(e=>e.textContent);
    assert.equal(ticks.length,5);
    assert.deepEqual(ticks.map(value=>Number(value.replaceAll(',',''))),expected);
    assert.ok(ticks.every(value=>!value.includes('.')||value.split('.')[1].length<=1));
    chart.cleanup();
  }
});

test('resource year labels center between Q2 and Q3 and titles are horizontal',()=>{
  const {build}=setup();
  for(const metric of ['allocation','overallocation']){
    const quarters=['2026-Q1','2026-Q2','2026-Q3','2026-Q4'];
    const values=Object.fromEntries(quarters.map(quarter=>[quarter,10]));
    const chart=build(metric,7,[],{
      rows:quarters.map(quarter=>({quarter,value:10,capacity:7})),
      pools:[{pool_id:1,name:'Pool X',allocation:values,overallocation:values,available:values}]
    });
    const center=quarter=>{
      const bar=chart.svg.children.find(e=>e.attrs['data-quarter']===quarter);
      return Number(bar.attrs.x)+Number(bar.attrs.width)/2;
    };
    const year=chart.svg.children.find(e=>e.attrs['data-year']==='2026');
    assert.ok(Math.abs(Number(year.attrs.x)-(center('2026-Q2')+center('2026-Q3'))/2)<1e-9);
    const title=chart.svg.children.find(e=>e.attrs['data-axis-title']===metric);
    assert.equal(title.attrs.transform,undefined);
    assert.equal(title.attrs.y,'15');
    chart.cleanup();
  }
});

test('overallocation omits capacity and allocation uses a shared axis including higher capacity',()=>{
  const {build}=setup();
  const over=build('overallocation',20);
  assert.equal(over.svg.children.filter(e=>e.tag==='path').length,0);
  assert.equal(over.root.children[0].children.some(e=>e.textContent==='Total pools capacity'),false);
  for(const capacity of [7,20]){
    const chart=build('allocation',capacity);
    assert.equal(chart.svg.children.some(e=>e.attrs['data-axis']==='capacity'),false);
    const bar=chart.svg.children.find(e=>e.tag==='rect');
    const line=chart.svg.children.find(e=>e.tag==='path');
    const lineY=Number(line.attrs.d.split(',')[1]);
    assert.ok(Math.abs((248-lineY)/Number(bar.attrs.height)-capacity/10)<1e-10);
    assert.ok(lineY>=25);
    chart.cleanup();
  }
  over.cleanup();
});

test('both resource menus navigate to the selected pool or its consuming projects',()=>{
  const {build,listeners}=setup();
  let navigationStarts=0;
  listeners.set('eppm-navigation-start',new Set([()=>navigationStarts++]));
  for(const metric of ['allocation','overallocation']){
    const chart=build(metric),bar=chart.svg.children.find(e=>e.tag==='rect');
    for(const [index,action] of [[1,'planning'],[2,'pool_details'],[3,'filter_pool']]){
      bar.oncontextmenu({preventDefault(){},clientX:400,clientY:100});
      const menu=chart.root.children.find(e=>e.className==='context-menu');
      assert.deepEqual(menu.children.slice(1).map(e=>e.textContent),['Planning','Pool details','Filter on this pool']);
      const before=navigationStarts;
      menu.children[index].onclick();
      assert.equal(navigationStarts-before,action==='filter_pool'?0:1);
      assert.deepEqual(chart.events.at(-1),{name:'selection',quarter:'2026-Q1',pool_id:1,metric,action});
      assert.equal(chart.root.children.some(e=>e.className==='context-menu'),false);
    }
    chart.cleanup();
  }
});

test('individual pool peaks stack and hide the summed capacity line',()=>{
  const {build}=setup();
  const chart=build('allocation',100,[{pool_id:2,name:'Pool Y',allocation:{'2026-Q1':8},overallocation:{'2026-Q1':1},available:{'2026-Q1':2}}]);
  const bars=chart.svg.children.filter(e=>e.tag==='rect');
  assert.equal(bars.length,2);
  assert.equal(bars[0].attrs.x,bars[1].attrs.x);
  assert.equal(Number(bars[0].attrs.y)+Number(bars[0].attrs.height),248);
  assert.ok(Math.abs(Number(bars[1].attrs.y)+Number(bars[1].attrs.height)-Number(bars[0].attrs.y))<1e-9);
  assert.equal(chart.svg.children.filter(e=>e.tag==='path').length,0);
  chart.cleanup();
});


test('financial bars stack actual and commitment totals and support signed corrections',()=>{
  const {build}=setup();
  const transactionSeries=[{key:'actual',name:'Actual',color:'#C41049'},{key:'commitment',name:'Commitment',color:'#6D6E70'}];
  const chart=build('finance',7,[],{transactionSeries,transactions:[{year:2026,actual:80,commitment:120}]});
  const bars=chart.svg.children.filter(e=>e.attrs['data-financial-year']);
  assert.equal(bars.length,2);
  assert.equal(bars[0].attrs.fill,'#C41049');
  assert.equal(bars[1].attrs.fill,'#6D6E70');
  assert.equal(bars[0].attrs.x,bars[1].attrs.x);
  const point=chart.svg.children.find(e=>e.tag==='circle');
  assert.ok(Math.abs(Number(bars[0].attrs.x)+Number(bars[0].attrs.width)/2-Number(point.attrs.cx))<1e-9);
  assert.ok(Math.abs(Number(bars[1].attrs.y)+Number(bars[1].attrs.height)-Number(bars[0].attrs.y))<.001);
  assert.ok(Number(bars[1].attrs.y)>=25);
  assert.equal(chart.root.children[1].children.filter(e=>e.className==='bar-series').length,2);
  bars[0].onpointermove({clientX:400,clientY:100});
  const tip=chart.root.children.find(e=>e.className==='tip');
  assert.equal(tip.children[1].children[1].textContent,'Actual: 0 kEUR');
  chart.cleanup();
  const signed=build('finance',7,[],{transactionSeries,transactions:[{year:2026,actual:-20,commitment:50}]});
  const signedBars=signed.svg.children.filter(e=>e.attrs['data-financial-year']);
  assert.ok(Number(signedBars[0].attrs.y)>Number(signedBars[1].attrs.y));
  assert.ok(signedBars.every(e=>Number(e.attrs.height)>0));
  signed.cleanup();
});

test('financial values use kEUR and the first centered annual bar clears the value axis',()=>{
  const {build}=setup();
  const chart=build('finance',7,[],{
    start:'2024-01-01',end:'2036-01-01',
    budgetSeries:[{name:'Approved',points:[{date:'2024-01-01',value:1000000}]}],
    transactions:[{year:2024,actual:1000000}],
    transactionSeries:[{key:'actual',name:'Actual',color:'#C41049'}]
  });
  const bar=chart.svg.children.find(e=>e.attrs['data-financial-year']);
  const tick=chart.svg.children.find(e=>e.attrs['data-axis']==='finance');
  assert.ok(Number(bar.attrs.x)-Number(tick.attrs.x)>=20);
  const ticks=chart.svg.children.filter(e=>e.attrs['data-axis']==='finance');
  assert.equal(ticks.at(-1).textContent,'1,000');
  chart.cleanup();
});
