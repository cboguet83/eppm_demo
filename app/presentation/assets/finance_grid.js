export default function({data, parentElement, setTriggerValue}) {
    const root = parentElement.querySelector('.finance');
    // CCv2 may render new data before disposing the previous invocation.
    // Release its document listeners before replacing the model and dialog.
    root.financeCleanup?.();
    const labels = data.labels;
    const t = (key, values={}) => Object.entries(values).reduce((s,[k,v])=>s.replaceAll('{'+k+'}',String(v)), labels[key] || key);
    const element = (tag,text='',cls='') => {const el=document.createElement(tag);el.textContent=text;el.className=cls;return el;};
    const clone = rows => rows.map(row=>({code:row.code,amounts:{...row.amounts}}));
    const signature = data.token;
    let model = root.financeModel;
    if (!model || model.token !== signature) {
        model = {token:signature,rows:clone(data.rows),dirty:false,scrollTop:0,scrollLeft:550,preview:null,
                 focus:null,selection:null};
        root.financeModel=model;
    }
    let busy=false, disposed=false, frame=0;
    const editable = () => data.can_edit;
    const populated = row => row.code.trim() || Object.values(row.amounts).some(value=>value.trim());
    const padRows = () => {
        const last=model.rows.findLastIndex(populated);
        const size=Math.min(10000,Math.max(25,last+11));
        while(model.rows.length<size) model.rows.push({code:'',amounts:{}});
        model.rows.length=Math.max(size,last+1);
    };
    padRows();
    const years = Array.from({length:20},(_,i)=>data.year-5+i);
    const historical = new Map(data.rows.map(row=>[row.code,Object.fromEntries(Object.entries(row.amounts).filter(([year])=>Number(year)<data.year))]));
    const descriptionFor=code=>Object.hasOwn(data.catalog,code)?data.catalog[code]:'';
    const emit = payload => {
        if(busy) return;
        busy=true; updateControls();
        setTriggerValue('action',{...payload,token:data.token,nonce:crypto.randomUUID()});
    };
    const payload = () => model.rows.map(row=>({code:row.code,amounts:Object.fromEntries(
        Object.entries(row.amounts).filter(([year])=>Number(year)>=data.year && Number(year)<data.year+15))}));
    const error=element('div',data.error || '', 'error');error.setAttribute('role','alert');
    const message=element('div',data.message || '', 'message');message.setAttribute('role','status');
    const toolbar=element('div','','toolbar');
    const versionSelect=element('select');versionSelect.setAttribute('aria-label',t('version'));
    if(!data.versions.length) {const option=element('option',t('empty_plan'));option.value='';versionSelect.append(option);}
    for(const version of data.versions) {
        const option=element('option',String(version.number));
        option.value=String(version.id);versionSelect.append(option);
    }
    versionSelect.value=String(data.selected?.id || '');
    const button=(label,handler) => {const el=element('button',t(label));el.type='button';el.onclick=handler;return el;};
    const modal=element('dialog');
    const showDialog=(title,body,actionLabel,action) => {
        modal.replaceChildren(element('h3',title),...body);
        const actions=element('div','','toolbar');
        actions.append(button('cancel',()=>modal.close()),button(actionLabel,()=>{modal.close();action();}));
        modal.append(actions);modal.showModal();
    };
    const discardThen=action => {
        if(!model.dirty) {action();return;}
        showDialog(t('unsaved'),[element('p',t('discard_warning'))],'discard',action);
    };
    versionSelect.onchange=()=>{
        const id=Number(versionSelect.value);versionSelect.value=String(data.selected?.id || '');
        discardThen(()=>emit({kind:'select',snapshot_id:id}));
    };
    const saveDialog=()=>{
        error.textContent='';
        if(!validateRows()) return;
        const name=element('input');name.maxLength=120;name.value=data.selected?.name || '';name.setAttribute('aria-label',t('version_name'));
        const nameLabel=element('label',t('version_name'));nameLabel.append(name);
        const status=element('select');status.setAttribute('aria-label',t('status'));
        const placeholder=element('option',t('choose_status'));placeholder.value='';placeholder.disabled=true;placeholder.selected=true;status.append(placeholder);
        for(const value of ['Draft','Proposed','Approved','Canceled']) {const option=element('option',t(value));option.value=value;status.append(option);}
        const statusLabel=element('label',t('status'));statusLabel.append(status);
        modal.replaceChildren(element('h3',t('save_confirm')),element('p',t('save_notice')),nameLabel,statusLabel);
        const validation=element('div','','error');validation.setAttribute('role','alert');modal.append(validation);
        const actions=element('div','','toolbar');
        actions.append(button('cancel',()=>modal.close()),button('confirm',()=>{
            if(!name.value.trim()) {validation.textContent=t('name_required');return;}
            if(!status.value) {validation.textContent=t('choose_status');return;}
            modal.close();emit({kind:'save',rows:payload(),status:status.value,name:name.value,year:data.year});
        }));modal.append(actions);modal.showModal();
    };
    const save=button('save',saveDialog);
    const cancel=button('reload',()=>discardThen(()=>emit({kind:'reload'})));
    const cancelVersion=button('cancel_version',()=>discardThen(()=>
        showDialog(t('cancel_version'),[element('p',t('cancel_notice'))],'confirm',()=>emit({kind:'cancel_version'}))));
    const file=element('input');file.type='file';file.accept='.csv,text/csv';file.hidden=true;
    const upload=button('import',()=>file.click());
    file.onchange=async()=>{
        const chosen=file.files[0];if(!chosen) return;
        if(chosen.size>2097152) {error.textContent=t('file_error');file.value='';return;}
        try {
            const content=new TextDecoder('utf-8',{fatal:true}).decode(await chosen.arrayBuffer());
            if(!disposed) emit({kind:'import',content,name:chosen.name,year:data.year});
        } catch {error.textContent=t('file_error');}
        file.value='';
    };
    const download=button('export',()=>{
        const go=()=>{const a=element('a');a.href=data.download_url;a.download='budget.csv';root.append(a);a.click();a.remove();};
        if(model.dirty) showDialog(t('export'),[element('p',t('export_saved'))],'export',go);else go();
    });
    toolbar.append(versionSelect,save,cancel,upload,download,cancelVersion,file);
    const metadata=element('p', data.selected ? t('metadata',{author:data.selected.author,
        date:new Date(data.selected.created_at*1000).toLocaleString(),status:t(data.selected.status)}) : t('empty_hint'),'muted');
    const viewport=element('div','','viewport');viewport.setAttribute('aria-label',t('grid'));viewport.tabIndex=0;
    const table=element('table');table.setAttribute('aria-label',t('grid'));
    const cols=element('colgroup');
    [36,180,220,...years.map(()=>110)].forEach(width=>{const col=element('col');col.style.width=width+'px';cols.append(col);});
    const head=element('thead'),header=element('tr');
    [element('th','','frozen remove'),element('th',t('code'),'frozen code'),element('th',t('description'),'frozen description'),
        ...years.map(year=>element('th',String(year),'year'+(year<data.year?' past':'')+(year===data.year?' current':'')))].forEach(th=>header.append(th));
    head.append(header);const body=element('tbody');table.append(cols,head,body);viewport.append(table);
    const footer=element('div','','footer'),count=element('span'),dirty=element('span');footer.append(count,dirty);
    const nameDisplay=element('p',data.selected?.name || '', 'plan-name');
    root.replaceChildren(toolbar,nameDisplay,metadata,error,message,viewport,footer,modal);
    const historyFor=code=>historical.get(code) || {};
    const hasHistory=code=>Object.keys(historyFor(code)).length>0;
    const valueAt=(row,col)=>col===0?row.code:col===1?descriptionFor(row.code):
        ((years[col-2]<data.year ? historyFor(row.code) : row.amounts)[years[col-2]] || '');
    function updateControls() {
        save.disabled=upload.disabled=!editable() || busy;
        cancel.disabled=versionSelect.disabled=busy;
        download.disabled=!data.selected || busy;
        cancelVersion.disabled=!editable() || !data.selected || data.selected.status==='Canceled' || busy;
        count.textContent=t('row_count',{count:model.rows.filter(row=>row.code.trim()).length});dirty.textContent=model.dirty?t('unsaved'):t('saved');
    }
    function validateRows(rows=model.rows) {
        const codes=new Set();
        for(let i=0;i<rows.length;i++) {
            const row=rows[i],code=row.code.trim();
            if(!populated(row)) continue;
            if(!code) {error.textContent=t('missing_code',{row:i+1});return false;}
            if(!/^#?[A-Za-z0-9._-]{1,128}$/.test(code)) {error.textContent=t('invalid_code',{row:i+1});return false;}
            if(codes.has(code)) {error.textContent=t('duplicate_code',{row:i+1,code});return false;}
            codes.add(code);
            for(const [year,amount] of Object.entries(row.amounts)) if(Number(year)>=data.year && amount.trim() && !/^[0-9]+([.,][0-9]{1,2})?$/.test(amount.trim())) {
                error.textContent=t('invalid_amount',{row:i+1,year});return false;
            }
        }
        return true;
    }
    function renderRows() {
        const activeCell=root.getRootNode().activeElement?.closest?.('td[data-row][data-col]');
        const focus=activeCell && body.contains(activeCell)?{row:activeCell.dataset.row,col:activeCell.dataset.col}:null;
        const first=Math.max(0,Math.floor(viewport.scrollTop/36)-4),last=Math.min(model.rows.length,first+28);
        const fragment=document.createDocumentFragment();
        const spacer=height=>{const tr=element('tr','','spacer'),td=element('td');td.colSpan=23;td.style.height=height+'px';tr.append(td);fragment.append(tr);};
        spacer(first*36);
        for(let index=first;index<last;index++) {
            const row=model.rows[index],tr=element('tr','',row.code.trim()?'':'unused');tr.dataset.row=String(index);
            const remove=element('td','','frozen remove');
            const removeButton=button('remove',()=>{
                if(hasHistory(row.code)) row.amounts={...historyFor(row.code)};else model.rows.splice(index,1);
                padRows();
                model.dirty=true;renderRows();updateControls();
            });removeButton.textContent='×';removeButton.setAttribute('aria-label',t('remove_row',{row:index+1}));
            removeButton.disabled=!editable() || !populated(row);remove.append(removeButton);tr.append(remove);
            for(let column=0;column<22;column++) {
                const year=years[column-2],locked=column===1 || (column>=2 && year<data.year);
                const td=element('td','',''+(column===0?'frozen code':column===1?'frozen description':'year'+(locked?' past':'')));
                td.dataset.col=String(column);td.dataset.row=String(index);
                if(model.selection && index>=Math.min(model.selection.start.row,model.selection.end.row) && index<=Math.max(model.selection.start.row,model.selection.end.row)
                    && column>=Math.min(model.selection.start.col,model.selection.end.col) && column<=Math.max(model.selection.start.col,model.selection.end.col)) td.classList.add('selected-cell');
                td.onmousedown=event=>{
                    const point={row:index,col:column};
                    if(event.shiftKey && model.selection) {model.selection.end=point;event.preventDefault();renderRows();}
                    else model.selection={start:point,end:point};
                };
                const value=valueAt(row,column);
                if(locked || !editable()) {td.textContent=value;td.title=value;}
                else {
                    const originalCode=row.code;
                    const input=element('input');input.value=value;input.setAttribute('aria-label',`${index+1} ${column===0?t('code'):year}`);
                    input.inputMode=column===0?'text':'decimal';input.maxLength=column===0?129:24;
                    input.onfocus=()=>{model.focus={row:index,col:column};model.selection={start:model.focus,end:model.focus};};
                    input.oninput=()=>{
                        if(column===0) {row.code=input.value;const desc=tr.querySelector('.description');desc.textContent=descriptionFor(row.code);desc.title=desc.textContent || t('unmatched');}
                        else row.amounts[year]=input.value;
                        tr.classList.toggle('unused',!row.code.trim());
                        padRows();const trailing=body.lastElementChild?.firstElementChild;
                        if(trailing) trailing.style.height=Math.max(0,model.rows.length-last)*36+'px';
                        removeButton.disabled=!populated(row);model.dirty=true;updateControls();
                    };
                    input.onchange=()=>{if(column===0) {
                        row.code=row.code.trim();
                        if(row.code!==originalCode && hasHistory(originalCode) && !model.rows.some(item=>item.code===originalCode))
                            model.rows.splice(model.rows.findLastIndex(populated)+1,0,{code:originalCode,amounts:{...historyFor(originalCode)}});
                        padRows();renderRows();updateControls();
                    }};
                    input.onkeydown=event=>navigateCell(event,index,column);
                    td.append(input);
                }
                if(column===1 && row.code.trim() && !Object.hasOwn(data.catalog,row.code)) {td.textContent=t('unmatched');td.title=t('unmatched');td.classList.add('muted');}
                tr.append(td);
            }
            fragment.append(tr);
        }
        spacer(Math.max(0,model.rows.length-last)*36);body.replaceChildren(fragment);
        if(focus) body.querySelector(`td[data-row="${focus.row}"][data-col="${focus.col}"] input`)?.focus({preventScroll:true});
    }
    function navigateCell(event,row,col) {
        if(!['Tab','Enter'].includes(event.key)) return;
        const columns=[0,...Array.from({length:15},(_,i)=>i+7)];
        let nextRow=row,nextCol=col;
        const direction=event.shiftKey?-1:1;
        if(event.key==='Enter') nextRow+=direction;
        else {
            const index=columns.indexOf(col)+direction;
            if(index<0) {nextRow--;nextCol=21;}
            else if(index>=columns.length) {nextRow++;nextCol=0;}
            else nextCol=columns[index];
        }
        if(nextRow<0 || nextRow>=10000) return;
        event.preventDefault();event.currentTarget.blur();
        while(model.rows.length<=nextRow) model.rows.push({code:'',amounts:{}});
        const top=nextRow*36;
        if(top<viewport.scrollTop) viewport.scrollTop=top;
        else if(top+80>viewport.scrollTop+viewport.clientHeight) viewport.scrollTop=top+80-viewport.clientHeight;
        renderRows();
        const input=body.querySelector(`td[data-row="${nextRow}"][data-col="${nextCol}"] input`);
        input?.focus({preventScroll:true});
        if(nextCol>=7) {
            const left=436+(nextCol-2)*110;
            if(left<viewport.scrollLeft+436) viewport.scrollLeft=left-436;
            else if(left+110>viewport.scrollLeft+viewport.clientWidth) viewport.scrollLeft=left+110-viewport.clientWidth;
        }
    }
    const onPaste=event=>{
        const raw=event.clipboardData?.getData('text/plain');if(!raw || !raw.includes('\t') && !raw.includes('\n')) return;
        event.preventDefault();if(!editable()) return;
        if(raw.length>2097152) {error.textContent=t('file_error');return;}
        const lines=raw.replaceAll('\r\n','\n').replace(/\n$/,'').split('\n').map(line=>line.split('\t'));
        const start=model.selection?.start || model.focus || {row:0,col:0},draft=clone(model.rows);
        if(start.row+lines.length>10000) {error.textContent=t('row_limit');return;}
        for(let i=0;i<lines.length;i++) {
            const index=start.row+i;while(draft.length<=index) draft.push({code:'',amounts:{}});
            // A 17-column row is the exported current/future shape; a 22-column row is the full visible grid.
            const full=start.col===0 && [17,22].includes(lines[i].length);
            for(let c=0;c<lines[i].length;c++) {
                const col=full && lines[i].length===17 && c>=2?c+5:start.col+c;
                if(col>=22) {error.textContent=t('paste_bounds');return;}
                const value=lines[i][c];
                if(col===1) {if(full) continue;error.textContent=t('paste_locked');return;}
                if(col>=2 && years[col-2]<data.year) {
                    if(full && value===(historyFor(draft[index].code)[years[col-2]] || '')) continue;
                    error.textContent=t('paste_locked');return;
                }
                if(col===0) draft[index].code=value;else draft[index].amounts[years[col-2]]=value;
            }
        }
        if(!validateRows(draft)) return;
        model.rows=draft;padRows();model.dirty=true;error.textContent='';renderRows();updateControls();
    };
    const onCopy=event=>{
        if(!model.selection) return;
        const {start,end}=model.selection;
        if(start.row===end.row && start.col===end.col && event.target.tagName==='INPUT') return;
        const lines=[];
        for(let r=Math.min(start.row,end.row);r<=Math.max(start.row,end.row);r++) {
            if(!model.rows[r]) break;
            const values=[];for(let c=Math.min(start.col,end.col);c<=Math.max(start.col,end.col);c++) values.push(valueAt(model.rows[r],c));
            lines.push(values.join('\t'));
        }
        event.clipboardData.setData('text/plain',lines.join('\n'));event.preventDefault();
    };
    const beforeUnload=event=>{if(!disposed && root.isConnected && model.dirty){event.preventDefault();event.returnValue='';}};
    const sidebarClick=event=>{
        if(disposed || !root.isConnected || root.financeModel!==model || !model.dirty
            || !event.target.closest?.('[data-testid="stSidebar"]')) return;
        event.preventDefault();event.stopImmediatePropagation();
        showDialog(t('unsaved'),[element('p',t('discard_warning'))],'discard',()=>{
            model.dirty=false;event.target.click();
        });
    };
    viewport.addEventListener('paste',onPaste);viewport.addEventListener('copy',onCopy);window.addEventListener('beforeunload',beforeUnload);
    document.addEventListener('click',sidebarClick,true);
    viewport.onscroll=()=>{
        const vertical=model.scrollTop!==viewport.scrollTop;model.scrollTop=viewport.scrollTop;model.scrollLeft=viewport.scrollLeft;
        if(vertical && !frame) frame=requestAnimationFrame(()=>{frame=0;renderRows();});
    };
    viewport.scrollTop=model.scrollTop;viewport.scrollLeft=model.scrollLeft;renderRows();updateControls();
    if(data.preview && model.preview!==data.preview.id) {
        model.preview=data.preview.id;
        showDialog(t('import_preview'),[element('p','⚠ '+t('replace_warning'),'warning'),element('p',t('row_count',{count:data.preview.rows.length}))],'continue',()=>{
            const rows=clone(data.preview.rows),codes=new Set(rows.map(row=>row.code));
            for(const [code,amounts] of historical) if(Object.keys(amounts).length && !codes.has(code)) rows.push({code,amounts:{...amounts}});
            model.rows=rows;padRows();model.dirty=true;renderRows();updateControls();saveDialog();
        });
    }
    const cleanup=()=>{
        disposed=true;cancelAnimationFrame(frame);viewport.removeEventListener('paste',onPaste);viewport.removeEventListener('copy',onCopy);
        window.removeEventListener('beforeunload',beforeUnload);viewport.onscroll=null;
        document.removeEventListener('click',sidebarClick,true);
        if(modal.open) modal.close();
        if(root.financeCleanup===cleanup) delete root.financeCleanup;
    };
    root.financeCleanup=cleanup;
    return cleanup;
}
