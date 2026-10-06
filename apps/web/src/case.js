/** Medical request from patient documents. Identification never leaves this page except to be removed. */
import {el} from './view.js';
import {box,button,busy,download,field,input,pill,say,select,session,textarea} from './evidence.js';
import {dictation} from './dictation.js';
import {templatePicker} from './catalog.js';

const REQUIREMENT=/** @type {Record<string,string>} */ ({ATENDIDO:'Atendido',PENDENTE:'Pendente',NAO_ATENDIDO:'Não atendido'});
/** Patient identification: memory only, cleared on logout/reload. */
const patient={name:'',cpf:'',rg:'',card_number:'',birth_date:'',phone:'',email:'',address:'',operadora:''};
/** @type {{id:string,view:Record<string,any>}|null} */ let current=null;
/** Request fields shared with the report card; the edited report text goes into the request. */
const draft={procedure:'',laterality:'',templateId:/** @type {string|null} */(null),reportText:'',autoReport:false};
/** Inputs of the identification card, so values read from the documents can fill them. */
const identityInputs=/** @type {Record<string,HTMLInputElement>} */ ({});
export function clearCase(){for(const k of Object.keys(patient))/** @type {Record<string,string>} */(patient)[k]='';current=null;draft.procedure='';draft.laterality='';draft.templateId=null;draft.reportText='';draft.autoReport=false;}
function identifiers(){const {operadora,...ids}=patient;return ids;}

/** @param {File} file @returns {Promise<string>} */
async function base64(file){const bytes=new Uint8Array(await file.arrayBuffer());let bin='';for(let i=0;i<bytes.length;i+=0x8000)bin+=String.fromCharCode(...bytes.subarray(i,i+0x8000));return btoa(bin);}

/** Renders the page; pass the live root to re-render it in place. @param {import('./evidence.js').EvidenceClient} client @param {HTMLElement} [root] */
export function casePage(client,root=box('div','page-grid')){
  root.replaceChildren(identityCard(),documentsCard(client,root));
  if(current)root.append(factsCard(client,root),reportCard(client),requestCard(client));
  return root;
}

function identityCard(){
  const card=box('section','card');
  card.append(box('h2','card-title','Identificação do paciente'),
    box('p','muted','Fica apenas neste navegador. Serve para remover esses dados dos documentos antes da IA e para preencher o cabeçalho do pedido no seu computador. Nada disso é enviado à IA ou gravado.'));
  const grid=box('div','form-grid');
  /** @type {[keyof typeof patient,string,string][]} */
  const fields=[['name','Nome completo',''],['cpf','CPF',''],['rg','RG',''],['card_number','Carteirinha',''],['operadora','Operadora / plano',''],['birth_date','Nascimento','dd/mm/aaaa'],['phone','Telefone',''],['email','E-mail',''],['address','Endereço','']];
  for(const [key,label,hint] of fields){const i=input(hint,patient[key]);i.autocomplete='off';i.oninput=()=>{patient[key]=i.value;};identityInputs[key]=i;grid.append(field(label,i));}
  card.append(grid);return card;
}

/** @param {import('./evidence.js').EvidenceClient} client @param {HTMLElement} root */
function documentsCard(client,root){
  const card=box('section','card');
  card.append(box('h2','card-title','Documentos e história'),
    box('p','muted','Envie laudos em PDF (com texto) ou .txt — ressonância, raio-x, tomografia, exames. Ao escolher os arquivos, nome, CPF e carteirinha são lidos aqui no seu computador (sem IA) e preenchem a identificação acima; confira. As imagens em si não são enviadas à IA.'));
  const picker=templatePicker(client,(t)=>{draft.templateId=t?t.template_id:null;if(t)draft.procedure=t.name;},draft.templateId||'');
  const side=select([['','—'],['Direito','Direito'],['Esquerdo','Esquerdo'],['Bilateral','Bilateral']]);side.value=draft.laterality;side.onchange=()=>{draft.laterality=side.value;};
  const history=textarea('História resumida: queixa, tempo de evolução, tratamentos realizados e por quanto tempo, exame físico, escalas (EVA, KOOS…), indicação.');history.rows=7;
  const files=document.createElement('input');files.type='file';files.multiple=true;files.accept='.pdf,.txt,application/pdf,text/plain';
  const consent=document.createElement('input');consent.type='checkbox';
  const consentLabel=box('label','chip');consentLabel.append(consent,el('span','Consentimento do paciente registrado para tratamento dos dados (LGPD)'));
  const go=button(session.model?'Remover identificação e ler com o Claude':'Remover identificação e enviar');const status=box('div','status-area');const preview=box('div','');
  const found=box('div','status-area');
  files.onchange=async()=>{
    /** @type {Set<string>} */ const filled=new Set();
    for(const f of Array.from(files.files||[])){
      if(f.size>700000)continue;
      try{const r=await client.caseScan({name:f.name,content_base64:await base64(f)});
        for(const [k,v] of Object.entries(r.identifiers||{})){const box_=identityInputs[k];if(box_&&!box_.value.trim()&&typeof v==='string'){box_.value=v;/** @type {Record<string,string>} */(patient)[k]=v;filled.add(k);}}
      }catch{/* unreadable file: reported when sending */}
    }
    say(found,filled.size?'Identificação lida dos documentos (no seu computador, sem IA). Confira os campos acima antes de enviar.':'Nenhuma identificação encontrada nos arquivos. Preencha ao menos o nome acima.',filled.size?'ok':'info');
  };
  const actions=box('div','actions');actions.append(go);
  card.append(picker,field('Lateralidade',side),field('História resumida',history),dictation(history),field('Laudos (PDF ou .txt, até 8)',files),found,consentLabel,actions,status,preview);
  if(current)renderPreview(preview,current.view);
  go.onclick=()=>busy(go,async()=>{
    if(!patient.name.trim()){say(status,'Preencha ao menos o nome do paciente, para que ele seja removido dos textos.');return;}
    if(!consent.checked){say(status,'Registre o consentimento do paciente.');return;}
    say(status,'Removendo identificação…','info');
    try{
      if(current)await client.caseDelete(current.id).catch(()=>{});
      let view=await client.caseCreate({history:history.value,identifiers:identifiers(),consent:true});
      const id=String(view.case_id);
      for(const f of Array.from(files.files||[])){
        if(f.size>700000)throw new Error(`"${f.name}" passa de 700 KB. Envie o PDF do laudo ou copie o texto na história.`);
        view=await client.caseDocument(id,{name:f.name,content_base64:await base64(f),identifiers:identifiers()});
      }
      current={id,view};files.value='';
      if(session.model){
        say(status,'Identificação removida. O Claude está lendo o texto sem identificação…','info');
        view=await client.caseExtract(id);
        for(let i=0;i<90&&view.status==='RUNNING';i++){await new Promise(r=>setTimeout(r,2000));view=await client.caseGet(id);}
        current.view=view;
      }
      casePage(client,root);
    }catch(e){say(status,e instanceof Error?e.message:'Falha no envio.');}
  });
  return card;
}

/** @param {HTMLElement} target @param {Record<string,any>} view */
function renderPreview(target,view){
  target.replaceChildren(box('h3','section-title','Texto que será lido pela IA (sem identificação)'));
  /** @param {string} title @param {string} text @param {Record<string,number>} removed */
  const block=(title,text,removed)=>{const d=document.createElement('details');const s=document.createElement('summary');
    const counts=Object.entries(removed||{}).map(([k,v])=>`${v} ${k.toLowerCase()}`).join(', ');
    s.textContent=title+(counts?` — removidos: ${counts}`:'');d.append(s,box('div','abstract',text||'(vazio)'));return d;};
  target.append(block('História',view.history,view.history_removed));
  for(const d of view.documents)target.append(block(`${d.label} (${d.name})`,d.text,d.removed));
}

/** @param {import('./evidence.js').EvidenceClient} client @param {HTMLElement} root */
function factsCard(client,root){
  const card=box('section','card');const view=current?current.view:{};
  card.append(box('h2','card-title','Fatos clínicos'),box('p','muted','A IA lê o texto sem identificação e extrai os fatos com o trecho literal de origem. Fato sem trecho literal é descartado. Confira, edite e confirme.'));
  const go=button(session.model?'Extrair fatos com o Claude':'IA não configurada');go.disabled=!session.model;
  const status=box('div','status-area');const list=box('div','rows');const actions=box('div','actions');actions.append(go);
  card.append(actions,status,list);
  const draw=(/** @type {Record<string,any>} */ v)=>{
    list.replaceChildren();
    if(v.status==='RUNNING'){say(status,'O Claude está lendo os documentos…','info');return;}
    if(v.status==='ERROR'||v.status==='BLOCKED'||v.status==='UNGROUNDED'){say(status,v.error||'Leitura não utilizável ('+v.status+'). Tente de novo.');return;}
    if(!v.facts||!v.facts.length){status.replaceChildren();return;}
    say(status,`${v.facts.length} fato(s) com trecho comprovado${v.discarded?`; ${v.discarded} descartado(s) por falta de trecho literal`:''}.`,'ok');
    /** @type {{id:string,check:HTMLInputElement,text:HTMLInputElement}[]} */ const rows=[];
    for(const f of v.facts){
      const row=box('div','row');const check=document.createElement('input');check.type='checkbox';check.checked=true;
      const text=input('',f.statement);const main=box('div','row-main');
      main.append(box('strong','',f.category_label),text,box('span','muted',`${f.source}: “${f.quote}”`));
      row.append(check,main);list.append(row);rows.push({id:f.fact_id,check,text});
    }
    const codes=box('div','chips');
    /** @type {HTMLInputElement[]} */
    const codeBoxes=[];
    for(const c of v.icd10_suggestions||[]){const b=document.createElement('input');b.type='checkbox';b.value=c.code;codeBoxes.push(b);
      const l=box('label','chip');l.append(b,el('span',`${c.code} — ${c.description}`));codes.append(l);}
    const manual=input('Outros CID-10, separados por vírgula (ex.: M17.1)');
    const confirm=button(session.model?'Confirmar e redigir o relatório':'Confirmar fatos e CID');const done=box('div','status-area');const a2=box('div','actions');a2.append(confirm);
    list.append(box('h3','section-title','CID-10 (sugestões da IA — marque só os que você confirma)'),codes,field('CID-10 adicionais',manual),a2,done);
    if(v.confirmed)say(done,`Confirmado: ${v.confirmed.facts.length} fato(s), CID ${v.confirmed.icd10.join(', ')||'—'}.`,'ok');
    confirm.onclick=()=>busy(confirm,async()=>{
      try{
        /** @type {Record<string,string>} */ const edits={};
        for(const r of rows)if(r.check.checked)edits[r.id]=r.text.value;
        const icd10=[...codeBoxes.filter(b=>b.checked).map(b=>b.value),...manual.value.split(',').map(x=>x.trim()).filter(Boolean)];
        const nv=await client.caseConfirm(String(current?.id),{fact_ids:rows.filter(r=>r.check.checked).map(r=>r.id),edits,icd10});
        if(current)current.view=nv;say(done,`Confirmado: ${nv.confirmed.facts.length} fato(s), CID ${nv.confirmed.icd10.join(', ')||'—'}.`,'ok');
        if(session.model){draft.autoReport=true;casePage(client,root);}
      }catch(e){say(done,e instanceof Error?e.message:'Falha.');}
    });
  };
  draw(view);
  go.onclick=()=>busy(go,async()=>{
    if(!current)return;
    try{
      let v=await client.caseExtract(current.id);draw(v);
      for(let i=0;i<90&&v.status==='RUNNING';i++){await new Promise(r=>setTimeout(r,2000));v=await client.caseGet(current.id);}
      current.view=v;draw(v);
    }catch(e){say(status,e instanceof Error?e.message:'Falha.');}
  });
  return card;
}

/** @param {import('./evidence.js').EvidenceClient} client */
function reportCard(client){
  const card=box('section','card');
  card.append(box('h2','card-title','Relatório médico'),box('p','muted','O Claude redige o relatório usando só os fatos que você confirmou. Cada frase é ligada aos fatos de origem, números que não estão nos fatos são descartados e o que faltar vira lacuna — nada é inventado. O modelo de cirurgia escolhido em "Documentos e história" define o procedimento e o OPME.'));
  const go=button(session.model?'Redigir relatório com o Claude':'IA não configurada');go.disabled=!session.model;
  const status=box('div','status-area');const body=box('div','');const a=box('div','actions');a.append(go);card.append(a,status,body);
  /** @type {HTMLTextAreaElement[]} */
  let areas=[];
  /** @type {string[]} */
  let titles=[];
  const sync=()=>{draft.reportText=areas.map((t,i)=>t.value.trim()?`${titles[i]}: ${t.value.trim()}`:'').filter(Boolean).join('\n\n');};
  const facts=()=>/** @type {Array<Record<string,any>>} */((current&&current.view.confirmed&&current.view.confirmed.facts)||[]);
  const render=(/** @type {Record<string,any>} */ r)=>{
    body.replaceChildren();areas=[];titles=[];
    if(r.status==='RUNNING'){say(status,'O Claude está redigindo o relatório…','info');return;}
    if(r.status==='ERROR'){say(status,r.error||'Falha.');return;}
    say(status,'Relatório redigido. Revise e edite cada seção; o texto final entra no pedido.'+(r.dropped?` ${r.dropped} frase(s) sem respaldo foram descartadas.`:''),'ok');
    for(const g of r.gaps||[])body.append(box('div','alert alert-warn','Lacuna: '+g));
    for(const sec of r.sections){
      const t=textarea('');t.rows=Math.max(3,Math.min(10,sec.sentences.length*2));t.value=sec.sentences.map((/** @type {any} */ x)=>x.text).join(' ');t.oninput=sync;
      const ids=[...new Set(sec.sentences.flatMap((/** @type {any} */ x)=>x.fact_ids))].filter(i=>i!=='CTX');
      const src=ids.map(i=>{const f=facts()[Number(i.slice(1))-1];return f?`${i}: ${f.statement} (${f.source})`:i;}).join(' · ');
      areas.push(t);titles.push(sec.title);body.append(field(sec.title,t,src?'Fontes — '+src:(sec.sentences.length?'Baseado no procedimento/OPME informado':'Sem fatos para esta seção — preencha se houver')));
    }
    sync();
  };
  const existing=current&&current.view.report;if(existing)render(existing);
  go.onclick=()=>busy(go,async()=>{draft.autoReport=false;
    if(!current){return;}
    if(!current.view.confirmed){say(status,'Confirme os fatos clínicos antes.');return;}
    try{
      let v=await client.caseReport(current.id,{procedure:draft.procedure,laterality:draft.laterality,template_id:draft.templateId});render(v.report);
      for(let i=0;i<90&&v.report&&v.report.status==='RUNNING';i++){await new Promise(r=>setTimeout(r,2000));v=await client.caseGet(current.id);}
      current.view=v;render(v.report);
    }catch(e){say(status,e instanceof Error?e.message:'Falha.');}
  });
  if(draft.autoReport&&session.model)queueMicrotask(()=>go.click());
  return card;
}

/** @param {HTMLElement} container @param {string[]} labels */
function repeater(container,labels){
  /** @type {HTMLInputElement[][]} */ const rows=[];
  const add=button('+ Adicionar','quiet');
  const addRow=()=>{const row=box('div','form-grid');const cells=labels.map(l=>input(l));for(const c of cells)row.append(c);container.insertBefore(row,add);rows.push(cells);};
  container.append(add);add.onclick=addRow;addRow();
  return ()=>rows.map(r=>r.map(c=>c.value.trim())).filter(r=>r.some(Boolean));
}

/** @param {import('./evidence.js').EvidenceClient} client */
function requestCard(client){
  const card=box('section','card');
  card.append(box('h2','card-title','Pedido médico'),box('p','muted','Códigos e materiais são informados por você. A fundamentação científica usa as decisões da página Evidências para a mesma afirmação.'));
  const procedure=input('Artroplastia total do joelho');const laterality=select([['','—'],['Direito','Direito'],['Esquerdo','Esquerdo'],['Bilateral','Bilateral']]);laterality.value=draft.laterality;
  const regime=select([['Internação','Internação'],['Ambulatorial','Ambulatorial'],['Hospital-dia','Hospital-dia']]);
  const rol=select([['NAO_INFORMADO','Não sei / verificar'],['SIM','Sim'],['NAO','Não']]);const urgency=select([['ELETIVA','Eletivo'],['URGENCIA','Urgência'],['EMERGENCIA','Emergência']]);
  const ans=select([['NAO_INFORMADO','Não sei'],['SEM_ANALISE','Nunca analisado'],['NEGADA','Incorporação negada'],['PENDENTE','Análise pendente']]);
  const crm=input('CRM-UF 000000',session.reviewer);const prior=select([['','Não informado'],['true','Sim, com protocolo'],['false','Ainda não']]);
  const self=select([['','Não sei'],['false','Não'],['true','Sim']]);const alt=textarea('Por que as alternativas do Rol não servem (se fora do Rol)');
  const summary=textarea('Texto clínico adicional (opcional)');
  const grid=box('div','form-grid');grid.append(field('Procedimento',procedure),field('Lateralidade',laterality),field('Regime',regime),field('Consta do Rol da ANS?',rol),field('Caráter',urgency),field('Situação na ANS',ans),field('Médico assistente (CRM)',crm),field('Pedido prévio à operadora',prior),field('Plano de autogestão',self));
  const tussBox=box('div','');const tuss=repeater(tussBox,['Código TUSS (8 dígitos)','Descrição']);
  const opmeBox=box('div','');const opme=repeater(opmeBox,['Material (OPME)','Registro Anvisa','Quantidade']);
  /** @type {string|null} */ let templateId=draft.templateId;
  const picker=templatePicker(client,(t)=>{templateId=t?t.template_id:null;draft.templateId=templateId;if(t){procedure.value=t.name;draft.procedure=t.name;regime.value=t.regime||regime.value;}},draft.templateId||'');
  procedure.oninput=()=>{draft.procedure=procedure.value;};laterality.onchange=()=>{draft.laterality=laterality.value;};
  if(draft.procedure)procedure.value=draft.procedure;
  card.append(picker,field('Procedimento solicitado',procedure),grid,box('div','field-label','TUSS'),tussBox,box('div','field-label','OPME'),opmeBox,field('Alternativas do Rol',alt),dictation(alt),field('Texto clínico adicional',summary),dictation(summary));
  const go=button('Gerar pedido');const status=box('div','status-area');const result=box('div','');const actions=box('div','actions');actions.append(go);card.append(actions,status,result);
  /** @param {string} v */ const bool=v=>v===''?null:v==='true';
  go.onclick=()=>busy(go,async()=>{
    if(!current){say(status,'Envie os documentos primeiro.');return;}
    if(!current.view.confirmed){say(status,'Confirme os fatos clínicos antes de gerar o pedido.');return;}
    const claim=session.claim.trim().length>=10?session.claim:`Surgical treatment is indicated: ${procedure.value||'procedure'}`;
    say(status,'Montando o pedido e reverificando as evidências…','info');
    try{
      const r=await client.document({claim,procedure:procedure.value,rol:rol.value,urgency:urgency.value,ans_analysis:ans.value,no_rol_alternative:alt.value,
        crm:crm.value,prior_request:bool(prior.value),autogestao:bool(self.value),clinical_summary:[draft.reportText,summary.value].filter(x=>x.trim()).join('\n\n'),case_id:current.id,
        laterality:laterality.value,regime:regime.value,template_id:templateId,tuss:tuss().map(([code,description])=>({code,description})),
        opme:opme().map(([description,anvisa,quantity])=>({description,anvisa,quantity:Number(quantity)||1}))});
      say(status,`Pedido gerado com ${r.included} referência(s) científica(s).`,'ok');
      result.replaceChildren();
      for(const q of r.requirements){const row=box('div','row');const m=box('div','row-main');m.append(box('strong','',q.label),box('span','muted',q.basis));row.append(pill(REQUIREMENT[q.status]||q.status,q.status),m);result.append(row);}
      for(const w of r.warnings)result.append(box('div','alert alert-warn','Pendência: '+w));
      const html=withIdentification(r.html);
      const open=button('Abrir para imprimir / PDF'),save=button('Baixar pedido (.html)','ghost');const a=box('div','actions');a.append(open,save);result.append(a);
      open.onclick=()=>{const url=URL.createObjectURL(new Blob([html],{type:'text/html'}));if(!window.open(url,'_blank'))result.append(box('div','alert alert-info','Nova aba bloqueada. Use "Baixar pedido".'));setTimeout(()=>URL.revokeObjectURL(url),60000);};
      save.onclick=()=>download('pedido-medico.html',html,'text/html');
    }catch(e){say(status,e instanceof Error?e.message:'Falha ao gerar.');}
  });
  return card;
}

/** Fill identification locally (the server never receives it for the document). @param {string} html */
function withIdentification(html){
  const doc=new DOMParser().parseFromString(html,'text/html');
  /** @type {Record<string,string>} */ const values={paciente:patient.name,carteirinha:patient.card_number,operadora:patient.operadora,data:new Date().toLocaleDateString('pt-BR')};
  for(const span of doc.querySelectorAll('[data-ident]')){const v=values[span.getAttribute('data-ident')||''];if(v){span.textContent=v;span.classList.remove('fill');}}
  return '<!doctype html>\n'+doc.documentElement.outerHTML;
}
