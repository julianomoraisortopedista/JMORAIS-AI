import {BrowserAuth,validateConfig} from './auth.js';
import {WorkspaceClient,launchReference,ApiError} from './client.js';
import {el,labels,navigation,renderView} from './view.js';
/** @typedef {import('./client.js').Viewer} Viewer */
const app=document.querySelector('main');
if(!app)throw new Error('Application shell missing');
const root=app;
/** @type {BrowserAuth|undefined} */ let auth;
/** @type {AbortController|undefined} */ let pending;
let generation=0;
function reset(){generation++;pending?.abort();auth?.logout();root.replaceChildren();}
/** @param {string} message */
function notice(message){const p=el('p',message);p.setAttribute('role','status');return p;}
function login(){root.replaceChildren(el('h1','Clinical Workspace'),notice('Acesse com sua identidade institucional.'));
 const b=el('button','Entrar com OIDC');b.onclick=async()=>{b.setAttribute('disabled','');try{if(auth)location.assign(await auth.begin());}catch{root.append(notice('Autenticação indisponível. Verifique a configuração.'));b.removeAttribute('disabled');}};root.append(b);}
async function shell(){
 if(!auth)return;
 const session=auth;
 const client=new WorkspaceClient(()=>session.bearer());
 const context=await client.context();
 root.replaceChildren();
 const header=el('header');header.append(el('strong','JMORAIS-AI'),el('span','Workspace clínico • Somente leitura'));
 const exit=el('button','Sair');exit.onclick=()=>{reset();login();};header.append(exit);root.append(header);
 root.append(el('h1','Clinical Workspace'),el('p',`${context.caller_id} · ${context.organization_id} · ${context.role}`));
 const layout=el('div');layout.className='workspace';const nav=navigation();layout.append(nav);
 const content=el('article');content.setAttribute('aria-live','polite');layout.append(content);root.append(layout);
 content.append(el('h2','Abrir contexto autorizado'),el('p','Selecione a referência de launch emitida pela aplicação autorizada. Nenhum paciente ou versão será inferido.'));
 const label=el('label','Arquivo de referência do launch');const input=document.createElement('input');input.type='file';input.accept='.json,application/json';input.id='launch-file';label.setAttribute('for',input.id);content.append(label,input);
 /** @type {import('./client.js').Bootstrap|undefined} */ let bootstrap;
 /** @param {Viewer} viewer */
 const show=async(viewer)=>{if(!bootstrap)return;pending?.abort();pending=new AbortController();const turn=++generation;
   for(const b of nav.querySelectorAll('button'))b.setAttribute('aria-current',b.dataset.viewer===viewer?'page':'false');
   content.replaceChildren(el('h2',labels[viewer]),notice('Carregando…'));
   const reference=bootstrap.references[viewer];
   if(!reference){content.replaceChildren(el('h2',labels[viewer]),notice('Não há referência autorizada para este viewer neste launch.'));return;}
   try{const data=await client.view(viewer,reference,pending.signal);if(turn!==generation)return;content.replaceChildren(el('h2',labels[viewer]),renderView(viewer,data));}
   catch(e){if(turn!==generation)return;if(e instanceof ApiError && e.status===401){reset();login();return;}content.replaceChildren(el('h2',labels[viewer]),notice(e instanceof ApiError?e.message:'Não foi possível carregar os dados.'));}
 };
 for(const b of nav.querySelectorAll('button'))b.onclick=()=>show(/** @type {Viewer} */(b.dataset.viewer));
 input.onchange=async()=>{const file=input.files?.[0];if(!file)return;const turn=++generation;
   try{if(file.size>4096)throw new ApiError(422);const reference=launchReference(JSON.parse(await file.text()));input.value='';
     const result=await client.bootstrap(reference);if(turn!==generation)return;bootstrap=result;await show('summary');}
   catch(e){if(turn!==generation)return;input.value='';content.append(notice(e instanceof ApiError?e.message:'Referência de abertura inválida.'));}
 };
}
try{
 const r=await fetch('/workspace-config.json',{cache:'no-store',credentials:'omit',redirect:'error'});
 if(!r.ok)throw new Error();
 auth=new BrowserAuth(validateConfig(await r.json(),location.origin),sessionStorage);
 const callback=new URL(location.href);
 if(callback.searchParams.has('code')||callback.searchParams.has('error')){
   await auth.callback(callback,path=>history.replaceState(null,'',path));await shell();
 }else login();
}catch{
 // Clear callback parameters even when runtime configuration is unavailable.
 if(location.search)history.replaceState(null,'',location.pathname);
 auth?.logout();root.replaceChildren(el('h1','Clinical Workspace'),notice('Indisponível: configuração OIDC ausente, inválida ou autenticação rejeitada.'));
}
