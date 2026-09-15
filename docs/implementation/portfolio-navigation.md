# Portfolio navigation and sign-in

The sidebar shows language, the application title, and navigation in that order.
Navigation labels have no icons or numbering. Compact account details and sign-out
controls sit at the bottom, flowing below navigation on smaller screens.
Settings reveals Organization Structure, Parameter Definition, and Project
Configuration in the sidebar only while Settings is selected. Opening Settings
selects Organization Structure. Its tabs start with Function Types, Hierarchy
Types, Functions, Teams, Employees, and Resource Pools, followed by the tag tabs.
Each route renders inside its own keyed container. The shell hides retained
dashboard issue cards outside the dashboard route while the next page loads,
preventing an unstyled red issue button from flashing during navigation.

The planning resource grid uses plain black tree triangles and an undecorated
section heading. Its synchronized panes include 16 pixels below the final row.
The resource-pool label and timeline header occupy a separate fixed header row,
outside the vertical scrolling body, matching the Gantt layout. Only horizontal
scroll positions synchronize; no vertical scroll handler repositions headers.
Allocation and capacity cells round values below 100 to one decimal place;
values from 100 are truncated to whole numbers for display only.

The selected project's details offer **Planning & resources details** beside
**Edit details**. Any user who can read that project can open its planning view;
editing details still requires project edit permission. The shortcut rechecks
project access, selects Planning & Milestones, and replaces old resource-pool,
task, and project-context filters with the selected project.

The master list no longer includes a three-dot action button on each row.
Right-click and the keyboard context-menu shortcuts still expose project actions.

The public **Sign in** link navigates to `/auth/login` in the current browser tab.
The existing OIDC callback returns that same tab to the application. This uses
an ordinary same-tab anchor rather than attempting to close browser tabs.

Portfolio provides a project-status multiselect defaulting to In Progress. It
constrains the native paginated query as well as the displayed project count.
Clear all filters clears search and column filters and restores In Progress;
clearing the status selection itself includes all statuses.

## Page loading

The application sidebar immediately covers the main workspace with a blank loading
screen and spinning indicator when a different page is clicked. Navigation remains
available. The destination is revealed after the Streamlit rerun finishes and its
loading placeholders are gone; ordinary same-page widget updates stay visible.
