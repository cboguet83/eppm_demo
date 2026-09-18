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
  const build=(metric,capacity=7,extraPools=[])=>{
    const root=new Element('root'),events=[];
    const cleanup=context.render({parentElement:{querySelector:()=>root},setTriggerValue(name,value){events.push({name,...value});},data:{
      palette:['#000000','#399df4','#09703e','#b1343b','#de00c3','#ffd700','#848486','#0000f0','#fa8775','#8800d2','#ffb14e','#ea5f94','#f10d0d','#0ccd66','#27e0e0'],
      budgetSeries:metric==='finance'?[{name:'Approved',points:[{date:'2026-01-01',value:100},{date:'2026-04-01',value:null},{date:'2026-07-01',value:80}]},{name:'Proposed',points:[{date:'2026-01-01',value:120}]}]:[],
      metric,locale:'en',rows:metric==='finance'?[]:[{quarter:'2026-Q1',value:metric==='allocation'?10:3,capacity}],
      pools:[{pool_id:1,name:'Pool X',allocation:{'2026-Q1':10},overallocation:{'2026-Q1':3},available:{'2026-Q1':-3}},...extraPools],
      totalLabel:'Total',allocatedLabel:'Allocation',availableLabel:'Available',goTo:'Planning',poolDetails:'Pool details',filterPool:'Filter on this pool',
      totalValueLabel:metric==='allocation'?'Total allocation':'Total overallocation',totalCapacityLabel:'Total capacity',
      valueLabel:metric==='overallocation'?'Overallocation':'Allocation',capacityLabel:'Total pools capacity',today:'2026-01-01',start:'2026-01-01',end:'2027-01-01'}});
    return {root,svg:root.children.find(e=>e.tag==='svg'),cleanup,events};
  };
  return {build,listeners};
}
test('metric tooltips use the requested line order and omit peak dates',()=>{
  const {build}=setup();
  for(const metric of ['overallocation','allocation']){
    const chart=build(metric),bar=chart.svg.children.find(e=>e.tag==='rect');
    bar.onpointermove({clientX:500,clientY:100});
    const tip=chart.root.children.find(e=>e.className==='tip');
    const text=tip.children.map(row=>row.children.map(child=>child.textContent||'').join('')).join('\n');
    assert.equal(text,metric==='overallocation'
      ?'2026-Q1\nOverallocation\nTotal: 3.0 FTE\nPool X: 3.0 FTE'
      :'2026-Q1\nTotal capacity: 7.0 FTE\nTotal allocation: 10.0 FTE\nPool X — Allocation: 10.0 FTE\nPool X — Available: -3.0 FTE');
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
    assert.deepEqual(text,['2026','Approved: 100.00 €','Proposed: 120.00 €']);
  }
  markers[1].onpointermove({clientX:400,clientY:100});
  assert.equal(chart.root.children.find(e=>e.className==='tip').children[2].children[0].textContent,'Proposed: —');
  chart.cleanup();
});

test('finance and resources align date ticks and synchronize guides using the requested palette',()=>{
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
