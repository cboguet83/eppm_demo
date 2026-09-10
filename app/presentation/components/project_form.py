"""Prepared project forms with local inputs, tabs and custom-link editing."""

from collections.abc import Callable
from typing import Any

import streamlit as st

from app.presentation.components.modal_form import _CSS as _MODAL_CSS


_CSS = _MODAL_CSS + """
.tabs {display:flex; gap:6px; flex-wrap:wrap; margin:18px 0 12px;}
.tabs button {background:var(--st-secondary-background-color);color:var(--st-text-color);border-color:var(--st-border-color);}
.tabs button[aria-selected=true] {background:#C41039;color:white;border-color:#C41039;}
.links {margin-top:18px; border-top:1px solid var(--st-border-color);padding-top:12px;}
.link-row {display:grid;grid-template-columns:1fr 2fr auto;gap:8px;margin-bottom:8px;}
.help {opacity:.75;font-size:.9rem;}
[hidden] {display:none !important;}
select[multiple] {min-height:90px;}
.danger {margin-right:auto;}
@media(max-width:640px) {.link-row {grid-template-columns:1fr;} }
"""

_JS = r"""
export default function({data, parentElement, setTriggerValue}) {
    const dialog = parentElement.querySelector('dialog');
    if (!data) {if (dialog.open) dialog.close(); parentElement.projectDraft = null; return;}
    const previous = parentElement.projectDraft;
    const draft = previous?.token === data.token ? previous : {token:data.token, tab:null, dirty:new Set()};
    parentElement.projectDraft = draft;
    const element = (tag, text) => {const node=document.createElement(tag); if(text!=null) node.textContent=text; return node;};
    const content = document.createDocumentFragment();
    const title = element('h2',data.title); title.id='project-title'; content.append(title);
    const form = element('form'); form.noValidate=true;
    const controls = new Map(), panels = new Map(), tabButtons = new Map();
    let pending=false;
    const core = element('div'); core.className='fields'; form.append(core);
    const tabbar = element('div'); tabbar.className='tabs'; tabbar.setAttribute('role','tablist');
    const selectTab = label => {
        draft.tab=label;
        for(const [name,panel] of panels) panel.hidden=name!==label;
        for(const [name,button] of tabButtons) {button.setAttribute('aria-selected',String(name===label)); button.tabIndex=name===label?0:-1;}
    };
    for(const label of data.tabs) {
        const button=element('button',label); button.type='button'; button.setAttribute('role','tab');
        button.onclick=()=>selectTab(label); tabbar.append(button); tabButtons.set(label,button);
        const panel=element('div');panel.className='fields'; panel.setAttribute('role','tabpanel');
        panels.set(label,panel);
    }
    form.append(tabbar,...panels.values());
    tabbar.onkeydown=event=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
        const labels=[...panels.keys()];let i=labels.indexOf(draft.tab);
        i=event.key==='Home'?0:event.key==='End'?labels.length-1:(i+(event.key==='ArrowRight'?1:-1)+labels.length)%labels.length;
        event.preventDefault();selectTab(labels[i]);tabButtons.get(labels[i]).focus();
    };
    const read = () => Object.fromEntries([...controls].map(([key,{field,input}])=>{
        let value=input.value;
        if(field.kind==='number') value=value===''?null:Number(value);
        if(field.kind==='multi') value=[...input.selectedOptions].map(option=>option.value);
        if(field.kind==='tags') value=value.split('\n').map(item=>item.trim()).filter(Boolean);
        return [key,value];
    }));
    const emit = kind => {
        if(pending) return;
        pending=true; form.setAttribute('aria-busy','true');
        const values=read(), links=[...linkRows.children].map(row=>({alias:row.querySelector('[name=alias]').value,url:row.querySelector('[name=url]').value}));
        for(const control of form.querySelectorAll('input,textarea,select,button')) control.disabled=true;
        setTriggerValue('action',{kind,token:data.token,values,links,dirty:[...draft.dirty]});
    };
    for(const field of data.fields) {
        const label=element('label');if(!field.tab) label.className='compact';
        label.append(element('span',field.label));
        const input=element(['select','multi'].includes(field.kind)?'select':field.kind==='tags'?'textarea':'input');
        input.name=field.key;input.setAttribute('aria-label',field.label);
        if(['select','multi'].includes(field.kind)) {
            input.multiple=field.kind==='multi';
            for(const [value,text] of field.options) {
                const option=element('option',text);option.value=value;
                if(input.multiple) option.selected=(data.values[field.key]||[]).includes(value);
                input.append(option);
            }
        } else if(field.kind!=='tags') {input.type=field.kind; if(field.kind==='number') input.step='any';}
        if(field.kind!=='multi') input.value=field.kind==='tags'?(data.values[field.key]||[]).join('\n'):(data.values[field.key]??'');
        input.disabled=Boolean(field.disabled);
        input.oninput=()=>draft.dirty.add(field.key);
        input.onchange=()=>{draft.dirty.add(field.key);if(field.key==='project_type_id') emit('type');};
        label.append(input);if(field.kind==='tags') label.append(element('small','One tag per line'));
        (field.tab?panels.get(field.tab):core).append(label);controls.set(field.key,{field,input});
    }
    for(const [label,message] of Object.entries(data.messages||{})) panels.get(label)?.append(element('p',message));
    selectTab(panels.has(draft.tab)?draft.tab:data.tabs[0]);
    const links=element('section');links.className='links';links.append(element('h3',data.links_label));
    const linkRows=element('div');links.append(linkRows);
    const addLink = value => {
        const row=element('div');row.className='link-row';
        for(const [name,label] of [['alias',data.alias_label],['url','URL']]) {
            const input=element('input');input.name=name;input.value=value[name]||'';input.placeholder=label;
            input.setAttribute('aria-label',label);input.disabled=!data.can_save;row.append(input);
        }
        const remove=element('button','Remove');remove.type='button';remove.disabled=!data.can_save;
        remove.onclick=()=>row.remove();row.append(remove);linkRows.append(row);
    };
    data.links.forEach(addLink);
    const add=element('button','Add link');add.type='button';add.disabled=!data.can_save;add.onclick=()=>addLink({});links.append(add);form.append(links);
    if(data.error) {const error=element('p',data.error);error.className='error';error.setAttribute('role','alert');form.append(error);}
    const buttons=element('div');buttons.className='buttons';
    const cancel=element('button',data.cancel);cancel.type='button';
    const submit=element('button',data.submit);submit.type='submit';submit.disabled=!data.can_save;
    const confirm=element('div');confirm.hidden=true;
    if(data.can_delete) {
        const remove=element('button','Delete project');remove.type='button';remove.className='danger';
        remove.onclick=()=>{confirm.hidden=false;buttons.hidden=true;};buttons.append(remove);
        confirm.append(element('p','Delete this project and its tasks, dependencies, contacts and log entries?'));
        const yes=element('button','Confirm delete project');yes.type='button';yes.onclick=()=>emit('delete');
        const no=element('button','Cancel deletion');no.type='button';no.onclick=()=>{confirm.hidden=true;buttons.hidden=false;};confirm.append(no,yes);
    }
    const dismiss=()=>{if(!pending){dialog.close();setTriggerValue('action',{kind:'cancel',token:data.token});}};
    cancel.onclick=dismiss;buttons.append(cancel,submit);form.append(buttons,confirm);
    form.onsubmit=event=>{event.preventDefault();if(data.can_save) emit('save');};
    content.append(form);
    // Build all controls synchronously before replacing or revealing the form.
    dialog.replaceChildren(content);dialog.className='wide';
    dialog.oncancel=event=>{event.preventDefault();dismiss();};
    dialog.onclick=event=>{
        const r=dialog.getBoundingClientRect();
        if(event.target===dialog&&(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)) dismiss();
    };
    if(!dialog.open) dialog.showModal();
}
"""


def project_form(data: dict[str, Any] | None, *, on_action: Callable[[], None]) -> None:
    """Mount prepared JSON display data; only explicit actions reach the server.

    Any represents the dynamic, validated project-property component boundary.
    """
    component = st.components.v2.component(
        "eppm_project_form", html='<dialog aria-labelledby="project-title"></dialog>', js=_JS, css=_CSS,
    )
    component(data=data, key="portfolio_project_form", height=0, on_action_change=on_action)
