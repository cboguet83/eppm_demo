import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createLifetime} from '../src/workspace/lifetime.js';

function clock() {
  let next=0;const pending=new Map();
  return {AbortController,pending,
    requestAnimationFrame:fn=>{pending.set(++next,fn);return next;},
    setTimeout:fn=>{pending.set(++next,fn);return next;},
    cancelAnimationFrame:id=>pending.delete(id),clearTimeout:id=>pending.delete(id),
    tick(){const work=[...pending.values()];pending.clear();work.forEach(fn=>fn());}};
}

test('lifetime cancels listeners, frames and timers once and prevents late work',()=>{
  const win=clock(),life=createLifetime(win),target=new EventTarget();let calls=0;
  life.listen(target,'change',()=>calls++);target.dispatchEvent(new Event('change'));
  life.frame(()=>calls++);const cancel=life.timeout(()=>calls++,5);cancel();win.tick();
  assert.equal(calls,2);
  life.frame(()=>calls++);life.timeout(()=>calls++,5);const late=[...win.pending.values()];
  life.destroy();life.destroy();assert.equal(win.pending.size,0);
  target.dispatchEvent(new Event('change'));late.forEach(fn=>fn());
  life.frame(()=>calls++);life.timeout(()=>calls++,0);life.listen(target,'change',()=>calls++);
  assert.equal(calls,2);assert.equal(life.disposed,true);
  life.own(()=>calls++);assert.equal(calls,3);
});

test('lifetime releases every owner in reverse order even when cleanup fails',()=>{
  const life=createLifetime(clock()),order=[];
  life.own(()=>order.push(1));const unregister=life.own(()=>order.push('removed'));unregister();
  life.own(()=>{order.push(2);throw new Error('cleanup');});life.own(()=>order.push(3));
  assert.throws(()=>life.destroy(),AggregateError);assert.deepEqual(order,[3,2,1]);life.destroy();
});
