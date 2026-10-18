/** Thin EPPM composition root over the independent browser/Streamlit packages. */
import {connectStreamlit} from './planning-view/src/adapters/streamlit.js';
import {mountPlanningView} from './planning-view/src/index.js';
import {createLifetime} from './planning-view/src/workspace/lifetime.js';
import {createTaskProvider,createEppmTransport} from './eppm-transport.js';
import {createChoiceReader} from './eppm-choices.js';
import {createProjectEditor} from './eppm-project-editor.js';
import {planningCommands,confirmedCommand} from './eppm-commands.js';

const root=document.querySelector('[data-eppm-planning]'),notice=document.querySelector('[data-eppm-error]');
let active=null;
const transport=createEppmTransport({receive:(kind,response)=>{
  if(kind==='choices')active?.choices.receive(response);else active?.projectEditor.receive(response);
}});
connectStreamlit(root,{
  prepareRender(args,callbacks) {
    const result=transport.prepareRender(args,callbacks);active?.projectEditor.refresh();return result;
  },
  encodeEvent:event=>transport.encodeEvent(event),
  onError:error=>{notice.textContent=error.message;notice.hidden=false;},
  mount(owner,options) {
    const lifetime=createLifetime(window),choices=createChoiceReader(transport);
    const provider=createTaskProvider({host:transport.host,refresh:()=>transport.event('initialize_planning')});
    let projectEditor=null;
    const view=mountPlanningView(owner,{...options,contextActions:planningCommands(),dependencyEditor:'successor',projectDependenciesCommand:'project_dependencies',
      load:async request=>{const patch=await provider(request);transport.loadedPatch(patch);return patch;},
      loadChoices:request=>choices.read(request),
      onEvent:event=>{
        if(event.type==='command' && event.command==='project_dependencies'){projectEditor?.open(event.context?.projectId ?? event.targetId);return;}
        const confirmed=confirmedCommand(event,transport.host(),window);
        return confirmed?options.onEvent(confirmed):false;
      }});
    const frame=owner.querySelector('.planning-view:last-child');
    projectEditor=createProjectEditor({frame,transport,choices,lifetime});
    const service={choices,projectEditor};active=service;
    lifetime.own(()=>choices.destroy());lifetime.own(()=>view.destroy());
    return {
      update(message){notice.hidden=true;return view.update(message);},
      destroy(){lifetime.destroy();if(active===service)active=null;}
    };
  }
});
