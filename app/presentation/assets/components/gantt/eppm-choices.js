/** Coalesced EPPM predecessor reads; choices never hydrate unrelated schedules. */

/** Create an instance-owned choice provider over EPPM application commands.
 * @param {object} transport EPPM transport. @returns {object} Reader/response/disposal seam.
 */
export function createChoiceReader(transport) {
  const pending=new Map(),groups=new Map();let disposed=false;
  const forget=group=>{pending.delete(group.nonce);groups.delete(group.key);};
  const finish=(group,error,rows=[])=>{
    forget(group);
    for(const waiter of group.waiters){waiter.cleanup();if(error)waiter.reject(error);else waiter.resolve(rows);}
    group.waiters.clear();
  };
  return {
    read(request) {
      const host=transport.host(),project=request.projectId;
      if(disposed || request.signal.aborted)return Promise.reject(new DOMException('Choice read cancelled.','AbortError'));
      if(request.overlayId?.startsWith('alternative:')) {
        const plan=host.alternatives?.[project],rows=plan?plan.tasks:(host.alternative_task_choices ?? []).filter(row=>String(row.project_id)===project);
        return Promise.resolve(rows.map(row=>({id:String(row.stable_id ?? row.id),name:row.task_name ?? row.name})));
      }
      const key=JSON.stringify([host.scope_token,host.task_revision,project]);let group=groups.get(key);
      if(!group) {
        const nonce=transport.event('load_dependency_tasks',{projectId:project},project);
        group={key,nonce,project,scope:host.scope_token,revision:host.task_revision,waiters:new Set()};groups.set(key,group);pending.set(nonce,group);
      }
      const active=group;
      return new Promise((resolve,reject)=>{
        const abort=()=>{active.waiters.delete(waiter);if(!active.waiters.size)forget(active);reject(new DOMException('Choice read cancelled.','AbortError'));};
        const waiter={resolve,reject,cleanup:()=>request.signal.removeEventListener('abort',abort)};active.waiters.add(waiter);
        request.signal.addEventListener('abort',abort,{once:true});
      });
    },
    receive(response) {
      const group=pending.get(response.nonce);if(!group)return;const host=transport.host();
      if(group.scope!==host.scope_token || group.revision!==host.task_revision){finish(group,new DOMException('Choice read cancelled.','AbortError'));return;}
      if(response.error || String(response.project_id)!==group.project || !Array.isArray(response.tasks) || response.tasks.some(row=>!row || row.id==null || typeof row.task_name!=='string')) {
        finish(group,new Error('Predecessor tasks could not be loaded.'));return;
      }
      finish(group,null,response.tasks.map(task=>({id:String(task.id),name:task.task_name})));
    },
    destroy() {
      if(disposed)return;disposed=true;
      for(const group of [...pending.values()])finish(group,new DOMException('Choice reader disposed.','AbortError'));
      pending.clear();groups.clear();
    }
  };
}
