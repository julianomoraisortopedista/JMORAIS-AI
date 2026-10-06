/** Medical request from patient documents. Identification never leaves this page except to be removed. */
import {el} from './view.js';
import {box,button,busy,download,field,input,pill,say,select,session,textarea} from './evidence.js';

const REQUIREMENT=/** @type {Record<string,string>} */ ({ATENDIDO:'Atendido',PENDENTE:'Pendente',NAO_ATENDIDO:'Não atendido'});
/** Patient identification: memory only, cleared on logout/reload. */
const patient={name:'',cpf:'',rg:'',card_number:'',birth_date:'',phone:'',email:'',address:'',operadora:''};
/** @type {{id:string,view:Record<string,any>}|null} */ let current=null;
export function clearCase(){for(const k of Object.keys(patient))/** @type {Record<string,string>} */(patient)[k]='';current=null;}
function identifiers(){const {operadora,...ids}=patient;return ids;}

/** @param {File} file @returns {Promise<string>} */
async function base64(file){const bytes=new Uint8Array(await file.arrayBuffer());let bin='';for(let i=0;i<bytes.length;i+=0x8000)bin+=String.fromCharCode(...bytes.subarray(i,i+0x8000));return btoa(bin);}

/** @param {import('./evidence.js').EvidenceClient} client */
export function casePage(client){
  const root=box('div','page-grid');
  root.append(identityCard(),documentsCard(client,root));
  if(current)root.append(factsCard(client,root),requestCard(client));
  return root;
}

function identityCard(){
  const card=box('section','card');
  card.append(box('h2','card-title','Identificação do paciente'),
    box('p','muted','Fica apenas neste navegador. Serve para remover esses dados dos documentos antes da IA e para preencher o cabeçalho do pedido no seu computador. Nada disso é enviado à IA ou gravado.'));
  const grid=box('div','form-grid');
  /** @type {[keyof typeof patient,string,string][]} */
  const fields=[['name','Nome completo',''],['cpf','CPF',''],['rg','RG',''],['card_number','Carteirinha',''],['operadora','Operadora / plano',''],['birth_date','Nascimento','dd/mm/aaaa'],['phone','Telefone',''],['email','E-mail',''],['address','Endereço','']];
  for(const [key,label,hint] of fields){const i=input(hint,patient[key]);i.autocomplete='off';i.oninput=()=>{patient[key]=i.value;};grid.append(field(label,i));}
  card.append(grid);return card;
}

/** @param {import('./evidence.js').EvidenceClient} client @param {HTMLElement} root */
function documentsCard(client,root){
  const card=box('section','card');
  card.append(box('h2','card-title','Documentos e história'),
    box('p','muted','Envie laudos em PDF (com texto) ou .txt — ressonância, raio-x, tomografia, exames. As imagens em si não são enviadas à IA. Escreva a história resumida abaixo.'));
  const history=textarea('História resumida: queixa, tempo de evolução, tratamentos realizados e por quanto tempo, exame físico, escalas (EVA, KOOS…), indicação.');history.rows=7;
  const files=document.createElement('input');files.type='file';files.multiple=true;files.accept='.pdf,.txt,application/pdf,text/plain';
  const consent=document.createElement('input');consent.type='checkbox';
  const consentLabel=box('label','chip');consentLabel.append(consent,el('span','Consentimento do paciente registrado para tratamento dos dados (LGPD)'));
  const go=button('Remover identificação e enviar');const status=box('div','status-area');const preview=box('div','');
  const actions=box('div','actions');actions.append(go);
  card.append(field('História resumida',history),field('Laudos (PDF ou .txt, até 8)',files),consentLabel,actions,status,preview);
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
      say(status,'Identificação removida. Confira o texto abaixo antes de pedir a leitura da IA.','ok');
      root.replaceChildren(...casePage(client).children);
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
    const confirm=button('Confirmar fatos e CID');const done=box('div','status-area');const a2=box('div','actions');a2.append(confirm);
    list.append(box('h3','section-title','CID-10 (sugestões da IA — marque só os que você confirma)'),codes,field('CID-10 adicionais',manual),a2,done);
    if(v.confirmed)say(done,`Confirmado: ${v.confirmed.facts.length} fato(s), CID ${v.confirmed.icd10.join(', ')||'—'}.`,'ok');
    confirm.onclick=()=>busy(confirm,async()=>{
      try{
        /** @type {Record<string,string>} */ const edits={};
        for(const r of rows)if(r.check.checked)edits[r.id]=r.text.value;
        const icd10=[...codeBoxes.filter(b=>b.checked).map(b=>b.value),...manual.value.split(',').map(x=>x.trim()).filter(Boolean)];
        const nv=await client.caseConfirm(String(current?.id),{fact_ids:rows.filter(r=>r.check.checked).map(r=>r.id),edits,icd10});
        if(current)current.view=nv;say(done,`Confirmado: ${nv.confirmed.facts.length} fato(s), CID ${nv.confirmed.icd10.join(', ')||'—'}.`,'ok');
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
  void root;return card;
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
  const procedure=input('Artroplastia total do joelho');const laterality=select([['','—'],['Direito','Direito'],['Esquerdo','Esquerdo'],['Bilateral','Bilateral']]);
  const regime=select([['Internação','Internação'],['Ambulatorial','Ambulatorial'],['Hospital-dia','Hospital-dia']]);
  const rol=select([['NAO_INFORMADO','Não sei / verificar'],['SIM','Sim'],['NAO','Não']]);const urgency=select([['ELETIVA','Eletivo'],['URGENCIA','Urgência'],['EMERGENCIA','Emergência']]);
  const ans=select([['NAO_INFORMADO','Não sei'],['SEM_ANALISE','Nunca analisado'],['NEGADA','Incorporação negada'],['PENDENTE','Análise pendente']]);
  const crm=input('CRM-UF 000000',session.reviewer);const prior=select([['','Não informado'],['true','Sim, com protocolo'],['false','Ainda não']]);
  const self=select([['','Não sei'],['false','Não'],['true','Sim']]);const alt=textarea('Por que as alternativas do Rol não servem (se fora do Rol)');
  const summary=textarea('Texto clínico adicional (opcional)');
  const grid=box('div','form-grid');grid.append(field('Procedimento',procedure),field('Lateralidade',laterality),field('Regime',regime),field('Consta do Rol da ANS?',rol),field('Caráter',urgency),field('Situação na ANS',ans),field('Médico assistente (CRM)',crm),field('Pedido prévio à operadora',prior),field('Plano de autogestão',self));
  const tussBox=box('div','');const tuss=repeater(tussBox,['Código TUSS (8 dígitos)','Descrição']);
  const opmeBox=box('div','');const opme=repeater(opmeBox,['Material (OPME)','Registro Anvisa','Quantidade']);
  card.append(field('Procedimento solicitado',procedure),grid,box('div','field-label','TUSS'),tussBox,box('div','field-label','OPME'),opmeBox,field('Alternativas do Rol',alt),field('Texto clínico adicional',summary));
  const go=button('Gerar pedido');const status=box('div','status-area');const result=box('div','');const actions=box('div','actions');actions.append(go);card.append(actions,status,result);
  /** @param {string} v */ const bool=v=>v===''?null:v==='true';
  go.onclick=()=>busy(go,async()=>{
    if(!current){say(status,'Envie os documentos primeiro.');return;}
    if(!current.view.confirmed){say(status,'Confirme os fatos clínicos antes de gerar o pedido.');return;}
    const claim=session.claim.trim().length>=10?session.claim:`Surgical treatment is indicated: ${procedure.value||'procedure'}`;
    say(status,'Montando o pedido e reverificando as evidências…','info');
    try{
      const r=await client.document({claim,procedure:procedure.value,rol:rol.value,urgency:urgency.value,ans_analysis:ans.value,no_rol_alternative:alt.value,
        crm:crm.value,prior_request:bool(prior.value),autogestao:bool(self.value),clinical_summary:summary.value,case_id:current.id,
        laterality:laterality.value,regime:regime.value,tuss:tuss().map(([code,description])=>({code,description})),
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
