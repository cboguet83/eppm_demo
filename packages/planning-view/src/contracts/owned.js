/** Internal ownership transfer: only this module can brand validated frozen data. */
import {validateMessage} from './index.js';

const owned=new WeakSet();

/** Validate and freeze an independent copy, or retain a previously owned graph.
 * Caller-created frozen objects still undergo complete validation and cloning.
 * @param {unknown} input Untrusted message or already owned immutable message.
 * @returns {object} Checked, deeply frozen, independently owned message.
 */
export function ownMessage(input) {
  if(input && typeof input==='object' && owned.has(input))return input;
  const message=validateMessage(input),pending=[message],seen=new WeakSet();
  while(pending.length) {
    const node=pending.pop();
    if(node===null || typeof node!=='object' || seen.has(node))continue;
    seen.add(node);for(const child of Object.values(node))if(child!==null && typeof child==='object')pending.push(child);
    Object.freeze(node);
  }
  owned.add(message);return message;
}
