/** Correlated EPPM predecessor reads; names never hydrate unrelated schedules. */

/** Create an instance-owned choice provider over EPPM application commands.
 * @param {object} transport EPPM transport. @returns {object} Reader/response/disposal seam.
 */
export function createChoiceReader(transport) {
  const pending=new Map();let disposed=false;
  return {
    read(request) {
      const host=transport.host(),project=request.projectId;
      if(disposed || request.signal.aborted)return Promise.reject(new DOMException('Choice read cancelled.','AbortError'));
      const alternative=request.overlayId?.startsWith('alternative:');
      if(alternative) {
        const plan=host.alternatives?.[project];
        const rows=plan?plan.tasks:(host.alternative_task_choices ?? []).filter(row=>String(row.project_id)===project);
        return Promise.resolve(rows.map(row=>({id:String(row.stable_id ?? row.id),name:row.task_name ?? row.name})));
      }
      return new Promise((resolve,reject)=>{
        const nonce=transport.event('load_dependency_tasks',{projectId:project},project);
        const abort=()=>{pending.delete(nonce);reject(new DOMException('Choice read cancelled.','AbortError'));};
        const finish=()=>request.signal.removeEventListener('abort',abort);
        pending.set(nonce,{scope:host.scope_token,revision:host.task_revision,project,
          resolve:rows=>{finish();resolve(rows);},reject:error=>{finish();reject(error);}});
        request.signal.addEventListener('abort',abort,{once:true});
      });
    },
    receive(response) {
      const row=pending.get(response.nonce);if(!row)return;
      pending.delete(response.nonce);const host=transport.host();
      if(row.scope!==host.scope_token || row.revision!==host.task_revision){row.reject(new DOMException('Choice read cancelled.','AbortError'));return;}
      if(response.error || String(response.project_id)!==row.project){row.reject(new Error('Predecessor tasks could not be loaded.'));return;}
      row.resolve((response.tasks ?? []).map(task=>({id:String(task.id),name:task.task_name})));
    },
    destroy() {
      if(disposed)return;disposed=true;
      for(const row of pending.values())row.reject(new DOMException('Choice reader disposed.','AbortError'));
      pending.clear();
    }
  };
}
