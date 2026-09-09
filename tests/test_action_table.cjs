const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../app/presentation/components/action_table.py'),'utf8');
const script = source.match(/_TABLE_JS = r"""([\s\S]*?)"""/)[1].replace('export default function','function mount');

test('row actions render untrusted labels as text and send the clicked row identity',()=>{
  function element(tag) {
    return {tag,children:[],attributes:{},textContent:'',
      appendChild(child){this.children.push(child);},replaceChildren(){this.children=[];},
      setAttribute(key,value){this.attributes[key]=value;},
      set innerHTML(value){throw Error('Unsafe HTML assignment');}};
  }
  const root=element('div'),events=[];
  const context=vm.createContext({document:{createElement:element}});
  vm.runInContext(script,context);
  context.mount({data:{columns:[['name','Project']],action_label:'Actions',actions:{open:'Open',unassign:'Unassign'},
    rows:[{id:4,name:'<script>alert(1)</script>'},{id:9,name:'<img onerror=alert(1)>'}]},
    parentElement:{querySelector:()=>root},setTriggerValue:(key,value)=>events.push({key,...value})});
  const rows=root.children[0].children[1].children;
  assert.equal(rows[0].children[0].textContent,'<script>alert(1)</script>');
  assert.equal(rows[1].children[0].textContent,'<img onerror=alert(1)>');
  rows[1].children[1].children[1].onclick();
  rows[0].children[1].children[0].onclick();
  assert.deepEqual(events,[{key:'action',id:9,action:'unassign'},{key:'action',id:4,action:'open'}]);
  assert.equal(rows[1].children[1].children[1].attributes['aria-label'],'Unassign: 9');
});
