/** Declarative EPPM application commands; persistence remains in Python handlers. */

/** Return stable command descriptors so reruns do not remount the workspace.
 * @returns {object[]} Public planning context-action descriptors.
 */
export function planningCommands() {
  const project=(id,label,capability)=>({id,label,targetKinds:['projects'],...(capability?{capability}:{}),
    ...(['editProject','captureBaseline','deleteBaseline','activateAlternative','createAlternative'].includes(capability)?{requiresMode:true}:{})});
  const task=(id,label,edit=true)=>({id,label,targetKinds:['tasks'],...(edit?{requiresEdit:true}:{})});
  const resource=(id,label,children)=>({id,label,targetKinds:['resources','hierarchy'],...(children?{children}:{})});
  return [
    {...project('add_step','Add step','editProject'),editor:'createTask'},
    project('project_dependencies','Manage dependencies','editProject'),{...project('constraint_diagnostics','Constraint diagnostics','hasDiagnostics'),editor:'diagnostics'},
    {id:'scenario_management',label:'Scenario management',targetKinds:['projects'],children:[
      project('create_alternative','Create alternative scenario','createAlternative'),project('choose_alternative','Display an alternative scenario'),
      project('hide_alternatives','Hide alternative scenarios','hideAlternatives'),project('activate_alternative','Set alternative as active scenario','activateAlternative'),
      project('show_baseline','Show baseline','showBaseline'),project('hide_baseline','Hide baseline','hideBaseline'),
      project('baseline_current_project','Set current project as baseline','captureBaseline'),project('delete_project_baseline','Delete baseline','deleteBaseline')]},
    {id:'project_filter_menu',label:'Filter projects',targetKinds:['projects','tasks'],children:[
      project('filter_project','This project'),project('filter_project_with_predecessors','With predecessors'),project('filter_project_with_dependencies','With all dependencies')].map(command=>({...command,targetKinds:['projects','tasks']}))},
    {id:'bulk_actions',label:'Bulk actions',targetKinds:['projects'],children:[project('export_csv_template','Export CSV'),project('import_csv_template','Import CSV','editProject')]},
    project('manage_project_tags','Manage project tags','editProject'),project('manage_project_pools','Manage project resource pools','editProject'),
    {...project('log_project_event','Log project event','logProject'),targetKinds:['projects','tasks']},project('edit_project_details','View project details'),
    task('complete_step','Mark complete'),task('delete_step','Delete step'),task('manage_task_tags','Manage step tags'),{...task('manage_task_pools','Assign Resource'),icon:'👤'},
    {...task('add_step_after','Add step'),editor:'createTask'},{...task('task_diagnostics','Constraint diagnostics',false),capability:'hasDiagnostics',editor:'diagnostics'},
    {...task('view_predecessors','View predecessors',false),capability:'hasPredecessors',editor:'predecessors'},
    {...resource('show_pool_allocations','Show resource allocations'),disabledScopes:['alternative','alternative_total','alternative_selected']},
    {...resource('go_to_pool_details','Resource pool details'),capability:'poolDetails',disabledScopes:['alternative','alternative_total','alternative_selected']},
    resource('filter_pool','Filter consuming projects',[
      resource('filter_pool_this','This period'),resource('filter_pool_predecessors','With predecessors'),resource('filter_pool_dependencies','With all dependencies')]),
    {...resource('clear_resource_pool_filter','Clear resource filter'),capability:'clearResourceFilter'}
  ];
}

/** Apply host confirmations and translate presentation-only command aliases.
 * @param {object} event Valid display event. @param {object} host Current server hints.
 * @param {Window} win Owning browser window. @returns {object|null} Intended host request, or cancellation.
 */
export function confirmedCommand(event,host,win) {
  if(event.type!=='command')return event;
  const project=event.context?.projectId ?? event.targetId,plan=host.alternatives?.[project];
  const hasBaseline=(host.permissions?.baseline_projects ?? []).some(id=>String(id)===String(project));
  const confirmation={delete_step:'Delete this step?',delete_project_baseline:'Delete this project’s baseline? Its frozen history will be retained.',
    baseline_current_project:hasBaseline?'This project already has a baseline. Replace it with the current project plan? The previous saved plan will be kept.':null,
    activate_alternative:plan?`Set '${plan.name}' as the active scenario? The current active plan will become inactive. Its tasks and resource assignments will be replaced in the portfolio by this scenario.`:null};
  if(event.command==='activate_alternative' && plan?.status!=='approved'){win.alert('Approve this scenario in the Project plans tab before activating it.');return null;}
  if(confirmation[event.command] && !win.confirm(confirmation[event.command]))return null;
  const context={...event.context},result={...event,context};
  if(event.command==='activate_alternative')context.values={plan_id:plan.id,revision:plan.revision};
  if(['show_baseline','hide_baseline'].includes(event.command)){result.command='toggle_baseline';context.enabled=event.command==='show_baseline';}
  if(event.command==='complete_step'){result.command='update_progress';context.values={progress:100};}
  if(event.command.startsWith('filter_project')) {
    result.command='filter_project';context.filterScope=event.command==='filter_project'?'this':event.command==='filter_project_with_predecessors'?'predecessors':'all';
  }
  if(event.command.startsWith('filter_pool_') || event.command.startsWith('intersect_pool_')) {
    result.command='filter_by_resource_pool';context.filterScope=event.command.endsWith('_dependencies')?'all':event.command.split('_').at(-1);context.clearOther=event.command.startsWith('filter_pool_');
  }
  return result;
}
