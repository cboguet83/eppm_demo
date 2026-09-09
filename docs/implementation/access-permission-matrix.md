# Business entry-point permission inventory

Source inventory: application service public methods on `feature/oidc-access-management`.
This matrix records the service and transport contract implemented on the feature
branch. Project, Gantt, and collaboration controls reflect current permission scopes.
The real Keycloak browser workflow passed on the rebuilt application image; current
results are recorded in [verification evidence](access-security-evidence.md).
On 2026-09-10, the inventory was cross-checked against all 213 current public
business-service methods; authentication and access-administration boundaries are
listed separately below.

An application caller supplies a server-resolved actor. A deployment operator uses
an explicit, separate operator context. There is no anonymous/superuser default.
For project operations, ownership is resolved from stored rows; submitted project
IDs cannot override task, contact, tag, log, link or allocation ownership. Both sides
of cross-project mutations need permission. Bulk mutations are atomic.

`read` means `project.read` scoped to each returned project. Queries filter before
pagination, aggregation, grouping and export. `edit` means `project.edit` for every
affected project, rechecked inside the write transaction. `shared` means the global
`business.manage` permission. `reference` means a separately bounded, minimal
projection for an authorized project workflow, with no unrelated project values,
employee details, resource contributions or usage counts. Full shared-data methods
remain `shared`; project workflow callers use separate reference projections.

| Service | Entry points | Required policy |
| --- | --- | --- |
| ProjectService | `get_project_by_id`, `exists`, `get_links`, `get_planning_catalog` | read |
| ProjectService | `permissions` | current read context; projects remain separate for each permission; visibility projection never authorizes a mutation |
| ProjectService | `generate_project_id`, `create_project` | global `project.create` |
| ProjectService | `update_project` | edit; changed scope-eligible values/type additionally require `project.protected_properties` and audit |
| ProjectService | `delete_project` | global `project.delete`; all dependent mutations authorized in the transaction |
| PortfolioService | `revision`, `get_metrics`, `get_page`, `get_facet`, `get_detail` | read; current security context participates in every cache key |
| PortfolioService | `get_catalog` | reference; no full organization records |
| PlanningService | `export_schedule`, `export_project_template` | read; download delivery reauthorizes on fetch |
| PlanningService | `validate_project_template` | edit; all supplied cross-project references must be authorized; no changes |
| PlanningService | `replace_project_template`, `import_csv`, `bulk_create_milestones` | edit for every affected project; validate before deleting; entire import rolls back on denial |
| PlanningService | `create_milestone`, `update_milestone`, `save_task_dependencies`, `add_dependency`, `update_dates`, `update_progress`, `delete_milestone` | edit; stored owners and all changed dependency endpoints |
| PlanningService | `related_project_ids`, `get_milestones_by_project`, `search_task_choices`, `get_all_milestones`, `get_dependencies_for_project`, `get_task_dependencies` | read; hidden dependency endpoints and labels are excluded |
| PlanningService | `get_project_date_bounds`, `get_all_project_date_bounds`, `get_all_external_tasks_map`, `get_milestones_for_projects`, `get_dependencies_for_projects`, `get_milestone_by_id` | read |
| PlanningService | `get_project_summaries`, `affected_task_projects`, `consuming_pool_ids`, `read_task_bundle` | read; derived cache refresh is not permission to mutate business data |
| PlanningService | `get_totals` | read; totals use scoped project/task/dependency/allocation views |
| Database initialization | `ensure_planning_indexes` | deployment maintenance; unavailable through planning services or browser workflows |
| BudgetService | `get_report` | read; scope before financial totals |
| ProjectOverallocationService | `overallocated_project_ids` | read; only authorized demand may influence returned project indicators |
| PoolCapacityService | `calculate_many`, `get_summaries`, `get_details` | read for project demand; shared for full employee/mapping contributions; project workflows receive minimal capacity projections |
| CollaborationService | `list_links`, `list_contacts`, `list_events` | read |
| CollaborationService | `can_edit` | current edit permission for the selected project; false after disabling or revocation; visibility only |
| CollaborationService | `save_link`, `delete_link`, `save_contact`, `delete_contact`, `reassign_contact`, `save_event` | edit; existing child ownership and both projects for reassignment |
| CollaborationService | `list_catalog`, `function_choices` | reference for authorized collaboration workflows; function choices omit phone numbers |
| CollaborationService | `list_functions` | shared; full occupant/contact projection |
| CollaborationService | `save_catalog`, `delete_catalog` | shared |
| ResourcePoolService | `get_assignments`, `get_assignment_by_id`, `get_task_assignments_map`, `get_project_assignments_map` | read; derive task ownership independently of submitted project IDs |
| ResourcePoolService | `create_assignment`, `update_assignment`, `delete_assignment` | edit; old and new stored owners and any referenced task |
| ResourcePoolService | `get_all_pools`, `get_pool_by_id`, `get_all_group_members`, `get_pool_group_by_id`, `get_all_pool_groups`, `get_group_members`, `get_group_direct_member_ids`, `get_group_descendant_pool_ids` | shared; planning uses minimal pool/group reference projections |
| ResourcePoolService | `get_mappings_by_pool`, `get_all_mappings`, `get_tag_choices`, `get_pool_tags`, `would_create_group_cycle`, `get_allowed_child_group_ids` | shared; reference variants only where a project workflow needs them |
| ResourcePoolService | `create_pool`, `update_pool`, `delete_pool`, `create_pool_group`, `update_pool_group`, `delete_pool_group`, `create_mapping`, `update_mapping`, `delete_mapping`, `replace_group_members`, `set_pool_tags` | shared |
| OrganizationService | `get_all_function_types`, `get_function_type_by_id`, `get_all_functions`, `get_function_by_id`, `get_all_teams`, `get_team_by_id`, `get_all_employees`, `get_employee_by_id` | shared; project workflows use separate minimal reference projections |
| OrganizationService | `create_function_type`, `update_function_type`, `delete_function_type`, `create_function`, `update_function`, `delete_function`, `create_team`, `update_team`, `delete_team`, `create_employee`, `update_employee`, `delete_employee` | shared |
| OrganizationService | `get_employee_calendar_exceptions`, `get_employee_calendar_exception_by_id`, `has_overlapping_calendar_exception`, `create_employee_calendar_exception`, `update_employee_calendar_exception`, `delete_employee_calendar_exception`, `get_effective_occupation_percentage` | shared |
| OrganizationService | `check_email_exists`, `check_code_exists`, `generate_next_employee_code`, `get_team_functions`, `set_team_functions`, `add_team_function`, `remove_team_function` | shared |
| ProjectTypeService | `get_all_types`, `get_template`, `get_applicability` | shared for management; project-specific minimal effective-template references for editing/inspection |
| ProjectTypeService | `create_type`, `update_type`, `delete_type`, `set_applicability`, `save_rule` | shared; scope-eligible definition/default changes require protected-property audit |
| SchemaService | `get_snapshot`, `get_all_groups`, `get_all_parameters`, `get_all_options`, `get_alias_translations`, `get_next_available_group_order`, `generate_param_id` | shared for administration; separate project-editor references where needed |
| SchemaService | `set_alias_translation`, `create_group`, `update_group`, `delete_group`, `create_parameter`, `update_parameter`, `delete_parameter`, `add_option`, `delete_option` | shared; scope-eligible definition/option changes require audit and invalidation as appropriate |
| TagService | `get_all_tag_groups`, `get_tag_group_by_id`, `count_tags_by_group`, `get_all_tags`, `get_tags_by_group_name`, `get_project_tag_group_tags`, `get_task_tag_group_tags`, `get_tag_group_for_tag`, `get_tag_by_id`, `count_tag_usages` | shared for dictionary administration; separate minimal reference choices for project/task tagging; scoped usage totals |
| TagService | `create_tag_group`, `update_tag_group`, `delete_tag_group`, `create_tag`, `update_tag`, `delete_tag` | shared |
| TagService | `get_all_resource_pool_tags`, `get_resource_pool_tags`, `create_resource_pool_tag`, `delete_resource_pool_tag` | shared; minimal reference projections for planning only |
| TagService | `get_all_project_tags`, `get_project_tags_by_project`, `get_project_tag_by_id`, `get_project_tags_by_project_ids` | read |
| TagService | `create_project_tag`, `update_project_tag`, `delete_project_tag` | edit; old/new stored project owners |
| TagService | `get_task_tags_page`, `get_all_task_tags`, `get_task_tags_by_task`, `get_task_tag_by_id`, `get_task_tags_by_task_ids` | read; filter before page/count/owner labels |
| TagService | `create_task_tag`, `update_task_tag`, `delete_task_tag` | edit; derive old/new task owners from stored tasks |
| TagService | `project_choices`, `search_task_choices`, `get_task_choice` | read with minimal labels and bounded searches |
| MaintenanceService | `startup`, `seed_defaults`, `seed_projects`, `flush`, `counts`, `clear_pool_allocations`, `generate_pool_allocations`, `seed_pool_scenarios` | deployment operator only; browser totals use scoped business reads |

Separate project-reference methods are `OrganizationService.function_references`
and `employee_references`, `SchemaService.property_references` and
`alias_references`, `ProjectTypeService.type_choices` and `template_reference`,
`ResourcePoolService.pool_choices`, `group_choices`, `group_membership`, and
`group_pool_ids`, and `TagService.project_tag_choices` and `task_tag_choices`.
Their dedicated projections omit employee contact/staffing data, pool configuration
notes, dictionary usage counts, and unrelated project assignments.

## Access and browser boundaries

| Boundary | Policy |
| --- | --- |
| Login/callback | One configured OIDC provider; valid code/state/nonce/PKCE/signature/issuer/audience/lifetimes before identity creation |
| Own account state and session check | Valid application session, including pending/disabled state; only own safe reference/status |
| Explicit activity/logout | Same-origin POST, current application session; logout revokes all tabs sharing the browser cookie |
| Account search, assignments, scope choices, explanation, audit | Current global `access.manage` |
| Registration, status changes, grants, revocations | Current global `access.manage`, recent verified authentication, production MFA; atomic audit and last-admin continuity |
| Bootstrap/recovery/account inspection CLI | Explicit deployment operator context; no HTTP route; bootstrap once and recovery with reason |
| WebSocket/widget/custom-component callbacks | Server-resolved actor; overwritten trusted identity header binds reconnects to the browser session and security revision; incoming and outgoing messages revalidate session/status/revision; operation-specific transaction checks remain mandatory |
| CSV/import/bulk/download | Same permissions as direct service calls; a bounded 2 MiB UTF-8 CSV component payload replaces native file uploads; import validation precedes mutation; authenticated attachment route regenerates and authorizes exports on fetch |
| Native media, native upload, metrics URLs | Denied; business downloads use the authenticated attachment route |
| Cached content/fragments/background work | Current session and effective scope; user/security revision isolation; background work never extends user activity |

`project.approve` is reserved for an existing approval workflow if one is found.
The inspected application has no approval state transition to authorize. Granting
`project_approver` currently provides scoped reading plus that separate permission;
it does not create an approval process or confer editing/administration.
