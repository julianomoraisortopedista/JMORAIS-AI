/** Evidence workbench inside the platform: same bearer, server-side rules, text-only DOM. */
import {el} from './view.js';
import {dictation} from './dictation.js';

export const DIRECTIONS = /** @type {const} */ ({SUPPORTING:'A favor',OPPOSING:'Contra',NEUTRAL:'Neutro',INCONCLUSIVE:'Inconclusivo'});
const REQUIREMENT = /** @type {Record<string,string>} */ ({ATENDIDO:'Atendido',PENDENTE:'Pendente',NAO_ATENDIDO:'Não atendido'});

export class EvidenceError extends Error {
  /** @param {number} status @param {string} [detail] */
  constructor(status,detail){super(detail || (status===401?'Sessão encerrada. Entre novamente.':status===403?'Acesso não autorizado.':'Não foi possível concluir a operação.'));this.status=status;}
}

export class EvidenceClient {
  /** @param {()=>string} bearer @param {typeof fetch} request */
  constructor(bearer,request=(/** @type {RequestInfo|URL} */ input,/** @type {RequestInit|undefined} */ init)=>fetch(input,init)){this.bearer=bearer;this.request=request;}
  /** @param {string} path @param {unknown} [body] @param {string} [method] @returns {Promise<any>} */
  async call(path,body=undefined,method=body===undefined?'GET':'POST'){
    const r=await this.request('/internal/evidence/api/'+path,{method,cache:'no-store',credentials:'omit',redirect:'error',
      headers:{Authorization:'Bearer '+this.bearer(),...(body===undefined?{}:{'Content-Type':'application/json'})},
      body:body===undefined?undefined:JSON.stringify(body)});
    let data=null;try{data=await r.json();}catch{data=null;}
    if(!r.ok){const d=data && data.detail;throw new EvidenceError(r.status,typeof d==='string'?d:Array.isArray(d)?d.map(x=>x.msg).join('; '):undefined);}
    return data;
  }
  status(){return this.call('status');}
  /** @param {Record<string,unknown>} q */ search(q){return this.call('search',q);}
  /** @param {string} identifiers */ importIds(identifiers){return this.call('import',{identifiers});}
  /** @param {string} question @param {string|null} templateId */ question(question,templateId){return this.call('question',{question,template_id:templateId});}
  /** @param {string} pmid */ abstract(pmid){return this.call('abstract',{pmid});}
  /** @param {string} claim @param {string} pmid */ propose(claim,pmid){return this.call('propose',{claim,pmid});}
  /** @param {Record<string,unknown>} body */ manual(body){return this.call('manual',body);}
  /** @param {Record<string,unknown>} body */ decide(body){return this.call('decide',body);}
  decisions(){return this.call('decisions');}
  /** @param {string} pmid */ remove(pmid){return this.call('decisions/'+encodeURIComponent(pmid),undefined,'DELETE');}
  /** @param {Record<string,unknown>} body */ document(body){return this.call('document',body);}
  /** @param {Record<string,unknown>} body */ caseCreate(body){return this.call('case',body);}
  /** @param {string} id @param {Record<string,unknown>} body */ caseDocument(id,body){return this.call('case/'+encodeURIComponent(id)+'/document',body);}
  /** @param {Record<string,unknown>} body */ caseScan(body){return this.call('case/scan',body);}
  /** @param {string} id */ caseExtract(id){return this.call('case/'+encodeURIComponent(id)+'/extract',{});}
  /** @param {string} id */ caseGet(id){return this.call('case/'+encodeURIComponent(id));}
  /** @param {string} id @param {Record<string,unknown>} body */ caseConfirm(id,body){return this.call('case/'+encodeURIComponent(id)+'/confirm',body);}
  /** @param {string} id */ caseDelete(id){return this.call('case/'+encodeURIComponent(id),undefined,'DELETE');}
  /** @param {string} id @param {Record<string,unknown>} body */ caseCheck(id,body){return this.call('case/'+encodeURIComponent(id)+'/check',body);}
  /** @param {string} id @param {Record<string,unknown>} body */ caseReport(id,body){return this.call('case/'+encodeURIComponent(id)+'/report',body);}
  styleGet(){return this.call('report-style');}
  /** @param {Record<string,unknown>} body */ stylePreview(body){return this.call('report-style/preview',body);}
  /** @param {string} text */ styleSave(text){return this.call('report-style',{text,confirmed:true},'PUT');}
  styleDelete(){return this.call('report-style',undefined,'DELETE');}
  /** @param {string} text */ requestParse(text){return this.call('request/parse',{text});}
  /** @param {string} q */ sbotSearch(q){return this.call('sbot/search?q='+encodeURIComponent(q));}
  /** @param {string} id */ sbotEntry(id){return this.call('sbot/entry/'+encodeURIComponent(id));}
  /** @param {string} id */ catalogFromSbot(id){return this.call('catalog/from-sbot',{entry_id:id});}
  profileGet(){return this.call('profile');}
  /** @param {Record<string,unknown>} p */ profileSave(p){return this.call('profile',p,'PUT');}
  financePanel(){return this.call('finance/panel');}
  financeSurgeries(){return this.call('finance/surgeries');}
  /** @param {Record<string,unknown>} s */ financeSurgerySave(s){return this.call('finance/surgeries',s,'PUT');}
  /** @param {string} id */ financeSurgeryDelete(id){return this.call('finance/surgeries/'+encodeURIComponent(id),undefined,'DELETE');}
  /** @param {Record<string,unknown>} body */ financeImportSurgeries(body){return this.call('finance/import/surgeries',body);}
  financeInvoices(){return this.call('finance/invoices');}
  /** @param {Record<string,unknown>} body */ financeImportInvoices(body){return this.call('finance/import/invoices',body);}
  /** @param {string} id */ financeInvoiceDelete(id){return this.call('finance/invoices/'+encodeURIComponent(id),undefined,'DELETE');}
  financePayments(){return this.call('finance/payments');}
  /** @param {Record<string,unknown>} body */ financeImportPayments(body){return this.call('finance/import/payments',body);}
  /** @param {string} id */ financePaymentDelete(id){return this.call('finance/payments/'+encodeURIComponent(id),undefined,'DELETE');}
  financeSuggestions(){return this.call('finance/suggestions');}
  /** @param {Record<string,unknown>} body */ financeLink(body){return this.call('finance/link',body);}
  appeals(){return this.call('appeals');}
  /** @param {Record<string,unknown>} body */ appealPreview(body){return this.call('appeals/preview',body);}
  /** @param {Record<string,unknown>} body */ appealSave(body){return this.call('appeals',body);}
  /** @param {string} id @param {string} outcome */ appealOutcome(id,outcome){return this.call('appeals/'+encodeURIComponent(id),{outcome},'PATCH');}
  /** @param {string} id */ appealDelete(id){return this.call('appeals/'+encodeURIComponent(id),undefined,'DELETE');}
  /** @param {Record<string,unknown>} body */ appealDraft(body){return this.call('appeal/draft',body);}
  /** @param {string} id */ appealDraftGet(id){return this.call('appeal/draft/'+encodeURIComponent(id));}
  letterheadGet(){return this.call('letterhead');}
  /** @param {Record<string,unknown>} l */ letterheadSave(l){return this.call('letterhead',l,'PUT');}
  consentGet(){return this.call('consent-model');}
  /** @param {Record<string,unknown>} body */ consentUpload(body){return this.call('consent-model',body);}
  consentDelete(){return this.call('consent-model',undefined,'DELETE');}
  catalog(){return this.call('catalog');}
  /** @param {Record<string,unknown>} t */ catalogSave(t){return this.call('catalog',t,'PUT');}
  /** @param {string} id */ catalogDelete(id){return this.call('catalog/'+encodeURIComponent(id),undefined,'DELETE');}
  /** @param {string} q */ tussProcedures(q){return this.call('tuss/procedures?q='+encodeURIComponent(q));}
  /** @param {string} q @param {string} m */ tussMaterials(q,m){return this.call('tuss/materials?q='+encodeURIComponent(q)+'&manufacturer='+encodeURIComponent(m));}
}

/** @param {string} tag @param {string} cls @param {string} [text] */
export function box(tag,cls,text=''){const n=el(tag,text);n.className=cls;return n;}
/** @param {string} label @param {HTMLElement} control @param {string} [hint] */
export function field(label,control,hint=''){
  const wrap=box('div','field');const l=el('label',label);
  if(!control.id)control.id='f-'+Math.random().toString(36).slice(2,10);
  l.setAttribute('for',control.id);wrap.append(l);if(hint)wrap.append(box('span','hint',hint));wrap.append(control);return wrap;
}
/** @param {string} [placeholder] @param {string} [value] */
export function input(placeholder='',value=''){const i=document.createElement('input');i.type='text';i.placeholder=placeholder;i.value=value;i.autocomplete='off';return i;}
/** @param {string} [placeholder] */
export function textarea(placeholder=''){const t=document.createElement('textarea');t.placeholder=placeholder;return t;}
/** @param {[string,string][]} options */
export function select(options){const s=document.createElement('select');for(const [v,t] of options){const o=el('option',t);o.setAttribute('value',v);s.append(o);}return s;}
/** @param {string} text @param {'primary'|'ghost'|'quiet'} [kind] @returns {HTMLButtonElement} */
export function button(text,kind='primary'){const b=document.createElement('button');b.textContent=text;b.className='btn btn-'+kind;b.type='button';return b;}
/** @param {string} text @param {string} tone */
export function pill(text,tone){return box('span','pill pill-'+tone,text);}
/** @param {HTMLElement} target @param {string} text @param {'error'|'ok'|'info'} [tone] */
export function say(target,text,tone='error'){const m=box('div','alert alert-'+tone,text);m.setAttribute('role',tone==='error'?'alert':'status');target.replaceChildren(m);}
/** @param {HTMLButtonElement} b @param {()=>Promise<void>} work */
export async function busy(b,work){b.disabled=true;b.classList.add('is-busy');try{await work();}finally{b.disabled=false;b.classList.remove('is-busy');}}
/** @param {string} name @param {string} text @param {string} type */
export function download(name,text,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);}

/** Shared state between the evidence and document pages (memory only). */
export const session = {claim:'', reviewer:'', /** @type {Array<Record<string,any>>} */ decisions:[], model:false};

/** @param {EvidenceClient} client @param {(n:number)=>void} onDecisions */
export function evidencePage(client,onDecisions){
  const root=box('div','page-grid');
  const form=box('section','card');
  form.append(box('h2','card-title','Pergunta clínica'),box('p','muted','Formule a afirmação que precisa ser fundamentada e a pergunta PICO. Use termos em inglês; não inclua dados do paciente.'));
  const claim=input('Total knee replacement improves pain and function versus nonsurgical treatment in knee osteoarthritis',session.claim);
  claim.oninput=()=>{session.claim=claim.value;};
  const population=input('knee osteoarthritis'),intervention=input('total knee arthroplasty; total knee replacement');
  const comparison=input('nonoperative; exercise therapy; conservative treatment'),outcome=input('pain; function');
  const reviewer=input('CRM-UF 000000',session.reviewer);reviewer.oninput=()=>{session.reviewer=reviewer.value;};
  form.append(field('Afirmação a fundamentar',claim));
  const grid=box('div','form-grid');
  grid.append(field('População',population,'sinônimos separados por ;'),field('Intervenção',intervention),field('Comparação',comparison,'opcional'),field('Desfecho',outcome,'opcional'));
  form.append(grid);
  const designs=box('div','chips');
  /** @type {HTMLInputElement[]} */ const boxes=[];
  for(const [value,label,on] of /** @type {[string,string,boolean][]} */([['rct','Ensaio randomizado',true],['sr','Revisão sistemática',true],['ma','Meta-análise',true],['guideline','Diretriz',false]])){
    const c=document.createElement('input');c.type='checkbox';c.value=value;c.checked=on;boxes.push(c);
    const l=box('label','chip');l.append(c,el('span',label));designs.append(l);
  }
  const since=select([['10','Últimos 10 anos'],['5','Últimos 5 anos'],['3','Últimos 3 anos'],['','Qualquer data']]);
  form.append(box('div','field-label','Tipos de estudo'),designs,field('Período de publicação',since,'prioriza os estudos mais atuais'),
    field('Seu registro profissional (CRM)',reviewer,'assina as decisões'));
  const go=button('Buscar evidências');const status=box('div','status-area');const query=box('p','query mono');
  form.append(box('div','actions'),status,query);/** @type {HTMLElement} */(form.querySelector('.actions')).append(go);
  // Portuguese question (typed or dictated), optionally from a surgery template -> Claude drafts the PICO search.
  const pt=box('section','card');
  pt.append(box('h2','card-title','Pergunta em português'),box('p','muted','Escreva ou dite a pergunta, ou escolha um modelo de cirurgia (procedimento TUSS + OPME). O Claude monta a busca em inglês, você confere os campos abaixo e a busca roda no PubMed. Não inclua dados do paciente.'));
  const ask=textarea('Ex.: A artroplastia total do joelho melhora dor e função em artrose avançada após falha do tratamento conservador?');ask.rows=3;
  const tpl=select([['','Sem modelo de cirurgia']]);
  client.catalog().then((/** @type {any} */ r)=>{for(const t of r.templates){const o=el('option',t.name);o.setAttribute('value',t.template_id);tpl.append(o);}}).catch(()=>{});
  const build=button(session.model?'Montar busca com o Claude e buscar':'IA não configurada');build.disabled=!session.model;
  const ptStatus=box('div','status-area');const ptActions=box('div','actions');ptActions.append(build);
  pt.append(field('Sua pergunta',ask),dictation(ask),field('Ou a partir de um modelo de cirurgia',tpl,'busca evidências para o procedimento e o OPME do modelo'),ptActions,ptStatus);
  build.onclick=()=>busy(build,async()=>{
    say(ptStatus,'O Claude está montando a busca…','info');
    try{
      const d=await client.question(ask.value,tpl.value||null);
      claim.value=d.claim;session.claim=d.claim;population.value=d.population.join('; ');intervention.value=d.intervention.join('; ');
      comparison.value=d.comparison.join('; ');outcome.value=d.outcome.join('; ');
      for(const b of boxes)b.checked=d.designs.includes(b.value);
      say(ptStatus,'Busca montada (confira os campos abaixo). Pesquisando no PubMed…','ok');
      go.click();
    }catch(e){say(ptStatus,e instanceof Error?e.message:'Falha.');}
  });
  const results=box('section','card');results.append(box('h2','card-title','Artigos encontrados'),box('p','muted','Faça a busca para listar os candidatos. Nada é usado sem a sua confirmação.'));
  const confirmed=box('section','card');confirmed.append(box('h2','card-title','Decisões confirmadas'));const table=box('div','decisions');confirmed.append(table);
  root.append(pt,form,externalSources(client,results,()=>refresh()),results,confirmed);

  const refresh=async()=>{const list=await client.decisions();session.decisions=list;onDecisions(list.length);renderDecisions(client,table,list,refresh);};
  go.onclick=()=>busy(go,async()=>{
    say(status,'Buscando no PubMed e conferindo no Crossref…','info');query.textContent='';
    try{
      const r=await client.search({population:population.value,intervention:intervention.value,comparison:comparison.value,outcome:outcome.value,
        designs:boxes.filter(b=>b.checked).map(b=>b.value),since_years:since.value?Number(since.value):null});
      status.replaceChildren();if(r.relaxed&&r.relaxed.length)say(status,'Poucos artigos com todos os critérios; a busca foi ampliada sem: '+r.relaxed.join(' e ')+'.','info');
      query.textContent='Consulta: '+r.query+(r.mesh.length?'  ·  MeSH: '+r.mesh.map((/** @type {any} */m)=>m.synonym+' → '+m.heading).join('; '):'');
      results.replaceChildren(box('h2','card-title',`${r.candidates.length} artigo(s) candidato(s)`));
      if(!r.candidates.length)results.append(box('p','muted','Nenhum artigo. Ajuste a pergunta.'));
      for(const c of r.candidates)results.append(articleCard(client,c,refresh));
    }catch(e){say(status,e instanceof Error?e.message:'Falha na busca.');}
  });
  refresh().catch(()=>{});
  return root;
}

/** Services used by the physician with their own login; nothing is fetched from them automatically. */
const EXTERNAL=[['OpenEvidence','https://www.openevidence.com/'],['OrthoEvidence','https://myorthoevidence.com/']];

/** @param {EvidenceClient} client @param {HTMLElement} results @param {()=>Promise<void>} refresh */
function externalSources(client,results,refresh){
  const card=box('section','card');
  card.append(box('h2','card-title','Outras fontes (com o seu login)'),
    box('p','muted','Consulte a pergunta no OpenEvidence ou no OrthoEvidence com a sua conta e traga para cá os PMIDs ou DOIs dos melhores artigos. Eles são conferidos no PubMed e no Crossref e entram no mesmo fluxo de classificação. Os termos de uso desses serviços não permitem acesso automatizado, por isso a consulta é feita por você.'));
  const links=box('div','actions');
  for(const [name,url] of EXTERNAL){const a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.className='btn btn-ghost';a.textContent='Abrir '+name;links.append(a);}
  const copy=button('Copiar pergunta','quiet');const copied=box('span','muted','');
  copy.onclick=async()=>{try{await navigator.clipboard.writeText(session.claim);copied.textContent='Pergunta copiada.';}catch{copied.textContent='Não foi possível copiar.';}};
  links.append(copy,copied);
  const ids=textarea('Cole PMIDs ou DOIs, separados por vírgula ou linha (até 10). Ex.: 26488691, 10.1056/NEJMoa1505467');ids.rows=3;
  const add=button('Verificar e adicionar');const status=box('div','status-area');const actions=box('div','actions');actions.append(add);
  card.append(links,field('PMIDs ou DOIs encontrados',ids),actions,status);
  add.onclick=()=>busy(add,async()=>{
    say(status,'Conferindo no PubMed e no Crossref…','info');
    try{
      const r=await client.importIds(ids.value);
      say(status,`${r.candidates.length} artigo(s) verificado(s) e adicionado(s) à lista.`+(r.invalid.length?' Ignorados: '+r.invalid.join(', '):''),r.candidates.length?'ok':'error');
      if(r.candidates.length){
        if(!results.querySelector('.article'))results.replaceChildren(box('h2','card-title','Artigos'));
        for(const c of r.candidates)results.append(articleCard(client,c,refresh));
        ids.value='';
      }
    }catch(e){say(status,e instanceof Error?e.message:'Falha.');}
  });
  return card;
}

/** @param {EvidenceClient} client @param {{pmid:string,title:string,doi?:string}} c @param {()=>Promise<void>} refresh */
function articleCard(client,c,refresh){
  const card=box('article','article');
  const link=document.createElement('a');link.href=`https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(c.pmid)}/`;link.target='_blank';link.rel='noopener noreferrer';link.textContent='PMID '+c.pmid;
  const head=box('div','article-head');head.append(box('h3','article-title',c.title||'[sem título]'),link);
  const out=box('div','article-body');
  const read=button('Ler resumo','quiet'),ai=button('Sugestão do Claude','ghost'),manual=button('Classificar manualmente','quiet');
  ai.disabled=!session.model;if(!session.model)ai.title='IA não configurada no servidor';
  const actions=box('div','actions');actions.append(read,ai,manual);card.append(head,actions,out);
  read.onclick=()=>busy(read,async()=>{try{const a=await client.abstract(c.pmid);out.replaceChildren(box('div','abstract',a.text));}catch(e){say(out,e instanceof Error?e.message:'Falha.');}});
  ai.onclick=()=>busy(ai,async()=>{if(!ready(out))return;say(out,'Consultando o Claude…','info');
    try{proposalView(client,out,await client.propose(session.claim,c.pmid),refresh);}catch(e){say(out,e instanceof Error?e.message:'Falha.');}});
  manual.onclick=()=>manualView(client,out,c.pmid,refresh);
  return card;
}

/** @param {HTMLElement} out */
function ready(out){
  if(session.claim.trim().length<10){say(out,'Preencha a afirmação a fundamentar.');return false;}
  if(session.reviewer.trim().length<3){say(out,'Informe o seu CRM.');return false;}
  return true;
}

/** @param {EvidenceClient} client @param {HTMLElement} out @param {Record<string,any>} p @param {()=>Promise<void>} refresh */
function proposalView(client,out,p,refresh){
  out.replaceChildren();
  if(p.status!=='PENDING_PHYSICIAN_REVIEW'){say(out,`Sugestão descartada (${p.status}): ${p.rationale}`);return;}
  const dir=/** @type {keyof typeof DIRECTIONS} */(p.direction);
  const choice=select(Object.entries(DIRECTIONS));choice.value=dir;
  const note=input('Motivo (obrigatório se mudar a classificação)');
  const ok=button('Confirmar'),no=button('Rejeitar artigo','quiet');
  const line=box('div','proposal-head');line.append(pill('Claude: '+DIRECTIONS[dir],dir),box('span','muted',p.model));
  out.append(line,box('blockquote','quote',p.quote),box('p','muted',p.rationale),field('Sua classificação',choice),note);
  const actions=box('div','actions');actions.append(ok,no);out.append(actions);
  /** @param {string} decision @param {HTMLButtonElement} b */
  const send=(decision,b)=>busy(b,async()=>{
    /** @type {Record<string,unknown>} */ const body={proposal_id:p.proposal_id,decision,reviewer:session.reviewer,note:note.value};
    if(decision!=='REJECT' && choice.value!==dir){body.decision='OVERRIDE';body.final_direction=choice.value;}
    try{const r=await client.decide(body);say(out,r.final_direction?'Confirmado: '+DIRECTIONS[/** @type {keyof typeof DIRECTIONS} */(r.final_direction)]+'.':'Artigo rejeitado.','ok');await refresh();}
    catch(e){out.append(box('div','alert alert-error',e instanceof Error?e.message:'Falha.'));}
  });
  ok.onclick=()=>send('ACCEPT',ok);no.onclick=()=>send('REJECT',no);
}

/** @param {EvidenceClient} client @param {HTMLElement} out @param {string} pmid @param {()=>Promise<void>} refresh */
function manualView(client,out,pmid,refresh){
  const choice=select(Object.entries(DIRECTIONS));const quote=textarea('Cole um trecho LITERAL do resumo (mínimo 20 caracteres)');
  const save=button('Salvar classificação');const msg=box('div','status-area');
  const actions=box('div','actions');actions.append(save);
  out.replaceChildren(field('Classificação',choice),field('Trecho do resumo',quote),actions,msg);
  save.onclick=()=>busy(save,async()=>{if(!ready(msg))return;
    try{const r=await client.manual({claim:session.claim,pmid,direction:choice.value,quote:quote.value,reviewer:session.reviewer});
      say(out,'Confirmado manualmente: '+DIRECTIONS[/** @type {keyof typeof DIRECTIONS} */(r.final_direction)]+'.','ok');await refresh();}
    catch(e){say(msg,e instanceof Error?e.message:'Falha.');}});
}

/** @param {EvidenceClient} client @param {HTMLElement} target @param {Array<Record<string,any>>} list @param {()=>Promise<void>} refresh */
function renderDecisions(client,target,list,refresh){
  if(!list.length){target.replaceChildren(box('p','muted','Nenhuma decisão ainda.'));return;}
  const rows=box('div','rows');
  for(const r of list){
    const row=box('div','row');const tag=r.final_direction?pill(DIRECTIONS[/** @type {keyof typeof DIRECTIONS} */(r.final_direction)],r.final_direction):pill('Rejeitado','muted');
    const remove=button('Remover','quiet');remove.onclick=()=>busy(remove,async()=>{await client.remove(r.pmid);await refresh();});
    const main=box('div','row-main');main.append(box('strong','', 'PMID '+r.pmid),box('span','muted',r.quote||''));
    row.append(tag,main,remove);rows.append(row);
  }
  target.replaceChildren(rows);
}

/** @param {EvidenceClient} client */
export function documentPage(client){
  const root=box('div','page-grid');
  const form=box('section','card');form.append(box('h2','card-title','Dados da solicitação'),box('p','muted','Fatos informados pelo médico. A identificação do paciente é preenchida depois, no PDF.'));
  const procedure=input('Artroplastia total do joelho');
  const rol=select([['NAO_INFORMADO','Não sei / verificar'],['SIM','Sim'],['NAO','Não']]);
  const urgency=select([['ELETIVA','Eletivo'],['URGENCIA','Urgência'],['EMERGENCIA','Emergência']]);
  const ans=select([['NAO_INFORMADO','Não sei'],['SEM_ANALISE','Nunca analisado'],['NEGADA','Incorporação negada'],['PENDENTE','Análise pendente']]);
  const crm=input('CRM-UF 000000',session.reviewer),anvisa=input('Registro do material');
  const prior=select([['','Não informado'],['true','Sim, com protocolo'],['false','Ainda não']]);
  const self=select([['','Não sei'],['false','Não'],['true','Sim']]);
  const alt=textarea('Por que as alternativas do Rol não servem para este caso'),summary=textarea('Justificativa clínica, sem nome ou documentos do paciente');summary.rows=7;
  form.append(field('Procedimento solicitado',procedure));
  const grid=box('div','form-grid');grid.append(field('Consta do Rol da ANS?',rol),field('Caráter',urgency),field('Situação na ANS',ans,'se fora do Rol'),field('Médico assistente (CRM)',crm),field('Registro Anvisa',anvisa),field('Pedido prévio à operadora',prior),field('Plano de autogestão',self));
  form.append(grid,field('Alternativas do Rol',alt,'necessário se fora do Rol'),field('Justificativa clínica',summary));
  const go=button('Gerar documento');const actions=box('div','actions');actions.append(go);const status=box('div','status-area');form.append(actions,status);
  const result=box('section','card');result.append(box('h2','card-title','Documento'),box('p','muted','O documento reverifica cada artigo no PubMed e no Crossref no momento da geração.'));
  root.append(form,result);
  /** @param {string} v */ const bool=v=>v===''?null:v==='true';
  go.onclick=()=>busy(go,async()=>{
    if(session.claim.trim().length<10){say(status,'Defina a afirmação na página Evidências.');return;}
    say(status,'Reverificando evidências e montando o documento…','info');
    try{
      const r=await client.document({claim:session.claim,procedure:procedure.value,rol:rol.value,urgency:urgency.value,ans_analysis:ans.value,
        no_rol_alternative:alt.value,anvisa:anvisa.value,crm:crm.value,prior_request:bool(prior.value),autogestao:bool(self.value),clinical_summary:summary.value});
      say(status,`${r.included} referência(s) incluída(s).`,'ok');renderDocument(result,r);
    }catch(e){say(status,e instanceof Error?e.message:'Falha ao gerar.');}
  });
  return root;
}

/** @param {HTMLElement} target @param {Record<string,any>} r */
function renderDocument(target,r){
  target.replaceChildren(box('h2','card-title','Documento'));
  if(r.requirements.length){
    target.append(box('h3','section-title','Requisitos do STF (ADI 7.265)'));
    const list=box('div','rows');
    for(const q of r.requirements){const row=box('div','row');const main=box('div','row-main');main.append(box('strong','',q.label),box('span','muted',q.basis));row.append(pill(REQUIREMENT[q.status]||q.status,q.status),main);list.append(row);}
    target.append(list);
  }
  for(const w of r.warnings)target.append(box('div','alert alert-warn','Pendência: '+w));
  for(const x of r.excluded)target.append(box('p','muted',`Não incluído PMID ${x.pmid}: ${x.reason}`));
  const open=button('Abrir para imprimir / PDF'),html=button('Baixar documento (.html)','ghost'),md=button('Baixar texto (.md)','quiet');
  const actions=box('div','actions');actions.append(open,html,md);target.append(actions);
  open.onclick=()=>{const url=URL.createObjectURL(new Blob([r.html],{type:'text/html'}));if(!window.open(url,'_blank'))target.append(box('div','alert alert-info','O navegador bloqueou a nova aba. Use "Baixar documento".'));setTimeout(()=>URL.revokeObjectURL(url),60000);};
  html.onclick=()=>download('solicitacao-cobertura.html',r.html,'text/html');
  md.onclick=()=>download('fundamentacao.md',r.markdown,'text/markdown');
}
