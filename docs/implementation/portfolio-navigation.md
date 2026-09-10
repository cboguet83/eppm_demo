# Portfolio navigation and sign-in

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
