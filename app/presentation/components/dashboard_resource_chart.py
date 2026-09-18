"""Accessible quarterly resource chart with an authorized planning drill-through."""

from collections.abc import Callable

import streamlit as st

from app.application.ports.dashboard import ResourceBreakdown

from app.presentation.components.context_menu import CONTEXT_MENU_CSS

PALETTE = ['#000000', '#399df4', '#09703e', '#b1343b', '#de00c3',
           '#ffd700', '#848486', '#0000f0', '#fa8775', '#8800d2',
           '#ffb14e', '#ea5f94', '#f10d0d', '#0ccd66', '#27e0e0']

_CSS = """
.resource-chart {position:relative;display:grid;grid-template-columns:minmax(0,1fr);align-items:center;gap:0;overflow-x:auto;color:var(--st-text-color);font:12px var(--st-font)}
svg {grid-column:1;grid-row:1;display:block;width:100%;height:300px;overflow:visible}
.legend {grid-column:1;grid-row:2;display:flex;flex-wrap:wrap;gap:16px;justify-content:center;margin:0;padding:0 0 8px}
.pool-swatch {display:inline-block;width:10px;height:10px;margin-right:6px;background:var(--series)}
.legend span::before {content:'';display:inline-block;width:22px;height:3px;background:var(--series);margin-right:7px;vertical-align:middle}
.tip {position:fixed;background:var(--st-background-color);color:var(--st-text-color);border:1px solid #cbd5e1;box-shadow:0 4px 12px #0002;padding:8px;border-radius:5px;white-space:pre-line;pointer-events:none;z-index:10001}
[data-quarter]:focus {outline:2px solid #C41039;outline-offset:-2px}
"""

_JS = r"""
export default function({data,parentElement,setTriggerValue}) {
    const root=parentElement.querySelector('.resource-chart'),ns='http://www.w3.org/2000/svg';
    const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 1025 300');svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('aria-label',data.title);
    const legend=document.createElement('div');legend.className='legend';
    const palette=data.palette;
    const color=id=>palette[1+(Math.abs(Number(id)-1)%(palette.length-1))];
    const budgetSeries=data.budgetSeries||[];
    const pools=data.pools.filter(pool=>data.rows.some(row=>Number(pool[data.metric][row.quarter])>0));
    const showCapacity=data.metric==='allocation' && pools.length===1;
    const capacity=row=>Number(pools[0]?.capacity?.[row.quarter] ?? row.capacity);
    for(const [label,tint] of budgetSeries.map((series,i)=>[series.name,palette[i]])){
        const item=document.createElement('span');item.textContent=label;item.style.setProperty('--series',tint);legend.appendChild(item);
    }
    root.replaceChildren(svg,...(budgetSeries.length?[legend]:[]));
    const add=(kind,attrs,text)=>{const node=document.createElementNS(ns,kind);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);if(text!==undefined)node.textContent=text;svg.appendChild(node);return node;};
    const left=68,right=1025,top=25,bottom=248,width=right-left,height=bottom-top,n=data.rows.length;
    const axis=maximum=>{const step=Math.max(1,Math.ceil(maximum/4)),count=Math.max(1,Math.ceil(maximum/step));return {step,count,max:step*count};};
    const valueAxis=axis(Math.max(0,...data.rows.map(row=>Math.max(pools.reduce((sum,pool)=>sum+Number(pool[data.metric][row.quarter]||0),0),showCapacity?capacity(row):0)),...budgetSeries.flatMap(series=>series.points.map(point=>point.value||0))));
    const fmt=value=>Number(value).toLocaleString(data.locale,{minimumFractionDigits:1,maximumFractionDigits:1});
    const money=value=>Number(value).toLocaleString(data.locale,{minimumFractionDigits:2,maximumFractionDigits:2});
    const tick=value=>Number(value).toLocaleString(data.locale,{maximumFractionDigits:0});
    for(let i=0;i<=valueAxis.count;i++){
        const y=bottom-height*i/valueAxis.count;
        add('line',{x1:left,x2:right,y1:y,y2:y,stroke:'#dce2eb','stroke-width':.6});
        add('text',{x:left-8,y:y+4,'text-anchor':'end',fill:'currentColor','data-axis':data.metric},tick(valueAxis.step*i));
    }
    const middle=(top+bottom)/2;
    add('text',{transform:`translate(6 ${middle}) rotate(-90)`,'text-anchor':'middle',fill:'currentColor','data-axis-title':data.metric},data.valueLabel);
    let tip,menu;
    const closeTip=()=>{tip?.remove();tip=null;};
    const closeMenu=()=>{menu?.remove();menu=null;};
    const position=(node,x,y)=>{node.style.left=Math.max(8,Math.min(x,window.innerWidth-node.offsetWidth-8))+'px';node.style.top=Math.max(8,Math.min(y,window.innerHeight-node.offsetHeight-8))+'px';};
    const showTip=(lines,event)=>{
        closeTip();tip=document.createElement('div');tip.className='tip';tip.setAttribute('role','tooltip');
        for(const [text,tint] of lines){
            const row=document.createElement('div');
            if(tint){const swatch=document.createElement('span');swatch.className='pool-swatch';swatch.style.setProperty('--series',tint);swatch.setAttribute('aria-hidden','true');row.appendChild(swatch);}
            const label=document.createElement('span');label.textContent=text;row.appendChild(label);tip.appendChild(row);
        }
        root.appendChild(tip);position(tip,event.clientX+12,event.clientY+12);
    };
    const showMenu=(row,pool,x,y)=>{
        closeMenu();closeTip();menu=document.createElement('div');menu.className='context-menu';menu.setAttribute('role','menu');
        const heading=document.createElement('div');heading.className='context-menu-header';heading.textContent=pool.name+' - '+row.quarter;menu.appendChild(heading);
        const item=document.createElement('button');item.className='context-menu-item';item.type='button';item.setAttribute('role','menuitem');item.textContent=data.goTo;
        item.onclick=()=>{closeMenu();document.dispatchEvent(new CustomEvent('eppm-navigation-start',{}));setTriggerValue('selection',{quarter:row.quarter,pool_id:pool.pool_id,metric:data.metric,action:'planning'});};menu.appendChild(item);
        const details=document.createElement('button');details.className='context-menu-item';details.type='button';details.setAttribute('role','menuitem');details.textContent=data.poolDetails;
        details.onclick=()=>{closeMenu();document.dispatchEvent(new CustomEvent('eppm-navigation-start',{}));setTriggerValue('selection',{quarter:row.quarter,pool_id:pool.pool_id,metric:data.metric,action:'pool_details'});};menu.appendChild(details);
        const filter=document.createElement('button');filter.className='context-menu-item';filter.type='button';filter.setAttribute('role','menuitem');filter.textContent=data.filterPool;
        filter.onclick=()=>{closeMenu();setTriggerValue('selection',{quarter:row.quarter,pool_id:pool.pool_id,metric:data.metric,action:'filter_pool'});};menu.appendChild(filter);
        root.appendChild(menu);position(menu,x,y);item.focus({preventScroll:true});
    };
    const path=[];
    const first=Date.parse(data.start),last=Date.parse(data.end),today=Date.parse(data.today);
    const dateX=date=>left+width*(Date.parse(date)-first)/(last-first);
    data.rows.forEach((row,index)=>{
        const [year,quarter]=row.quarter.split('-Q').map(Number);
        const quarterStart=Date.UTC(year,(quarter-1)*3,1),quarterEnd=Date.UTC(year,quarter*3,1);
        const x=left+width*((quarterStart+quarterEnd)/2-first)/(last-first);
        let cumulative=0;
        for(const pool of pools){
            const value=Number(pool[data.metric][row.quarter]||0);if(value<=0)continue;
            const barHeight=height*value/valueAxis.max;cumulative+=value;
            const bar=add('rect',{x:x-width/n*.36,y:bottom-height*cumulative/valueAxis.max,width:width/n*.72,height:barHeight,
                fill:color(pool.pool_id),tabindex:0,role:'button','data-quarter':row.quarter,'data-pool-id':pool.pool_id,
                'aria-label':pool.name+', '+row.quarter+': '+data.valueLabel+' '+fmt(value)});
            bar.onpointermove=event=>{if(menu)return;
                showTip(data.metric==='overallocation'
                    ? [[row.quarter],[data.valueLabel],[(data.portfolioPeakLabel||data.totalLabel)+': '+fmt(row.value)+' FTE'],
                       [pool.name+': '+fmt(value)+' FTE',color(pool.pool_id)]]
                    : [[row.quarter],...(showCapacity?[[data.totalCapacityLabel+': '+fmt(capacity(row))+' FTE']]:[]),
                       [(data.portfolioPeakLabel||data.totalValueLabel)+': '+fmt(row.value)+' FTE'],
                       [pool.name+' — '+data.allocatedLabel+': '+fmt(value)+' FTE',color(pool.pool_id)],
                       [pool.name+' — '+data.availableLabel+': '+fmt(pool.available[row.quarter])+' FTE',color(pool.pool_id)]],event);};
            bar.onpointerleave=closeTip;
            bar.oncontextmenu=event=>{event.preventDefault();showMenu(row,pool,event.clientX,event.clientY);};
            bar.onkeydown=event=>{if(event.key==='ContextMenu'||event.key==='Enter'||(event.shiftKey&&event.key==='F10')){event.preventDefault();const rect=bar.getBoundingClientRect();showMenu(row,pool,rect.left,rect.top+20);}};
        }
        if(showCapacity)path.push((index?'L':'M')+x+','+(bottom-height*capacity(row)/valueAxis.max));
    });
    if(showCapacity)add('path',{d:path.join(' '),fill:'none',stroke:'#f10d0d','stroke-width':2,'stroke-dasharray':'6 4','pointer-events':'none'});
    for(let year=Number(data.start.slice(0,4));year<Number(data.end.slice(0,4));year++){
        add('text',{x:dateX(year+'-01-01'),y:bottom+22,'text-anchor':'middle',fill:'currentColor','data-year':year},String(year));
    }
    budgetSeries.forEach((series,index)=>{
        const segments=[];let connected=false;
        for(const point of series.points){
            if(point.value===null){connected=false;continue;}
            const x=dateX(point.date),y=bottom-height*point.value/valueAxis.max;
            segments.push((connected?'L':'M')+x+','+y);connected=true;
            const marker=add('circle',{cx:x,cy:y,r:4,fill:palette[index],tabindex:0,'data-budget-series':series.name,
                'aria-label':series.name+', '+point.date.slice(0,4)+': '+money(point.value)+' €'});
            const show=event=>showTip([[point.date.slice(0,4)],...budgetSeries.map(budget=>{
                const value=budget.points.find(item=>item.date===point.date)?.value;
                return [budget.name+': '+(value===null||value===undefined?'—':money(value)+' €')];
            })],event);
            marker.onpointermove=show;marker.onpointerleave=closeTip;
            marker.onfocus=()=>{const rect=marker.getBoundingClientRect();show({clientX:rect.left,clientY:rect.top});};
            marker.onblur=closeTip;
        }
        add('path',{d:segments.join(' '),fill:'none',stroke:palette[index],'stroke-width':2,'data-budget-series':series.name,'pointer-events':'none'});
    });
    if(today>=first&&today<=last){const x=left+width*(today-first)/(last-first);add('line',{x1:x,x2:x,y1:top,y2:bottom,stroke:'#23934c','stroke-width':2,'stroke-dasharray':'6 4','data-today':data.today,'pointer-events':'none'});}
    const hoverLine=add('line',{x1:left,x2:left,y1:top,y2:bottom,stroke:'#374151','stroke-width':3,
        'stroke-dasharray':'4 4','data-hover-line':data.metric,visibility:'hidden','pointer-events':'none'});
    const hoverEvent='eppm-resource-chart-hover';
    const receiveHover=event=>{
        const fraction=event.detail?.fraction;
        const visible=Number.isFinite(fraction)&&fraction>=0&&fraction<=1;
        hoverLine.setAttribute('visibility',visible?'visible':'hidden');
        if(visible){const x=left+fraction*width;hoverLine.setAttribute('x1',x);hoverLine.setAttribute('x2',x);}
    };
    const publishHover=fraction=>document.dispatchEvent(new CustomEvent(hoverEvent,{detail:{fraction}}));
    svg.onpointermove=event=>{
        const matrix=svg.getScreenCTM();if(!matrix)return;
        const point=new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());
        publishHover(point.x>=left&&point.x<=right&&point.y>=top&&point.y<=bottom?(point.x-left)/width:null);
    };
    svg.onpointerleave=()=>publishHover(null);
    document.addEventListener(hoverEvent,receiveHover);
    const outside=event=>{if(menu&&!event.composedPath().includes(menu))closeMenu();};
    const escape=event=>{if(event.key==='Escape'){closeMenu();closeTip();}};
    document.addEventListener('pointerdown',outside,true);document.addEventListener('keydown',escape,true);
    return()=>{publishHover(null);document.removeEventListener(hoverEvent,receiveHover);svg.onpointermove=null;svg.onpointerleave=null;
        closeMenu();closeTip();document.removeEventListener('pointerdown',outside,true);document.removeEventListener('keydown',escape,true);};
}
"""


def resource_chart(series: ResourceBreakdown, *, today: str, year: int,
                   labels: dict[str, str], locale: str, metric: str = 'overallocation',
                   on_pool_filter: Callable[[int], None] | None = None) -> dict | None:
    """Render per-pool stacks and return the selected pool/quarter for reauthorization."""
    component = st.components.v2.component('eppm_dashboard_resources',
        html='<div class="resource-chart"></div>', css=_CSS + CONTEXT_MENU_CSS, js=_JS)
    key = 'dashboard_resource_chart_' + metric

    def apply_filter() -> None:
        event = getattr(st.session_state.get(key), 'selection', None)
        if (on_pool_filter is not None and isinstance(event, dict)
                and event.get('action') == 'filter_pool' and event.get('metric') == metric
                and type(event.get('pool_id')) is int and isinstance(event.get('quarter'), str)
                and event['pool_id'] in {pool['pool_id'] for pool in series['pools']}):
            on_pool_filter(event['pool_id'])

    rows = [{'quarter': key, 'value': float(value), 'capacity': float(series['capacity'][key])}
            for key, value in sorted(series[metric].items()) if year - 2 <= int(key[:4]) <= year + 9]
    result = component(data={'rows': rows, 'pools': series.get('individual_pools', series['pools']), 'metric': metric,
                             'today': today, 'start': f'{year-2}-01-01', 'end': f'{year+10}-01-01',
                             'locale': locale, 'palette': PALETTE, **labels}, key=key,
                       on_selection_change=apply_filter, height='content')
    return getattr(result, 'selection', None)


def finance_chart(*, series: list[dict], today: str, year: int, locale: str,
                  title: str, value_label: str) -> None:
    """Render budget lines with the resource charts' date scale and hover guide."""
    component = st.components.v2.component('eppm_dashboard_resources',
        html='<div class="resource-chart"></div>', css=_CSS + CONTEXT_MENU_CSS, js=_JS)
    component(data={'rows': [], 'pools': [], 'metric': 'finance', 'budgetSeries': series,
                    'today': today, 'start': f'{year-2}-01-01', 'end': f'{year+10}-01-01',
                    'locale': locale, 'palette': PALETTE, 'title': title, 'valueLabel': value_label},
              key='dashboard_finance_chart', height='content')
