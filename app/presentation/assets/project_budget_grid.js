export default function({data, parentElement, setTriggerValue}) {
    const root = parentElement.querySelector('.project-budget');
    const node = (tag, text = '', className = '') => {
        const value = document.createElement(tag);
        value.textContent = text;
        value.className = className;
        return value;
    };
    let model = root.budgetModel;
    if (!model || model.token !== data.token) {
        model = {token: data.token, edits: new Map(), scroll: 0};
        root.budgetModel = model;
    }
    root.replaceChildren();
    const error = node('div', data.error || '', 'error');
    error.setAttribute('role', 'alert');
    const message = node('div', data.message || '', 'message');
    message.setAttribute('role', 'status');
    const viewport = node('div', '', 'viewport');
    viewport.tabIndex = 0;
    viewport.setAttribute('aria-label', 'Project budget, amounts in EUR');
    const table = node('table');
    table.setAttribute('aria-label', 'Project budget');
    const head = node('thead');
    const heading = node('tr');
    for (const label of ['OTP', 'Nature', 'Version', ...data.years.map(String)]) {
        const cell = node('th', label);
        cell.scope = 'col';
        heading.append(cell);
    }
    head.append(heading);
    const body = node('tbody');
    let previousCode = null;
    const inputs = [];
    const save = node('button', 'Save changes', 'primary');
    const cancel = node('button', 'Cancel');
    save.type = cancel.type = 'button';
    const controls = () => {save.disabled = cancel.disabled = model.edits.size === 0;};
    for (const row of data.rows) {
        const line = node('tr', '', previousCode === row.wbs ? '' : 'group-start');
        const code = node('th', previousCode === row.wbs ? '' : row.wbs);
        code.scope = 'row';
        line.append(code, node('td', row.label), node('td', row.version || '—'));
        previousCode = row.wbs;
        for (const year of data.years) {
            const cell = node('td');
            const original = row.amounts[String(year)] || '';
            if (data.can_edit && row.editable) {
                const input = node('input');
                const key = JSON.stringify([row.wbs, row.kind, year]);
                input.type = 'text';
                input.inputMode = 'decimal';
                input.setAttribute('aria-label', `${row.wbs} ${row.label} ${year}`);
                input.value = model.edits.get(key)?.amount ?? original;
                input.oninput = () => {
                    if (input.value === original) model.edits.delete(key);
                    else model.edits.set(key, {wbs: row.wbs, kind: row.kind, year, amount: input.value});
                    input.setCustomValidity('');
                    error.textContent = '';
                    controls();
                };
                inputs.push({input, original});
                cell.className = 'editable';
                cell.append(input);
            } else {
                cell.textContent = original;
                cell.className = 'readonly';
            }
            line.append(cell);
        }
        body.append(line);
    }
    table.append(head, body);
    viewport.append(table);
    viewport.onscroll = () => {model.scroll = viewport.scrollLeft;};
    save.onclick = () => {
        for (const {input} of inputs) {
            if (input.value.trim() && !/^-?\d+(?:[.,]\d{1,2})?$/.test(input.value.trim())) {
                input.setCustomValidity('Enter a monetary amount with at most two decimal places.');
                input.reportValidity();
                return;
            }
        }
        save.disabled = cancel.disabled = true;
        setTriggerValue('save', {revision: data.revision, edits: [...model.edits.values()], nonce: crypto.randomUUID()});
    };
    cancel.onclick = () => {
        model.edits.clear();
        for (const {input, original} of inputs) {input.value = original; input.setCustomValidity('');}
        controls();
    };
    controls();
    root.append(error, message, viewport);
    viewport.scrollLeft = model.scroll;
    if (data.can_edit) {
        const actions = node('div', '', 'actions');
        actions.append(cancel, save);
        root.append(actions);
    }
    return () => {viewport.onscroll = null;};
}
