"""Accessible quarterly resource chart with an authorized planning drill-through."""

import streamlit as st

from app.presentation.components.context_menu import CONTEXT_MENU_CSS


_CSS = """
.resource-chart {position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:16px;color:var(--st-text-color);font:12px var(--st-font)}
svg {grid-column:1;grid-row:1;display:block;width:100%;height:300px;overflow:visible}
.legend {grid-column:2;grid-row:1;display:flex;flex-direction:column;gap:16px;justify-content:center;margin:0}
.legend span::before {content:'';display:inline-block;width:22px;height:3px;background:var(--series);margin-right:7px;vertical-align:middle}
.tip {position:fixed;background:var(--st-background-color);color:var(--st-text-color);border:1px solid #cbd5e1;box-shadow:0 4px 12px #0002;padding:8px;border-radius:5px;white-space:pre-line;pointer-events:none;z-index:10001}
[data-quarter]:focus {outline:2px solid #C41039;outline-offset:-2px}
"""

_JS = r"""
export default function({data,parentElement,setTriggerValue}) {
    const root=parentElement.querySelector('.resource-chart'),ns='http://www.w3.org/2000/svg';
    const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 1100 300');svg.setAttribute('aria-label',data.title);
    const legend=document.createElement('div');legend.className='legend';
    for(const [label,color] of [[data.overallocationLabel,'#7851A9'],[data.capacityLabel,'#2780b9']]){
        const item=document.createElement('span');item.textContent=label;item.style.setProperty('--series',color);legend.appendChild(item);
    }
    root.replaceChildren(legend,svg);
    const add=(kind,attrs,text)=>{const node=document.createElementNS(ns,kind);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);if(text!==undefined)node.textContent=text;svg.appendChild(node);return node;};
    const left=68,right=1025,top=25,bottom=248,width=right-left,height=bottom-top,n=data.rows.length;
    const axis=maximum=>{const step=Math.max(1,Math.ceil(maximum/4)),count=Math.max(1,Math.ceil(maximum/step));return {step,count,max:step*count};};
    const overAxis=axis(Math.max(...data.rows.map(row=>row.overallocation))),capAxis=axis(Math.max(...data.rows.map(row=>row.capacity)));
    const maxOver=overAxis.max,maxCap=capAxis.max;
    const fmt=value=>Number(value).toLocaleString(data.locale,{minimumFractionDigits:1,maximumFractionDigits:1});
    const tick=value=>Number(value).toLocaleString(data.locale,{maximumFractionDigits:0});
    for(let i=0;i<=overAxis.count;i++){
        const y=bottom-height*i/overAxis.count;
        add('line',{x1:left,x2:right,y1:y,y2:y,stroke:'#dce2eb','stroke-width':.6});
        add('text',{x:left-8,y:y+4,'text-anchor':'end',fill:'currentColor','data-axis':'overallocation'},tick(overAxis.step*i));
    }
    for(let i=0;i<=capAxis.count;i++)add('text',{x:right+8,y:bottom-height*i/capAxis.count+4,fill:'currentColor','data-axis':'capacity'},tick(capAxis.step*i));
    add('text',{x:left,y:12,fill:'currentColor'},data.overallocationLabel);
    add('text',{x:right,y:12,'text-anchor':'end',fill:'currentColor'},data.capacityLabel);
    const path=[];
    data.rows.forEach((row,index)=>{
        const x=left+width*(index+.5)/n,barHeight=height*row.overallocation/maxOver;
        add('rect',{x:x-width/n*.36,y:bottom-barHeight,width:width/n*.72,height:barHeight,fill:'#7851A9'});
        path.push((index?'L':'M')+x+','+(bottom-height*row.capacity/maxCap));
        if(row.quarter.endsWith('Q1'))add('text',{x,y:bottom+22,'text-anchor':'middle',fill:'currentColor'},row.quarter.slice(0,4));
    });
    add('path',{d:path.join(' '),fill:'none',stroke:'#2780b9','stroke-width':2});
    const first=Date.parse(data.start),last=Date.parse(data.end),today=Date.parse(data.today);
    if(today>=first&&today<=last){const x=left+width*(today-first)/(last-first);add('line',{x1:x,x2:x,y1:top,y2:bottom,stroke:'#23934c','stroke-width':2,'stroke-dasharray':'6 4','data-today':data.today});}
    let tip,menu;
    const closeTip=()=>{tip?.remove();tip=null;};
    const closeMenu=()=>{menu?.remove();menu=null;};
    const position=(node,x,y)=>{node.style.left=Math.max(8,Math.min(x,window.innerWidth-node.offsetWidth-8))+'px';node.style.top=Math.max(8,Math.min(y,window.innerHeight-node.offsetHeight-8))+'px';};
    const showMenu=(row,x,y)=>{
        closeMenu();closeTip();menu=document.createElement('div');menu.className='context-menu';menu.setAttribute('role','menu');
        const heading=document.createElement('div');heading.className='context-menu-header';heading.textContent=row.quarter;menu.appendChild(heading);
        const item=document.createElement('button');item.className='context-menu-item';item.type='button';item.setAttribute('role','menuitem');item.textContent=data.goTo;item.disabled=row.overallocation<=0;
        item.onclick=()=>{closeMenu();setTriggerValue('quarter',row.quarter);};menu.appendChild(item);root.appendChild(menu);position(menu,x,y);item.focus({preventScroll:true});
    };
    data.rows.forEach((row,index)=>{
        const hit=add('rect',{x:left+width*index/n,y:top,width:width/n,height,fill:'transparent',tabindex:0,role:'button','data-quarter':row.quarter,'aria-label':row.quarter+': '+data.overallocationLabel+' '+fmt(row.overallocation)+', '+data.capacityLabel+' '+fmt(row.capacity)});
        hit.onpointermove=event=>{if(menu)return;if(!tip){tip=document.createElement('div');tip.className='tip';tip.setAttribute('role','tooltip');root.appendChild(tip);}tip.textContent=row.quarter+'\n'+data.overallocationLabel+': '+fmt(row.overallocation)+'\n'+data.capacityLabel+': '+fmt(row.capacity);position(tip,event.clientX+12,event.clientY+12);};
        hit.onpointerleave=closeTip;
        hit.oncontextmenu=event=>{event.preventDefault();showMenu(row,event.clientX,event.clientY);};
        hit.onkeydown=event=>{if(event.key==='ContextMenu'||event.key==='Enter'||(event.shiftKey&&event.key==='F10')){event.preventDefault();const rect=hit.getBoundingClientRect();showMenu(row,rect.left,rect.top+20);}};
    });
    const outside=event=>{if(menu&&!event.composedPath().includes(menu))closeMenu();};
    const escape=event=>{if(event.key==='Escape'){closeMenu();closeTip();}};
    document.addEventListener('pointerdown',outside,true);document.addEventListener('keydown',escape,true);
    return()=>{closeMenu();closeTip();document.removeEventListener('pointerdown',outside,true);document.removeEventListener('keydown',escape,true);};
}
"""


def resource_chart(series: dict[str, dict[str, float]], *, today: str, year: int,
                   labels: dict[str, str], locale: str) -> str | None:
    """Render aggregate-only series and return the selected quarter, never pool IDs."""
    component = st.components.v2.component('eppm_dashboard_resources',
        html='<div class="resource-chart"></div>', css=_CSS + CONTEXT_MENU_CSS, js=_JS)
    result = component(data={'rows': [{'quarter': key, 'overallocation': value,
                                      'capacity': series['capacity'][key]}
                                     for key, value in series['overallocation'].items()
                                     if year - 2 <= int(key[:4]) <= year + 9],
                             'today': today, 'start': f'{year-2}-01-01', 'end': f'{year+10}-01-01',
                             'locale': locale, **labels}, key='dashboard_resource_chart',
                       on_quarter_change=lambda: None, height='content')
    return getattr(result, 'quarter', None)
