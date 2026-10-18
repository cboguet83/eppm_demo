/** Streamlit v1 transport; core modules never import or depend on this bridge. */
import {mountPlanningView} from '../index.js';
import {validateEvent,ContractError} from '../contracts/index.js';
import {createLifetime} from '../workspace/lifetime.js';
import {ownMessage} from '../contracts/owned.js';

/** Connect a supplied root to one Streamlit parent with lossless queued delivery.
 * @param {HTMLElement} root Owned host element.
 * @param {{mount?:Function,onError?:Function,prepareRender?:Function,encodeEvent?:Function}} options Host normalization seams; core contracts remain validated.
 * @returns {{destroy:Function}} Idempotent bridge disposal.
 */
export function connectStreamlit(root,{mount=mountPlanningView,onError=()=>{},prepareRender=args=>args,encodeEvent=event=>event}={}) {
  const win=root.ownerDocument.defaultView,lifetime=createLifetime(win),reads=new Map(),writes=new Map();
  let origin=null,instance=null,snapshotKey=null,snapshotText=null,optionsKey=null,messagesKey=null,queue=[],inFlight=null,scope=null,revision=null;
  const send=(type,fields={})=>{if(!lifetime.disposed)win.parent.postMessage({isStreamlitMessage:true,type,...fields},origin ?? '*');};
  const flush=()=>{
    if(inFlight || !queue.length || lifetime.disposed)return;
    const value=encodeEvent(queue[0]);
    inFlight=queue[0].requestId;send('streamlit:setComponentValue',{value,dataType:'json'});
  };
  const enqueue=input=>{
    if(lifetime.disposed)return;
    const event=validateEvent(input);
    if(['dates','progress','task','dependency'].includes(event.type))writes.set(event.requestId,event);
    if(queue.some(row=>row.requestId===event.requestId))return;
    if(event.type==='load')queue.push(event);
    else {
      const index=queue.findIndex(row=>row.requestId!==inFlight && row.type==='load');
      if(index<0)queue.push(event);else queue.splice(index,0,event);
    }
    flush();
  };
  const load=request=>new Promise((resolve,reject)=>{
    const abort=()=>{
      reads.delete(request.requestId);queue=queue.filter(row=>row.requestId===inFlight || row.requestId!==request.requestId);
      reject(new win.DOMException('Planning read cancelled.','AbortError'));
    };
    if(request.signal.aborted){abort();return;}
    const finish=()=>request.signal.removeEventListener('abort',abort);
    reads.set(request.requestId,{resolve:value=>{finish();resolve(value);},reject:error=>{finish();reject(error);}});
    request.signal.addEventListener('abort',abort,{once:true});
    enqueue({version:1,type:'load',scope:request.scope,revision:request.revision,requestId:request.requestId,projectIds:request.projectIds});
  });
  const apply=input=>{
    const message=ownMessage(input),pending=reads.get(message.requestId);
    if(message.kind==='response')writes.delete(message.requestId);
    if(pending) {
      reads.delete(message.requestId);
      if(message.kind==='patch')pending.resolve(message);
      else pending.reject(new Error('The planning read was rejected.'));
    }else instance.update(message);
  };
  lifetime.listen(win,'message',event=>{
    if(event.source!==win.parent || (origin!==null && event.origin!==origin) || event.data?.type!=='streamlit:render')return;
    try {
      const args=prepareRender(event.data.args,{emit:enqueue});
      if(args===null && event.data.args!==null)return; // Host may request its missing initial payload first.
      if(!args || !Array.isArray(args.messages ?? []) || !Array.isArray(args.ackRequestIds ?? []) || (args.ackRequestIds ?? []).some(id=>typeof id!=='string'))throw new ContractError('streamlit.args');
      if(args.lazy!==undefined && typeof args.lazy!=='boolean')throw new ContractError('streamlit.lazy');
      if(args.options!==undefined && (!args.options || typeof args.options!=='object' || Array.isArray(args.options)))throw new ContractError('streamlit.options');
      const snapshot=ownMessage(args.snapshot);
      if(snapshot.kind!=='snapshot')throw new ContractError('streamlit.snapshot');
      const updates=(args.messages ?? []).map(ownMessage);
      const nextOptionsKey=JSON.stringify([args.options ?? {},!!args.lazy]);
      const changedSnapshot=snapshotKey!==snapshot && snapshotKey!==null &&
        (snapshotText ??=JSON.stringify(snapshotKey))!==JSON.stringify(snapshot);
      origin=event.origin;
      // A new scope invalidates unsent intentions; an already delivered head still
      // waits for its acknowledgement, preventing channel overwrite.
      if(scope!==null && (scope!==snapshot.scope || revision!==snapshot.revision)) {
        queue=queue.filter(row=>row.requestId===inFlight);
        for(const [id,request] of writes) {
          if(updates.some(update=>update.kind==='response' && update.requestId===id))continue;
          instance?.update({version:1,kind:'response',scope:request.scope,revision:request.revision,requestId:id,accepted:false,error:'The view changed before this request completed.'});
          writes.delete(id);
        }
      }
      scope=snapshot.scope;revision=snapshot.revision;
      const acknowledgements=new Set(args.ackRequestIds ?? []);
      queue=queue.filter(row=>!acknowledgements.has(row.requestId));
      if(acknowledgements.has(inFlight))inFlight=null;
      if(!instance || optionsKey!==nextOptionsKey) {
        const previous=instance;
        const replacement=mount(root,{...args.options,snapshot,onEvent:enqueue,onHeight:height=>send('streamlit:setFrameHeight',{height}),
          ...(args.lazy?{load}:{}),onLoadError:error=>onError(error)});
        previous?.destroy();instance=replacement;
        optionsKey=nextOptionsKey;snapshotKey=snapshot;snapshotText=null;messagesKey=null;
      }else if(changedSnapshot){instance.update(snapshot);snapshotKey=snapshot;snapshotText=null;messagesKey=null;}
      const nextMessagesKey=JSON.stringify(updates);
      if(messagesKey!==nextMessagesKey){for(const message of updates)apply(message);messagesKey=nextMessagesKey;}
      flush();
    }catch(error) {
      if(!(error instanceof ContractError))throw error;
      onError({code:'invalid_contract',message:'The planning display received invalid data.'});
    }
  });
  lifetime.own(()=>{instance?.destroy();instance=null;for(const read of reads.values())read.reject(new win.DOMException('Planning display disposed.','AbortError'));reads.clear();writes.clear();queue=[];});
  lifetime.listen(win,'pagehide',()=>lifetime.destroy());
  send('streamlit:componentReady',{apiVersion:1});
  return {destroy(){lifetime.destroy();}};
}
