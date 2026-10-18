import {test} from 'node:test';
import assert from 'node:assert/strict';
import {connectStreamlit} from '../src/adapters/streamlit.js';

const snapshot=()=>({version:1,kind:'snapshot',scope:'s',revision:'r',projects:[],tasks:[]});
const command=id=>({version:1,scope:'s',revision:'r',requestId:id,type:'command',command:'host'});
function harness() {
  const win=new EventTarget(),sent=[],mounts=[],updates=[],errors=[];
  Object.assign(win,{AbortController,DOMException,parent:{postMessage:(message,origin)=>sent.push({message,origin})}});
  const root={ownerDocument:{defaultView:win}};
  const bridge=connectStreamlit(root,{mount:(root,options)=>{
    const record={options,disposed:false};mounts.push(record);
    return {update:message=>updates.push(message),destroy:()=>{record.disposed=true;}};
  },onError:error=>errors.push(error)});
  const render=(args={snapshot:snapshot()},extra={})=>{
    const event=new Event('message');Object.defineProperties(event,Object.fromEntries(Object.entries({source:win.parent,origin:'http://host',data:{type:'streamlit:render',args},...extra}).map(([key,value])=>[key,{value}])));win.dispatchEvent(event);
  };
  const values=()=>sent.filter(row=>row.message.type==='streamlit:setComponentValue').map(row=>row.message.value);
  return {win,bridge,sent,mounts,updates,errors,render,values};
}

test('bridge mounts once, deduplicates snapshots, pins parent origin and disposes idempotently',()=>{
  const h=harness();assert.equal(h.sent[0].message.type,'streamlit:componentReady');assert.equal(h.sent[0].origin,'*');
  h.render();h.render();assert.equal(h.mounts.length,1);assert.equal(h.updates.length,0);
  h.mounts[0].options.onHeight(500);assert.equal(h.sent.at(-1).message.height,500);assert.equal(h.sent.at(-1).origin,'http://host');
  h.render({snapshot:{...snapshot(),revision:'next'}});assert.equal(h.updates.length,1);
  h.render(undefined,{source:{}});h.render(undefined,{origin:'http://other'});h.render(undefined,{data:{type:'other'}});
  assert.equal(h.updates.length,1);
  h.render({snapshot:snapshot(),options:{mode:'Day'}});assert.equal(h.mounts[0].disposed,true);assert.equal(h.mounts.length,2);
  h.bridge.destroy();h.bridge.destroy();h.mounts[1].options.onHeight(600);h.render();assert.equal(h.mounts.length,2);
  assert.equal(h.mounts[1].disposed,true);
});

test('action/read queue waits for acknowledgement and prioritizes unsent user actions',async()=>{
  const h=harness();h.render({snapshot:snapshot(),lazy:true});const options=h.mounts[0].options;
  options.onEvent(command('first'));options.onEvent(command('first'));
  const controller=new AbortController(),read=options.load({scope:'s',revision:'r',requestId:'read',projectIds:['opaque'],signal:controller.signal});
  options.onEvent(command('second'));assert.deepEqual(h.values().map(event=>event.requestId),['first']);
  h.render({snapshot:snapshot(),lazy:true,ackRequestIds:['first']});assert.deepEqual(h.values().map(event=>event.requestId),['first','second']);
  h.render({snapshot:snapshot(),lazy:true,ackRequestIds:['second']});assert.equal(h.values().at(-1).type,'load');
  const patch={version:1,kind:'patch',scope:'s',revision:'r',requestId:'read',replaceProjectIds:['opaque'],tasks:[]};
  h.render({snapshot:snapshot(),lazy:true,messages:[patch],ackRequestIds:['read']});assert.deepEqual(await read,patch);assert.equal(h.updates.length,0);
  h.render({snapshot:snapshot(),lazy:true,messages:[patch],ackRequestIds:['read']});assert.equal(h.updates.length,0);
  h.bridge.destroy();
});

test('read rejection and cancellation do not overwrite queued action delivery',async()=>{
  const h=harness();h.render({snapshot:snapshot(),lazy:true});const options=h.mounts[0].options;
  const controller=new AbortController(),read=options.load({scope:'s',revision:'r',requestId:'read',projectIds:['p'],signal:controller.signal});
  h.render({snapshot:snapshot(),lazy:true,messages:[{version:1,kind:'response',scope:'s',revision:'r',requestId:'read',accepted:false}]});
  await assert.rejects(read,/rejected/);
  const cancelled=new AbortController();cancelled.abort();await assert.rejects(options.load({scope:'s',revision:'r',requestId:'cancelled',projectIds:['p'],signal:cancelled.signal}),{name:'AbortError'});
  const pending=new AbortController(),aborted=options.load({scope:'s',revision:'r',requestId:'abort',projectIds:['p'],signal:pending.signal});pending.abort();await assert.rejects(aborted,{name:'AbortError'});
  const waiting=options.load({scope:'s',revision:'r',requestId:'dispose',projectIds:['p'],signal:new AbortController().signal});
  h.bridge.destroy();await assert.rejects(waiting,{name:'AbortError'});
  options.onEvent(command('late'));assert.equal(h.values().length,1);
});

test('malformed transport is rejected before mounting while stale writes are reconciled on revisions',()=>{
  const h=harness();
  for(const args of [null,{}, {snapshot:snapshot(),messages:{}},{snapshot:snapshot(),ackRequestIds:[1]},
    {snapshot:snapshot(),lazy:'yes'},{snapshot:snapshot(),options:[]},{snapshot:{...snapshot(),kind:'patch'}}])h.render(args);
  assert.equal(h.mounts.length,0);assert.equal(h.errors.length,7);assert.ok(h.errors.every(error=>error.code==='invalid_contract'));
  h.render();h.mounts[0].options.onEvent({version:1,scope:'s',revision:'r',requestId:'edit',type:'progress',targetId:'task',progress:50});
  h.render({snapshot:{...snapshot(),revision:'next'},ackRequestIds:['edit']});
  assert.equal(h.updates[0].kind,'response');assert.equal(h.updates[0].accepted,false);
  assert.equal(h.updates[1].revision,'next');
  h.win.dispatchEvent(new Event('pagehide'));assert.equal(h.mounts[0].disposed,true);
});

test('host codecs translate partial reruns and wire events while core contracts stay checked',()=>{
  const win=new EventTarget(),sent=[],updates=[];
  Object.assign(win,{AbortController,DOMException,parent:{postMessage:message=>sent.push(message)}});
  let emit=null,mounted=null;
  const bridge=connectStreamlit({ownerDocument:{defaultView:win}},{
    prepareRender:(args,callbacks)=>{emit=callbacks.emit;return args?.initial?{snapshot:snapshot(),ackRequestIds:args.ack?[args.ack]:[]}:null;},
    encodeEvent:event=>({action:event.command,nonce:event.requestId}),
    mount:(root,options)=>{mounted=options;return {update:message=>updates.push(message),destroy:()=>{}};}
  });
  const render=args=>{const event=new Event('message');Object.defineProperties(event,{source:{value:win.parent},origin:{value:'https://host'},data:{value:{type:'streamlit:render',args}}});win.dispatchEvent(event);};
  render({});assert.equal(mounted,null);emit(command('initialize'));assert.equal(sent.at(-1).value.action,'host');
  render({initial:true,ack:'initialize'});mounted.onEvent(command('edit'));
  assert.deepEqual(sent.at(-1).value,{action:'host',nonce:'edit'});assert.equal(updates.length,0);bridge.destroy();
});
