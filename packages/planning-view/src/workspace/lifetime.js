/** One instance's listeners, scheduled work, observers and disposal callbacks. */

/** @param {Window} win Owning browser window or deterministic scheduler adapter. */
export function createLifetime(win) {
  const controller=new win.AbortController(),cleanup=new Set();
  let disposed=false;
  /** @param {Function} callback Cleanup. @returns {Function} Remove registration. */
  const own=callback=>{
    if(disposed){callback();return ()=>{};}
    cleanup.add(callback);return ()=>cleanup.delete(callback);
  };
  /** @param {Function} callback Scheduled work. @param {boolean} frame Animation-frame mode. @param {number} delay Timeout delay. */
  const scheduled=(callback,frame,delay)=>{
    if(disposed) return ()=>{};
    const run=()=>{unregister();if(!disposed)callback();};
    const handle=frame?win.requestAnimationFrame(run):win.setTimeout(run,delay);
    const cancel=()=>{unregister();if(frame)win.cancelAnimationFrame(handle);else win.clearTimeout(handle);};
    const unregister=own(cancel);
    return cancel;
  };
  return {
    own,
    listen(target,type,callback,options={}){
      if(!disposed) target.addEventListener(type,callback,{...options,signal:controller.signal});
    },
    frame(callback){return scheduled(callback,true,0);},
    timeout(callback,delay){return scheduled(callback,false,delay);},
    get disposed(){return disposed;},
    destroy(){
      if(disposed)return;
      disposed=true;controller.abort();
      const failures=[];
      for(const callback of [...cleanup].reverse()) {
        try{callback();}catch(error){failures.push(error);}
      }
      cleanup.clear();
      if(failures.length) throw new AggregateError(failures,'Planning display cleanup failed.');
    }
  };
}
