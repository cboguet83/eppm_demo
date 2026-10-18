"""Five-row virtual viewport with bounded, lazily requested project pages."""

from collections.abc import Callable

import streamlit as st


_CSS = """
.viewport {height:210px;overflow:auto;overflow-anchor:none;border:1px solid #d8dde5;border-radius:6px;font:14px var(--st-font);color:var(--st-text-color)}
table {width:100%;table-layout:fixed;border-spacing:0}
th,td {box-sizing:border-box;height:35px;padding:0 10px;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-bottom:1px solid #e5e8ed}
th {position:sticky;top:0;background:var(--st-secondary-background-color);z-index:1;font-weight:500}
.spacer td {padding:0;border:0}.loading {color:#777}
tr[data-project-id] {cursor:pointer}
tr[data-project-id]:hover,tr[aria-selected=true] {background:#C4103910}
tr[data-project-id]:focus {outline:2px solid #C41039;outline-offset:-2px}
"""

_JS = r"""
export default function({data,parentElement,setStateValue,setTriggerValue}) {
    const root=parentElement.querySelector('.viewport');
    const model=root.dashboardRows || {token:null,pages:new Map(),top:0,pending:null};
    root.dashboardRows=model;
    if(model.token!==data.token){model.token=data.token;model.pages.clear();model.top=0;model.pending=null;}
    model.pages.set(data.offset,data.rows);
    if(model.pending===data.offset)model.pending=null;
    while(model.pages.size>6)model.pages.delete(model.pages.keys().next().value);
    const table=document.createElement('table'),head=document.createElement('thead'),header=document.createElement('tr'),body=document.createElement('tbody');
    for(const label of data.columns){const th=document.createElement('th');th.textContent=label;header.appendChild(th);}
    head.appendChild(header);table.append(head,body);root.replaceChildren(table);
    const request=offset=>{if(model.pending!==null||model.pages.has(offset))return;model.pending=offset;setStateValue('request',{offset,token:data.token});};
    const spacer=count=>{if(!count)return;const tr=document.createElement('tr'),td=document.createElement('td');tr.className='spacer';td.colSpan=4;td.style.height=(count*35)+'px';tr.appendChild(td);body.appendChild(tr);};
    const draw=()=>{
        const first=Math.max(0,Math.floor(model.top/35)-3),last=Math.min(data.total,first+12);
        if(data.total)request(Math.floor(Math.min(data.total-1,Math.floor(model.top/35))/50)*50);
        body.replaceChildren();spacer(first);
        for(let index=first;index<last;index++){
            const offset=Math.floor(index/50)*50,row=model.pages.get(offset)?.[index-offset],tr=document.createElement('tr');
            if(row){
                tr.dataset.projectId=row.id;tr.tabIndex=0;tr.setAttribute('aria-selected',String(row.id===data.selected));
                const select=()=>setTriggerValue('project',{id:row.id,token:data.selection_token,nonce:crypto.randomUUID()});
                tr.onclick=select;
                tr.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select();}};
            }
            for(let col=0;col<4;col++){const td=document.createElement('td');td.textContent=row?row.values[col]:(col===0?data.loading:'');td.title=td.textContent;if(!row)td.className='loading';tr.appendChild(td);}
            body.appendChild(tr);if(!row)request(offset);
        }
        spacer(data.total-last);
        const next=Math.floor((last+15)/50)*50;
        if(next<data.total)request(next);
    };
    let frame;
    root.onscroll=()=>{model.top=root.scrollTop;if(!frame)frame=requestAnimationFrame(()=>{frame=null;draw();});};
    draw();root.scrollTop=model.top;
    return()=>{root.onscroll=null;if(frame)cancelAnimationFrame(frame);};
}
"""


def dashboard_table(rows: list[dict], columns: list[str], total: int, offset: int,
                    token: str, loading: str, selected: int | None,
                    selection_token: str,
                    on_project: Callable[[], None]) -> None:
    """Send only one fifty-row page; scrolling retains a bounded browser cache."""
    component = st.components.v2.component('eppm_dashboard_table', html='<div class="viewport" tabindex="0"></div>', css=_CSS, js=_JS)
    component(data={'rows': rows, 'columns': columns, 'total': total, 'offset': offset,
                    'token': token, 'loading': loading, 'selected': selected,
                    'selection_token': selection_token}, key='dashboard_project_table',
              on_request_change=lambda: None, on_project_change=on_project, height='content')
