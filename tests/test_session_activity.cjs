const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../app/presentation/components/authentication.py'),'utf8');
const script=source.match(/_SESSION_JS = """([\s\S]*?)"""/)[1].replace('export default function','function mount');

function harness(){
  const document=()=>({listeners:new Map(),addEventListener(type,handler,options){
    if(!this.listeners.has(type))this.listeners.set(type,{handlers:new Set(),options});
    this.listeners.get(type).handlers.add(handler);
  },removeEventListener(type,handler){
    const handlers=this.listeners.get(type)?.handlers;handlers?.delete(handler);
    if(!handlers?.size)this.listeners.delete(type);
  }});
  const main=document(),child=document(),frame={...document(),contentDocument:child};
  let root={dataset:{},replaceChildren(child){child.parentElement=this;this.child=child;}};
  const parentElement={querySelector:()=>root};
  const requests=[],reloads=[];
  let now=20000,response={ok:true,json:async()=>({status:'active'})};
  const polls=new Set();
  Object.assign(main,{createElement:()=>({}),querySelectorAll:()=>[frame],body:{}});
  const context=vm.createContext({document:main,Date:{now:()=>now},
    window:{...document(),location:{replace:url=>reloads.push(url)}},localStorage:{setItem(){}},
    MutationObserver:class{observe(){}disconnect(){}},setInterval:fn=>{polls.add(fn);return fn;},clearInterval:fn=>polls.delete(fn),
    fetch:async(url,options)=>{requests.push({url,options});if(response instanceof Error)throw response;return response;},
  });
  vm.runInContext(script,context);
  const mount=(data={status:'active',logout:'Sign out'})=>context.mount({data,parentElement});
  const cleanup=mount();
  return {main,child,root,requests,reloads,cleanup,mount,polls,poll:()=>Promise.all([...polls].map(fn=>fn())),
    replaceRoot:()=>{root={dataset:{},replaceChildren(child){child.parentElement=this;this.child=child;}};return root;},
    advance:()=>{now+=10000;},respond:value=>{response=value;},
    wheel:(doc,trusted=true)=>Promise.all([...doc.listeners.get('wheel').handlers].map(fn=>fn({isTrusted:trusted}))),};
}

test('repeated component renders keep one listener set and poll and preserve activity throttling',async()=>{
  const h=harness();
  await h.wheel(h.child);
  for(let index=0;index<40;index++)assert.equal(h.mount(),h.cleanup);
  assert.equal(h.polls.size,1);
  assert.equal(h.main.listeners.get('wheel').handlers.size,1);
  assert.equal(h.child.listeners.get('wheel').handlers.size,1);
  await h.wheel(h.child);
  assert.equal(h.requests.length,1);
  h.advance();await h.wheel(h.main);
  assert.equal(h.requests.length,2);
  const root=h.replaceRoot();
  h.mount({status:'pending',logout:'Logout'});
  assert.equal(root.child.textContent,'Logout');
  h.respond({ok:true,json:async()=>({status:'pending'})});
  await h.poll();assert.equal(h.reloads.length,0);
  h.cleanup();assert.equal(h.polls.size,0);
  assert.equal(h.main.listeners.size,0);assert.equal(h.child.listeners.size,0);
  h.mount();h.cleanup(); // An old cleanup must not dispose a new mount.
  assert.equal(h.polls.size,1);
});

test('slow activity and session requests remain single flight across component renders',async()=>{
  const h=harness();let finish;
  h.respond(new Promise(resolve=>{finish=resolve;}));
  const activity=h.wheel(h.child),poll=h.poll();
  h.advance();h.mount();
  await h.wheel(h.main);await h.poll();
  assert.deepEqual(h.requests.map(request=>request.url),['/auth/activity','/auth/session']);
  h.cleanup();
  finish({ok:false,status:401});
  await activity;await poll;
  assert.equal(h.reloads.length,0);
});

test('trusted wheel input in both page and chart counts as activity without blocking scrolling',async()=>{
  const h=harness();
  assert.equal(h.main.listeners.get('wheel').options.passive,true);
  await h.wheel(h.main,false);
  assert.equal(h.requests.length,0);
  await h.wheel(h.main);
  await h.wheel(h.child);
  assert.equal(h.requests.length,1); // Throttled across documents.
  h.advance();await h.wheel(h.child);
  assert.equal(h.requests.length,2);
  assert.ok(h.requests.every(request=>request.url==='/auth/activity'));
  await h.poll();
  assert.equal(h.requests.at(-1).url,'/auth/session');
  h.cleanup();
  assert.equal(h.main.listeners.size,0);
  assert.equal(h.child.listeners.size,0);
});

for(const response of [{ok:false,status:503},new Error('temporary network interruption')])
test(`temporary session failures retain the page and retry: ${response.status||'network'}`,async()=>{
  const h=harness();h.respond(response);
  await h.wheel(h.child);await h.poll();
  assert.equal(h.reloads.length,0);
  assert.equal(h.root.dataset.sessionConnection,'retrying');
  h.respond({ok:true,json:async()=>({status:'active'})});
  await h.poll();
  assert.equal(h.root.dataset.sessionConnection,undefined);
  assert.equal(h.reloads.length,0);
});

for(const status of [401,403]) test(`explicit session denial still closes the page: ${status}`,async()=>{
  const h=harness();h.respond({ok:false,status});
  await h.poll();assert.equal(h.reloads.length,1);
  await h.wheel(h.child);assert.equal(h.reloads.length,2);
});

test('a confirmed account-status change still leaves the protected page',async()=>{
  const h=harness();h.respond({ok:true,json:async()=>({status:'disabled'})});
  await h.poll();assert.equal(h.reloads.length,1);
});
