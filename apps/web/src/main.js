import {BrowserAuth,validateConfig} from './auth.js';
import {WorkspaceClient,launchReference,ApiError} from './client.js';
import {el,labels,navigation,renderView} from './view.js';
import {EvidenceClient,EvidenceError,box,button,documentPage,evidencePage,pill,session} from './evidence.js';
import {icon} from './icons.js';
import {casePage,clearCase} from './case.js';
import {catalogPage} from './catalog.js';
/** @typedef {import('./client.js').Viewer} Viewer */
const app=document.querySelector('main');
if(!app)throw new Error('Application shell missing');
const root=app;
/** @type {BrowserAuth|undefined} */ let auth;
/** @type {AbortController|undefined} */ let pending;
let generation=0;
function reset(){generation++;pending?.abort();auth?.logout();session.claim='';session.decisions=[];clearCase();root.replaceChildren();document.body.className='';}
/** @param {string} message */
function notice(message){const p=el('p',message);p.setAttribute('role','status');return p;}

/** @type {Record<string,string>} */
const ROLE={CLINICAL_REVIEWER:'Revisor clínico',CLINICAL_REVIEW:'Revisão clínica',ADMINISTRATOR:'Administrador',INTERNAL_SERVICE:'Serviço interno'};

function brand(){const b=box('div','brand');b.append(box('span','brand-mark','J'),box('span','brand-name','JMORAIS'),box('span','brand-suffix','AI'));return b;}

function login(){
 document.body.className='is-login';
 const hero=box('section','login-hero');
 hero.append(brand(),box('h1','login-title','Fundamentação clínica baseada em evidências'),
   box('p','login-lead','Busca científica verificada, classificação assistida por IA com confirmação médica e documento técnico-jurídico para o convênio.'));
 const points=box('ul','login-points');
 for(const t of ['Referências conferidas no PubMed e no Crossref','Trechos literais, sem conteúdo inventado','Requisitos do STF (ADI 7.265) verificados um a um'])points.append(el('li',t));
 hero.append(points);
 const card=box('section','login-card');
 card.append(box('h2','login-card-title','Acesso seguro'),notice('Entre com a sua identidade institucional.'));
 const b=button('Entrar');b.classList.add('btn-wide');
 b.onclick=async()=>{b.setAttribute('disabled','');try{if(auth)location.assign(await auth.begin());}catch{card.append(box('div','alert alert-error','Autenticação indisponível. Verifique a configuração.'));b.removeAttribute('disabled');}};
 card.append(b,box('p','login-foot','Uso clínico restrito. Sessão protegida por OIDC + PKCE.'));
 const wrap=box('div','login');wrap.append(hero,card);root.replaceChildren(wrap);
}

async function shell(){
 if(!auth)return;
 const current=auth;
 const client=new WorkspaceClient(()=>current.bearer());
 const evidence=new EvidenceClient(()=>current.bearer());
 const context=await client.context();
 try{session.model=Boolean((await evidence.status()).model_configured);}catch{session.model=false;}
 document.body.className='is-app';
 const side=box('aside','sidebar');side.append(brand());
 const menu=el('nav');menu.setAttribute('aria-label','Seções da plataforma');menu.className='menu';
 /** @type {[string,string,string][]} */
 const pages=[['overview','Visão geral','home'],['case','Pedido médico','clipboard'],['catalog','Modelos de cirurgia','file'],['patients','Pacientes','user'],['evidence','Evidências','search'],['document','Documento ao convênio','file']];
 /** @type {Record<string,HTMLButtonElement>} */ const items={};
 for(const [key,label,ic] of pages){const b=button('','quiet');b.className='menu-item';b.dataset.page=key;b.setAttribute('aria-label',label);b.append(icon(ic),el('span',label));items[key]=b;menu.append(b);}
 const who=box('div','side-foot');who.append(box('strong','',context.caller_id),box('span','muted',context.organization_id+' · '+(ROLE[context.role]||context.role)));
 side.append(menu,who);
 const main=box('div','main');
 const top=box('header','topbar');const title=box('h1','page-title','');
 const ai=session.model?pill('Claude conectado','SUPPORTING'):pill('IA em modo manual','muted');
 const exit=button('Sair','ghost');exit.onclick=()=>{reset();login();};
 const tools=box('div','top-tools');tools.append(ai,exit);top.append(title,tools);
 const content=box('section','content');content.setAttribute('aria-live','polite');
 main.append(top,content);
 const layout=box('div','layout');layout.append(side,main);root.replaceChildren(layout);
 /** @type {HTMLElement|undefined} */ let patientsView;
 const counts={decisions:0};
 /** @param {string} key */
 const go=(key)=>{
   for(const [k,b] of Object.entries(items))b.setAttribute('aria-current',k===key?'page':'false');
   title.textContent=(pages.find(p=>p[0]===key)||pages[0])[1];
   if(key==='overview')content.replaceChildren(overview(context,counts.decisions,go));
   else if(key==='patients'){patientsView=patientsView||patients(client);content.replaceChildren(patientsView);}
   else if(key==='evidence')content.replaceChildren(evidencePage(evidence,n=>{counts.decisions=n;}));
   else if(key==='case')content.replaceChildren(casePage(evidence));
   else if(key==='catalog')content.replaceChildren(catalogPage(evidence));
   else content.replaceChildren(documentPage(evidence));
 };
 for(const [k,b] of Object.entries(items))b.onclick=()=>go(k);
 go('overview');
}

/** @param {import('./client.js').Caller} context @param {number} decisions @param {(k:string)=>void} go */
function overview(context,decisions,go){
 const page=box('div','page-grid');
 const hello=box('section','card card-hero');
 hello.append(box('h2','card-title','Bem-vindo'),box('p','muted',`${context.caller_id} · ${context.organization_id}`),
   box('p','','Fluxo recomendado: defina a pergunta clínica, confirme as evidências e gere o documento técnico para o convênio.'));
 const stats=box('div','stats');
 /** @param {string} label @param {string} value @param {string} hint */
 const stat=(label,value,hint)=>{const s=box('div','stat');s.append(box('span','stat-label',label),box('strong','stat-value',value),box('span','muted',hint));return s;};
 stats.append(stat('Decisões confirmadas',String(decisions),'nesta sessão'),stat('Assistente de IA',session.model?'Claude':'Manual',session.model?'sugestões com confirmação médica':'classificação pelo médico'),stat('Escopo de acesso',ROLE[context.role]||context.role,ROLE[context.purpose]||context.purpose));
 const steps=box('div','steps');
 /** @type {[string,string,string,string][]} */
 const flow=[['1','Pedido médico','Envie laudos e história; a IA extrai os fatos sem identificar o paciente.','case'],['2','Evidências','Busque, leia e confirme os artigos.','evidence'],['3','Documento','Gere a fundamentação técnico-jurídica.','document']];
 for(const [n,t,d,k] of flow){
   const s=box('button','step');s.setAttribute('type','button');s.setAttribute('aria-label',`Passo ${n}: ${t}`);s.append(box('span','step-n',n),box('strong','',t),box('span','muted',d));s.onclick=()=>go(k);steps.append(s);
 }
 page.append(hello,stats,steps);return page;
}

/** @param {WorkspaceClient} client */
function patients(client){
 const page=box('div','page-grid');
 const opener=box('section','card');
 opener.append(box('h2','card-title','Abrir contexto autorizado'),box('p','muted','Selecione a referência de launch emitida pela aplicação autorizada. Nenhum paciente ou versão será inferido.'));
 const label=el('label','Arquivo de referência do launch');const input=document.createElement('input');input.type='file';input.accept='.json,application/json';input.id='launch-file';label.setAttribute('for',input.id);
 const drop=box('div','file-drop');drop.append(icon('upload'),label,input);opener.append(drop);
 const viewer=box('section','card viewer');const nav=navigation();nav.className='viewer-nav';
 const content=box('article','viewer-body');content.setAttribute('aria-live','polite');
 viewer.append(nav,content);content.append(box('p','muted','Os visualizadores ficam disponíveis após abrir um contexto.'));
 page.append(opener,viewer);
 /** @type {import('./client.js').Bootstrap|undefined} */ let bootstrap;
 /** @param {Viewer} name */
 const show=async(name)=>{if(!bootstrap)return;pending?.abort();pending=new AbortController();const turn=++generation;
   for(const b of nav.querySelectorAll('button'))b.setAttribute('aria-current',b.dataset.viewer===name?'page':'false');
   content.replaceChildren(el('h2',labels[name]),notice('Carregando…'));
   const reference=bootstrap.references[name];
   if(!reference){content.replaceChildren(el('h2',labels[name]),notice('Não há referência autorizada para este viewer neste launch.'));return;}
   try{const data=await client.view(name,reference,pending.signal);if(turn!==generation)return;content.replaceChildren(el('h2',labels[name]),renderView(name,data));}
   catch(e){if(turn!==generation)return;if(e instanceof ApiError && e.status===401){reset();login();return;}content.replaceChildren(el('h2',labels[name]),notice(e instanceof ApiError?e.message:'Não foi possível carregar os dados.'));}
 };
 for(const b of nav.querySelectorAll('button'))b.onclick=()=>show(/** @type {Viewer} */(b.dataset.viewer));
 input.onchange=async()=>{const file=input.files?.[0];if(!file)return;const turn=++generation;
   try{if(file.size>4096)throw new ApiError(422);const reference=launchReference(JSON.parse(await file.text()));input.value='';
     const result=await client.bootstrap(reference);if(turn!==generation)return;bootstrap=result;await show('summary');}
   catch(e){if(turn!==generation)return;input.value='';content.replaceChildren(notice(e instanceof ApiError?e.message:'Referência de abertura inválida.'));}
 };
 return page;
}

window.addEventListener('unhandledrejection',(event)=>{
 if(event.reason instanceof EvidenceError && event.reason.status===401){reset();login();}
});
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
 auth?.logout();root.replaceChildren(el('h1','JMORAIS'),notice('Indisponível: configuração OIDC ausente, inválida ou autenticação rejeitada.'));
}
