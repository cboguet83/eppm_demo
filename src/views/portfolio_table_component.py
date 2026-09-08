"""Streamlit Components v2 project table used by the portfolio overview."""

from typing import Any

import streamlit as st


_TABLE_HTML = '<div id="portfolio-project-table" class="portfolio-project-table"></div>'

_TABLE_CSS = r"""
.portfolio-project-table {
    color: var(--st-text-color);
    font-family: var(--st-font);
    font-size: 0.875rem;
    position: relative;
}
.table-scroll {
    border: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
    border-radius: 0.5rem;
    max-height: 32rem;
    overflow: auto;
}
table {
    border-collapse: separate;
    border-spacing: 0;
    min-width: 100%;
    width: max-content;
}
th, td {
    border-bottom: 1px solid color-mix(in srgb, var(--st-text-color) 12%, transparent);
    padding: 0.58rem 0.7rem;
    text-align: left;
    white-space: nowrap;
}
th {
    background: var(--st-secondary-background-color);
    font-weight: 600;
    position: sticky;
    top: 0;
    z-index: 2;
}
tbody tr {
    cursor: pointer;
    outline: none;
}
tbody tr:hover, tbody tr:focus-visible {
    background: color-mix(in srgb, var(--st-primary-color) 10%, transparent);
}
tbody tr.selected {
    background: color-mix(in srgb, var(--st-primary-color) 16%, transparent);
    box-shadow: inset 3px 0 0 var(--st-primary-color);
}
.header-content {
    align-items: center;
    display: flex;
    gap: 0.35rem;
    justify-content: space-between;
}
.filter-button {
    align-items: center;
    background: transparent;
    border: 0;
    border-radius: 0.25rem;
    color: var(--st-text-color);
    cursor: pointer;
    display: inline-flex;
    font: inherit;
    height: 1.6rem;
    justify-content: center;
    opacity: 0.62;
    width: 1.6rem;
}
.filter-button:hover, .filter-button.active {
    background: color-mix(in srgb, var(--st-primary-color) 14%, transparent);
    color: var(--st-primary-color);
    opacity: 1;
}
.filter-menu {
    background: var(--st-background-color);
    border: 1px solid color-mix(in srgb, var(--st-text-color) 22%, transparent);
    border-radius: 0.5rem;
    box-shadow: 0 0.5rem 1.5rem color-mix(in srgb, black 20%, transparent);
    min-width: 16rem;
    padding: 0.65rem;
    position: fixed;
    z-index: 10000;
}
.filter-menu input[type="search"] {
    background: var(--st-background-color);
    border: 1px solid color-mix(in srgb, var(--st-text-color) 24%, transparent);
    border-radius: 0.3rem;
    box-sizing: border-box;
    color: var(--st-text-color);
    margin-bottom: 0.5rem;
    padding: 0.45rem 0.55rem;
    width: 100%;
}
.filter-stats {
    background: var(--st-secondary-background-color);
    border-radius: 0.35rem;
    display: grid;
    gap: 0.25rem 0.7rem;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    margin-bottom: 0.5rem;
    padding: 0.5rem;
}
.filter-stat {
    display: flex;
    gap: 0.35rem;
    justify-content: space-between;
}
.filter-stat-label {
    color: color-mix(in srgb, var(--st-text-color) 65%, transparent);
}
.filter-stat-value {
    font-weight: 650;
    overflow: hidden;
    text-overflow: ellipsis;
}
.filter-actions, .sort-actions {
    display: flex;
    gap: 0.35rem;
    margin-bottom: 0.45rem;
}
.filter-actions button, .sort-actions button {
    background: var(--st-secondary-background-color);
    border: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
    border-radius: 0.3rem;
    color: var(--st-text-color);
    cursor: pointer;
    flex: 1;
    padding: 0.35rem 0.45rem;
}
.filter-actions button.primary {
    background: var(--st-primary-color);
    color: white;
}
.value-list {
    border-bottom: 1px solid color-mix(in srgb, var(--st-text-color) 14%, transparent);
    border-top: 1px solid color-mix(in srgb, var(--st-text-color) 14%, transparent);
    max-height: 13rem;
    margin-bottom: 0.5rem;
    overflow-y: auto;
    padding: 0.3rem 0;
}
.value-option {
    align-items: center;
    display: flex;
    gap: 0.45rem;
    padding: 0.22rem 0.1rem;
}
.empty-state {
    color: color-mix(in srgb, var(--st-text-color) 65%, transparent);
    padding: 1.2rem;
    text-align: center;
}
.row-count {
    color: color-mix(in srgb, var(--st-text-color) 65%, transparent);
    font-size: 0.78rem;
    margin-top: 0.35rem;
}
a {
    color: var(--st-link-color);
}
"""

_TABLE_JS = r"""
export default function(component) {
    const { data, state, setStateValue, setTriggerValue, parentElement } = component;
    const root = parentElement.querySelector('#portfolio-project-table');
    const rows = Array.isArray(data.rows) ? data.rows : [];
    const columns = Array.isArray(data.columns) ? data.columns : [];
    let filters = { ...((state && state.filters) || {}) };
    let sort = { ...((state && state.sort) || {}) };

    const displayValue = (row, column) => {
        const value = row[column.key];
        if (value === null || value === undefined || value === '') return '—';
        if (Array.isArray(value)) return value.join(', ');
        if (column.format === 'currency') {
            const number = Number(value);
            if (!Number.isNaN(number)) {
                return new Intl.NumberFormat(undefined, {
                    style: 'currency', currency: 'EUR', minimumFractionDigits: 2
                }).format(number);
            }
        }
        return String(value);
    };

    const filteredAndSortedRows = () => {
        const visible = rows.filter((row) => columns.every((column) => {
            const selected = filters[column.key];
            return !Array.isArray(selected) || selected.includes(displayValue(row, column));
        }));
        if (sort.column && sort.direction) {
            const column = columns.find((item) => item.key === sort.column);
            if (column) {
                visible.sort((left, right) => {
                    const aRaw = left[column.key];
                    const bRaw = right[column.key];
                    let comparison;
                    if (column.format === 'currency' || column.format === 'number') {
                        comparison = (Number(aRaw) || 0) - (Number(bRaw) || 0);
                    } else {
                        comparison = displayValue(left, column).localeCompare(
                            displayValue(right, column), undefined, { numeric: true, sensitivity: 'base' }
                        );
                    }
                    return sort.direction === 'desc' ? -comparison : comparison;
                });
            }
        }
        return visible;
    };

    const closeMenu = () => {
        const existing = root.querySelector('.filter-menu');
        if (existing) existing.remove();
    };

    const openFilterMenu = (column, anchor) => {
        closeMenu();
        const contextRows = rows.filter((row) => columns.every((otherColumn) => {
            if (otherColumn.key === column.key) return true;
            const selected = filters[otherColumn.key];
            return !Array.isArray(selected) || selected.includes(displayValue(row, otherColumn));
        }));
        const values = [...new Set(contextRows.map((row) => displayValue(row, column)))].sort((a, b) =>
            a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })
        );
        const selectedValues = new Set(
            Array.isArray(filters[column.key]) ? filters[column.key] : values
        );
        const menu = document.createElement('div');
        menu.className = 'filter-menu';
        menu.setAttribute('role', 'dialog');
        menu.setAttribute('aria-label', `Filter ${column.label}`);

        const search = document.createElement('input');
        search.type = 'search';
        search.placeholder = 'Search values';
        search.setAttribute('aria-label', `Search ${column.label} values`);
        menu.appendChild(search);

        const isBlank = (row) => {
            const value = row[column.key];
            return value === null || value === undefined || value === '' ||
                (Array.isArray(value) && value.length === 0);
        };
        const blankCount = contextRows.filter(isBlank).length;
        const populatedRows = contextRows.filter((row) => !isBlank(row));
        const uniqueCount = new Set(populatedRows.map((row) => displayValue(row, column))).size;
        const stats = [
            ['Rows', contextRows.length],
            ['Filled', populatedRows.length],
            ['Unique', uniqueCount],
            ['Empty', blankCount]
        ];
        const numericValues = populatedRows
            .map((row) => Number(row[column.key]))
            .filter((value) => Number.isFinite(value));
        const formatStat = (value) => {
            if (column.format === 'currency') {
                return new Intl.NumberFormat(undefined, {
                    style: 'currency', currency: 'EUR', maximumFractionDigits: 2
                }).format(value);
            }
            return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
        };
        if (numericValues.length && (column.format === 'currency' || column.format === 'number')) {
            const total = numericValues.reduce((sum, value) => sum + value, 0);
            stats.push(
                ['Minimum', formatStat(Math.min(...numericValues))],
                ['Average', formatStat(total / numericValues.length)],
                ['Maximum', formatStat(Math.max(...numericValues))]
            );
        } else if (populatedRows.length) {
            const counts = new Map();
            populatedRows.forEach((row) => {
                const value = displayValue(row, column);
                counts.set(value, (counts.get(value) || 0) + 1);
            });
            const top = [...counts.entries()].sort((left, right) => right[1] - left[1])[0];
            if (top) stats.push(['Most common', `${top[0]} (${top[1]})`]);
        }
        const statistics = document.createElement('div');
        statistics.className = 'filter-stats';
        stats.forEach(([labelText, valueText]) => {
            const item = document.createElement('div');
            item.className = 'filter-stat';
            const label = document.createElement('span');
            label.className = 'filter-stat-label';
            label.textContent = labelText;
            const value = document.createElement('span');
            value.className = 'filter-stat-value';
            value.title = String(valueText);
            value.textContent = String(valueText);
            item.append(label, value);
            statistics.appendChild(item);
        });
        menu.appendChild(statistics);

        const sortActions = document.createElement('div');
        sortActions.className = 'sort-actions';
        [['asc', 'Sort A → Z'], ['desc', 'Sort Z → A']].forEach(([direction, label]) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = label;
            button.onclick = () => {
                sort = { column: column.key, direction };
                setStateValue('sort', sort);
                render();
            };
            sortActions.appendChild(button);
        });
        menu.appendChild(sortActions);

        const quickActions = document.createElement('div');
        quickActions.className = 'filter-actions';
        const selectAll = document.createElement('button');
        selectAll.type = 'button';
        selectAll.textContent = 'Select all';
        const clearAll = document.createElement('button');
        clearAll.type = 'button';
        clearAll.textContent = 'Clear';
        quickActions.append(selectAll, clearAll);
        menu.appendChild(quickActions);

        const valueList = document.createElement('div');
        valueList.className = 'value-list';
        const options = [];
        values.forEach((value, index) => {
            const label = document.createElement('label');
            label.className = 'value-option';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = value;
            checkbox.checked = selectedValues.has(value);
            checkbox.id = `filter-${column.key}-${index}`;
            const text = document.createElement('span');
            text.textContent = value;
            label.append(checkbox, text);
            valueList.appendChild(label);
            options.push({ label, checkbox, value });
        });
        menu.appendChild(valueList);

        const applyActions = document.createElement('div');
        applyActions.className = 'filter-actions';
        const cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.textContent = 'Cancel';
        cancel.onclick = closeMenu;
        const apply = document.createElement('button');
        apply.type = 'button';
        apply.className = 'primary';
        apply.textContent = 'Apply';
        apply.onclick = () => {
            const selected = options.filter((item) => item.checkbox.checked).map((item) => item.value);
            if (selected.length === values.length) delete filters[column.key];
            else filters[column.key] = selected;
            setStateValue('filters', filters);
            render();
        };
        applyActions.append(cancel, apply);
        menu.appendChild(applyActions);

        search.oninput = () => {
            const needle = search.value.toLocaleLowerCase();
            options.forEach((item) => {
                item.label.hidden = !item.value.toLocaleLowerCase().includes(needle);
            });
        };
        selectAll.onclick = () => options
            .filter((item) => !item.label.hidden)
            .forEach((item) => { item.checkbox.checked = true; });
        clearAll.onclick = () => options
            .filter((item) => !item.label.hidden)
            .forEach((item) => { item.checkbox.checked = false; });

        root.appendChild(menu);
        const rect = anchor.getBoundingClientRect();
        const maxLeft = Math.max(8, window.innerWidth - 272);
        menu.style.left = `${Math.min(rect.left, maxLeft)}px`;
        menu.style.top = `${Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - 390))}px`;
        search.focus();
    };

    const render = () => {
        root.replaceChildren();
        const scroll = document.createElement('div');
        scroll.className = 'table-scroll';
        const table = document.createElement('table');
        const head = document.createElement('thead');
        const headerRow = document.createElement('tr');

        columns.forEach((column) => {
            const th = document.createElement('th');
            const content = document.createElement('div');
            content.className = 'header-content';
            const label = document.createElement('span');
            label.textContent = column.label;
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'filter-button';
            if (Object.prototype.hasOwnProperty.call(filters, column.key) || sort.column === column.key) {
                button.classList.add('active');
            }
            button.textContent = '▼';
            button.title = `Filter or sort ${column.label}`;
            button.setAttribute('aria-label', `Filter or sort ${column.label}`);
            button.onclick = (event) => {
                event.stopPropagation();
                openFilterMenu(column, button);
            };
            content.append(label, button);
            th.appendChild(content);
            headerRow.appendChild(th);
        });
        head.appendChild(headerRow);
        table.appendChild(head);

        const body = document.createElement('tbody');
        const visibleRows = filteredAndSortedRows();
        visibleRows.forEach((row) => {
            const tr = document.createElement('tr');
            tr.tabIndex = 0;
            tr.setAttribute('role', 'button');
            tr.setAttribute('aria-label', `Open project ${row.name || row.project_id}`);
            if (String(row.project_id) === String(data.selected_id)) tr.classList.add('selected');
            const selectRow = () => setTriggerValue('row_click', row.project_id);
            tr.onclick = selectRow;
            tr.onkeydown = (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    selectRow();
                }
            };
            columns.forEach((column) => {
                const td = document.createElement('td');
                const text = displayValue(row, column);
                if (column.format === 'url' && /^https?:\/\//i.test(String(row[column.key] || ''))) {
                    const link = document.createElement('a');
                    link.href = String(row[column.key]);
                    link.target = '_blank';
                    link.rel = 'noopener noreferrer';
                    link.textContent = text;
                    link.onclick = (event) => event.stopPropagation();
                    td.appendChild(link);
                } else {
                    td.textContent = text;
                }
                tr.appendChild(td);
            });
            body.appendChild(tr);
        });
        table.appendChild(body);
        scroll.appendChild(table);
        root.appendChild(scroll);

        if (!visibleRows.length) {
            const empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.textContent = 'No projects match the column filters.';
            root.appendChild(empty);
        }
        const count = document.createElement('div');
        count.className = 'row-count';
        count.textContent = `${visibleRows.length} of ${rows.length} project${rows.length === 1 ? '' : 's'}`;
        root.appendChild(count);
    };

    render();
}
"""

_PORTFOLIO_PROJECT_TABLE = st.components.v2.component(
    "eppm_portfolio_project_table",
    html=_TABLE_HTML,
    css=_TABLE_CSS,
    js=_TABLE_JS,
)


def portfolio_project_table(
    rows: list[dict[str, Any]],
    columns: list[dict[str, str]],
    selected_id: Any,
    *,
    key: str,
) -> Any:
    """Render the portfolio table and return the ID from the latest row click."""
    result = _PORTFOLIO_PROJECT_TABLE(
        data={"rows": rows, "columns": columns, "selected_id": selected_id},
        default={"filters": {}, "sort": {}},
        key=key,
        width="stretch",
        height="content",
        on_filters_change=lambda: None,
        on_sort_change=lambda: None,
        on_row_click_change=lambda: None,
    )
    return getattr(result, "row_click", None)
