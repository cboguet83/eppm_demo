"""Shared context-menu styling based on the planning Gantt menu."""

CONTEXT_MENU_CSS = """
.context-menu {
    position: fixed; background: var(--st-background-color, #fff);
    color: var(--st-text-color, #1e293b); border: 1px solid #cbd5e1;
    border-radius: 8px; box-shadow: 0 10px 25px rgba(0,0,0,.15);
    z-index: 10000; min-width: 220px; padding: 6px 0;
    box-sizing: border-box; max-width: calc(100vw - 20px);
    max-height: calc(100vh - 20px); overflow-y: auto;
}
.context-menu-item {
    display: flex; align-items: center; gap: 10px; padding: 8px 16px;
    font: inherit; font-size: 13px; font-weight: 500; text-align: left;
    color: inherit; background: transparent; border: 0; border-radius: 0;
    box-sizing: border-box; width: 100%; margin: 0; cursor: pointer; transition: background .12s ease;
}
.context-menu-item:hover, .context-menu-item:focus-visible {
    background: var(--st-secondary-background-color, #f1f5f9);
    color: var(--st-primary-color, #2563eb); outline-offset: -2px;
}
.context-menu-item.danger {color: #dc2626;}
.context-menu-item.danger:hover {background: #fef2f2; color: #b91c1c;}
.context-menu-divider {height: 1px; background: #e2e8f0; margin: 4px 0;}
.context-menu-header {padding: 8px 16px; font-size: 12px; font-weight: 600;}
"""
