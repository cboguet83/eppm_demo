/** EPPM presentation DTOs mapped to the public planning contract. No persistence. */
import {decodeIntervals} from './planning-view/src/resources/summary.js';
import {ContractError} from './planning-view/src/contracts/index.js';
import {ownMessage} from './planning-view/src/contracts/owned.js';

const id=value=>String(value);
const editable=(permissions,project)=>permissions.edit_all===true || (permissions.editable_projects ?? []).some(value=>id(value)===id(project));

/** Return flat component labels from the existing translated application catalog.
 * @param {object} catalog Nested application translations.
 */
export function labelsFor(catalog={}) {
  const result={editMode:'Enable edit mode',hover:'Tooltips',name:'Step name',phase:'Phase',start:'Start date',end:'End date',
    progress:'Progress',description:'Description',addDependency:'Add predecessor',projectTask:'Project / step'};
  const sections={view_modes:{day:'day',week:'week',month:'month',quarter:'quarter',year:'year'},
    columns:{id:'columnId',project:'columnName',start:'columnStart',stop:'columnEnd'},
    toggles:{internal_links:'internalLinks',external_links:'externalLinks',show_description:'descriptions',show_hover:'hover',expand_all:'expandAll',collapse_all:'collapseAll'},
    resource_grid:{only_overallocated:'onlyOverallocated',title:'resourceUsage',show_total:'showTotal',show_selected:'showSelected',no_pools:'noResources',assigned_capacity:'assignedCapacity',clear_filter:'clearFilter',available_value:'available',overallocated_value:'excess',
      defined_capacity:'definedCapacity',min_assigned_capacity:'minAssignedCapacity',max_assigned_capacity:'maxAssignedCapacity'},
    modal:{field_name:'name',field_phase:'phase',field_start:'start',field_end:'end',field_desc:'description',field_progress:'progress',btn_save:'save',btn_cancel:'cancel',
      dependencies_header:'dependencies',btn_add_pred:'addDependency',whole_project_option:'wholeProject'},
    diagnostics:{title:'diagnostics',btn_close:'close'}};
  for(const [section,keys] of Object.entries(sections))for(const [key,target] of Object.entries(keys))if(typeof catalog[section]?.[key]==='string')result[target]=catalog[section][key];
  if(result.showTotal)result.total=result.showTotal;
  if(result.showSelected)result.selected=result.showSelected;
  const commands={project_dependencies:'manage_dependencies',manage_project_pools:'manage_project_pools',manage_task_pools:'assign_resource',
    manage_project_tags:'manage_tags',manage_task_tags:'manage_tags',edit_project_details:'edit_project',log_project_event:'log_event',
    complete_step:'mark_complete',delete_step:'delete_step',add_step:'add_step',add_step_after:'add_step_after',export_csv_template:'export_csv_template',import_csv_template:'import_csv_template',bulk_actions:'bulk_actions',project_filter_menu:'filter'};
  for(const [command,key] of Object.entries(commands))if(catalog.context_menu?.[key])result['command_'+command]=catalog.context_menu[key];
  return result;
}

/** Normalize only delivered endpoint identities. Redacted endpoints stay unavailable.
 * @param {object} row EPPM dependency. @param {string} project Successor owner.
 * @param {string|null} task Optional successor task identity.
 */
export function dependencyFor(row,project,task=null,permissions=null,alternative=false) {
  const predProject=row.predecessor_owner_id ?? row.pred_task_project_id ?? row.predecessor_project_id;
  const predecessor=row.predecessor_task_id!=null?{kind:'task',id:id(row.predecessor_task_id),...(predProject!=null?{projectId:id(predProject)}:{})}:
    row.predecessor_project_id!=null?{kind:'project',id:id(row.predecessor_project_id)}:{kind:'unavailable'};
  if(predecessor.kind!=='unavailable') {
    const name=predecessor.kind==='task'?row.predecessor_task_name:row.predecessor_project_name;
    if(typeof name==='string')predecessor.name=name;
    const start=row.pred_start_date ?? row.pred_start,end=row.pred_end_date ?? row.pred_end;
    if(start && end)Object.assign(predecessor,{start,end});
  }
  return {id:(task===null?'project:':'task:')+id(row.id),type:row.link_type ?? 'FS',lagDays:row.lag_days ?? 0,predecessor,
    ...(permissions?{editable:editable(permissions,project) && (alternative || task===null || predProject!=null && editable(permissions,predProject))}:{}),
    successor:task===null?{kind:'project',id:id(project)}:{kind:'task',id:id(task),projectId:id(project)},
    violated:row.is_violated===true,evaluable:row.is_evaluable!==false,external:predProject!=null && id(predProject)!==id(project),
    diagnostics:row.violation_text?[row.violation_text]:[],context:{projectId:id(project),dependencyId:row.id},
    ...(row.predecessor_project_name?{predecessorName:row.predecessor_project_name}:{}),
    ...(row.predecessor_task_name?{predecessorTaskName:row.predecessor_task_name}:{})};
}

/** Normalize a task using stable business identity across comparison snapshots.
 * @param {object} row Task DTO. @param {object} permissions Actor presentation hints.
 * @param {string|null} project Comparison project. @param {object|null} plan Comparison metadata.
 */
export function taskFor(row,permissions,project=null,plan=null,activeName=null) {
  const projectId=id(project ?? row.project_id),identity=id(row.stable_id ?? row.id);
  return {id:identity,stableId:identity,projectId,name:row.task_name ?? row.name,start:row.start_date ?? row.start,end:row.end_date ?? row.end,
    progress:row.progress_pct ?? row.progress ?? 0,description:row.description ?? '',phase:row.phase ?? '',
    editable:editable(permissions,projectId) && (!plan || plan.editable!==false),violations:row.violations ?? [],
    capabilities:{hasDiagnostics:(row.violations ?? []).length>0,logProject:editable(permissions,projectId),
      hasPredecessors:plan?(plan.dependencies ?? []).some(dep=>id(dep.task_id)===identity):(row.dependenciesList ?? []).length>0},
    context:{projectId,taskName:row.task_name ?? row.name,...(plan?{planId:plan.id,planRevision:plan.revision}:{})},
    tooltip:[(plan?.name ?? activeName)?'Scenario: '+(plan?.name ?? activeName):null,row.task_name ?? row.name,String(row.progress_pct ?? row.progress ?? 0)+'%',row.description,...(row.violations ?? []),
      ...(row.tags ?? []).map(tag=>tag.tag_name ?? tag.free_tag ?? tag.tag ?? ''),
      ...(row.pools ?? []).map(pool=>(pool.pool_name ?? pool.name ?? '')+' · '+(pool.fte ?? pool.fte_assigned ?? 0)+' FTE')].filter(Boolean).join('\n')};
}

/** Normalize compact resource intervals through the shared inclusive decoder.
 * @param {object} pool Resource DTO. @param {object} comparisons Alternative demand.
 */
export function resourceFor(pool,comparisons={},permissions={}) {
  const daily=field=>pool[field+'_intervals']?decodeIntervals(pool[field+'_intervals']):(pool[field] ?? {});
  return {id:id(pool.id),name:pool.name,capacity:pool.displayed_assigned_capacity ?? pool.capacity,
    definedCapacity:pool.theoretical_capacity ?? pool.capacity,hasAssignments:pool.has_assigned_resources===true,
    usedBySelection:pool.used_by_selected_projects!==false,usage:daily('daily_usage'),selectedUsage:daily('selected_projects_daily_usage'),
    assignedCapacity:daily('daily_assigned_capacity'),comparisonUsage:comparisons[id(pool.id)] ?? {},capabilities:{poolDetails:permissions.manage_shared===true},context:{poolId:pool.id,poolName:pool.name}};
}

/** Normalize hierarchy iteratively; incoming duplicate/cyclic graphs are rejected.
 * @param {object[]} rows Application hierarchy.
 */
export function hierarchyFor(rows=[]) {
  const result=[],pending=rows.toReversed().map(row=>({row,destination:result})),seen=new Set();
  while(pending.length) {
    const {row,destination}=pending.pop();if(!row || seen.has(row))throw new ContractError('eppm.hierarchy');seen.add(row);
    const node={id:row.key,name:row.name,capabilities:{poolDetails:row.pool_id!=null},context:{...(row.group_id!=null?{groupId:row.group_id}:{}),...(row.pool_id!=null?{poolId:row.pool_id}:{}),poolName:row.name}};
    if(row.pool_id!=null)node.resourceId=id(row.pool_id);
    if(row.children){node.children=[];for(const child of row.children.toReversed())pending.push({row:child,destination:node.children});}
    destination.push(node);
  }
  return result;
}

/** Normalize one EPPM project header without fabricated dates.
 * @param {object} row Summary. @param {object} permissions Actor hints.
 */
export function projectFor(row,permissions,view={}) {
  const plan=view.alternatives?.[id(row.id)],comparison=Object.keys(view.alternatives ?? {}).length>0;
  const canEdit=editable(permissions,row.id);
  const canApprove=permissions.baseline_all===true || (permissions.approvable_projects ?? []).some(value=>id(value)===id(row.id));
  return {id:id(row.id),name:row.name,taskCount:row.taskCount ?? 0,progress:row.progress ?? 0,defaultPhase:'Phase 1 - FAI',editable:editable(permissions,row.id),
    capabilities:{editProject:canEdit && (!comparison || plan?.editable===true),logProject:canEdit,
      captureBaseline:!comparison && canApprove,deleteBaseline:!comparison && canApprove && (permissions.baseline_projects ?? []).some(value=>id(value)===id(row.id)),
      activateAlternative:!!plan && canApprove,createAlternative:canEdit,
      showBaseline:view.show_baseline!==true,hideBaseline:view.show_baseline===true,hideAlternatives:comparison,
      hasDiagnostics:row.hasViolations===true || (row.projectDependencies ?? []).some(dep=>dep.is_violated===true)},
    ...(row.start && row.end?{start:row.start,end:row.end}:{}),context:{projectId:id(row.id)},
    ...(view.active_plan_names?.[row.id]?{scenarioName:view.active_plan_names[row.id]}:{}),tooltip:[view.active_plan_names?.[row.id]?'Scenario: '+view.active_plan_names[row.id]:null,row.name].filter(Boolean).join('\n'),
    violations:(row.projectDependencies ?? []).filter(dep=>dep.is_violated).map(dep=>dep.violation_text).filter(Boolean)};
}

/** Normalize baseline/alternative lanes, retaining stable pairing and host revisions.
 * @param {object} args Application scenario envelope.
 */
export function overlaysFor(args) {
  const result=[],permissions=args.permissions ?? {};
  for(const [project,plan] of Object.entries(args.alternatives ?? {}))result.push({id:'alternative:'+id(plan.id),kind:'alternative',projectId:project,
    name:plan.name,tooltip:'Scenario: '+plan.name,revision:plan.revision,newScenario:plan.new_scenario===true,editable:plan.editable===true,
    capabilities:{hasDiagnostics:(plan.dependencies ?? []).some(row=>row.is_violated===true)},
    context:{projectId:project,planId:plan.id,planRevision:plan.revision},tasks:plan.tasks.map(row=>taskFor(row,permissions,project,plan)),
    dependencies:(plan.dependencies ?? []).map(row=>dependencyFor(row,project,row.task_id==null?null:id(row.task_id),permissions,true))});
  if(args.show_baseline)for(const [project,rows] of Object.entries(args.baseline_tasks ?? {}))result.push({id:'baseline:'+project,kind:'baseline',projectId:project,editable:false,
    tasks:rows.map(row=>taskFor(row,permissions,project))});
  return result;
}

/** Normalize bounded task/project replacements. HTTP correlation stays unchanged.
 * @param {object} patch Legacy replacement. @param {object} host Current host context.
 * @param {string} revision Public data revision. @param {string} baseRevision Previous revision.
 */
export function patchFor(patch,host,revision,baseRevision=revision) {
  const tasks=(patch.tasks ?? []).map(row=>taskFor(row,host.permissions,null,null,host.active_plan_names?.[row.project_id])),dependencies=[];
  const owners=new Map(tasks.map(task=>[task.id,task.projectId]));
  for(const row of patch.tasks ?? [])for(const dep of row.dependenciesList ?? [])dependencies.push(dependencyFor({...dep,
    predecessor_owner_id:dep.predecessor_owner_id ?? dep.pred_task_project_id ?? owners.get(id(dep.predecessor_task_id)) ?? dep.predecessor_project_id},row.project_id,row.id,host.permissions));
  const summaries=new Map((host.project_summaries ?? []).filter(row=>(patch.replace_projects ?? []).some(project=>id(project)===id(row.id))).map(row=>[id(row.id),row]));
  for(const row of patch.project_summaries ?? [])summaries.set(id(row.id),row);
  for(const row of summaries.values())for(const dep of row.projectDependencies ?? [])dependencies.push(dependencyFor(dep,row.id,null,host.permissions));
  return {version:1,kind:'patch',scope:host.view_scope ?? host.scope_token,revision,baseRevision,replaceProjectIds:(patch.replace_projects ?? []).map(id),tasks,dependencies,
    ...(patch.project_summaries?{projects:patch.project_summaries.map(row=>projectFor(row,host.permissions,host))}:{}),
    ...(patch.resource_pools?{resources:patch.resource_pools.map(pool=>resourceFor(pool,host.alternative_pool_usage,host.permissions))}:{}),
    ...(patch.evict_project_ids?{evictProjectIds:patch.evict_project_ids.map(id)}:{}),
    ...(patch.loaded_project_ids?{loadedProjectIds:patch.loaded_project_ids.map(id)}:{}),
    ...(patch.focus_project_id?{viewHints:{focusProjectId:id(patch.focus_project_id)}}:{})};
}

/** Create one checked initial snapshot; all subsequent host changes are patches.
 * @param {object} args Full application envelope.
 */
export function snapshotFor(args) {
  const patch=patchFor({tasks:args.tasks,project_summaries:args.project_summaries},args,args.task_revision);
  const filter=args.active_resource_filter;
  const hierarchy=hierarchyFor(args.resource_pool_hierarchy),pending=[...hierarchy];let groupId=filter?.group_id==null?null:id(filter.group_id);
  while(pending.length){const node=pending.pop();if(groupId!==null && id(node.context.groupId)===id(filter.group_id))groupId=node.id;for(const child of node.children ?? [])pending.push(child);}
  return ownMessage({version:1,kind:'snapshot',scope:args.view_scope ?? args.scope_token,revision:args.task_revision,projects:patch.projects,tasks:patch.tasks,dependencies:patch.dependencies,
    resources:(args.resource_pools ?? []).map(pool=>resourceFor(pool,args.alternative_pool_usage,args.permissions)),hierarchy,
    overlays:overlaysFor(args),loadedProjectIds:(args.loaded_project_ids ?? []).map(id),capabilities:{edit:true,select:true,clearResourceFilter:!!filter},labels:labelsFor(args.translations),
    choiceProjects:(args.all_projects ?? args.project_summaries).map(row=>({id:id(row.id),name:row.name})),
    resourceFilter:filter?{...(filter.pool_id?{resourceId:id(filter.pool_id)}:{groupId}),name:filter.pool_name ?? filter.name ?? '',
      ...(filter.start_date && filter.end_date?{start:filter.start_date,end:filter.end_date}:{}),clearAction:'clear_resource_pool_filter'}:null,
    viewHints:{editEnabled:args.edit_enabled===true,expandedProjectIds:args.project_summaries.length===1?[id(args.project_summaries[0].id)]:[],filters:{externalLinks:false}}});
}

/** Translate generic incoming links back to the authoritative task-service shape.
 * @param {object[]} dependencies Edited incoming dependencies.
 */
export function dependencyValues(dependencies=[]) {
  return dependencies.map(row=>({predecessor_task_id:row.predecessor.kind==='task'?Number(row.predecessor.id):null,
    predecessor_project_id:row.predecessor.kind==='project'?Number(row.predecessor.id):null,link_type:row.type,lag_days:row.lagDays ?? 0}));
}

/** Translate a validated display intention, preserving the established Python API.
 * @param {object} event Public component event. @param {object} host Current EPPM metadata.
 * @param {string[]} loaded Bounded hydrated project IDs.
 */
export function eventFor(event,host,loaded=[]) {
  const context=event.context ?? {},project=context.projectId ?? (event.targetKind==='projects'?event.targetId:null);
  const plan=event.overlayId?.startsWith('alternative:') || event.type==='command'?(host.alternatives ?? {})[project]:null;
  const base={nonce:event.requestId,scope_token:host.scope_token,loaded_project_ids:loaded.map(Number)};
  if(event.type==='dates')return {...base,action:plan?'update_alternative_dates':'update_dates',id:Number(event.targetId),start_date:event.start,end_date:event.end,
    ...(plan?{project_id:Number(project),plan_id:plan.id,revision:context.planRevision}: {})};
  const fields=event.values;
  if(event.type==='task' || event.type==='progress') {
    const values=event.type==='task'?{task_name:fields.name,phase:fields.phase,description:fields.description,start_date:fields.start,end_date:fields.end,
      progress_pct:fields.progress,dependencies:dependencyValues(fields.dependencies)}:{progress:event.progress};
    const operation=event.operation==='create'?'create_step_full':event.type==='task'?'update_task_full':'update_progress';
    return {...base,action:plan?'alternative_action':operation,...(plan?{operation,project_id:Number(project),plan_id:plan.id,revision:context.planRevision}:{}),
      ...(event.operation==='create'?{project_id:Number(project)}:{id:Number(event.targetId)}),...values};
  }
  if(event.type==='select')return {...base,action:['resources','hierarchy'].includes(event.targetKind)?'select_pool_allocations':'select_planning_entity',pool_id:context.poolId ?? null,group_id:context.groupId ?? null,
    start_date:context.start,end_date:context.end,allocation_scope:context.scope};
  if(event.type!=='command')throw new ContractError('eppm.event');
  // Commands can carry an application-owned form payload. It is validated again
  // by existing Python boundary/services; never spread it over correlation data.
  const values=context.values ?? {};
  const result={...values,...base,action:event.command,...(project!=null?{project_id:Number(project)}:{}),
    ...(event.targetKind==='tasks'?{id:Number(event.targetId),task_name:context.taskName}:{}),
    ...(context.enabled!==undefined?{enabled:context.enabled}:{}),
    ...(context.poolId!=null?{pool_id:context.poolId}:{}),...(context.groupId!=null?{group_id:context.groupId}:{}),
    ...(context.poolName?{pool_name:context.poolName}:{}),...(context.start?{start_date:context.start,end_date:context.end}:{}),
    ...(context.scope?{allocation_scope:context.scope}:{}),...(context.filterScope?{filter_scope:context.filterScope}:{}),
    ...(context.clearOther!==undefined?{clear_other_filters:context.clearOther}: {})};
  if(result.action==='filter_project')result.project_name=(host.all_projects ?? []).find(row=>id(row.id)===id(project))?.name ?? '';
  if(plan && ['update_task_full','create_step_full','update_progress','delete_step','manage_task_tags','manage_task_pools','manage_project_tags','manage_project_pools','export_csv_template','import_csv_template','manage_dependencies'].includes(result.action)) {
    return {...result,operation:result.action,action:'alternative_action',plan_id:plan.id,revision:context.planRevision ?? plan.revision};
  }
  return result;
}
