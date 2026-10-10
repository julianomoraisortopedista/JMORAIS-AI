/** Medical request from patient documents. Identification never leaves this page except to be removed. */
import {el} from './view.js';
import {DIRECTIONS,box,button,busy,download,field,input,pill,say,select,session,textarea} from './evidence.js';
import {dictation} from './dictation.js';
import {templatePicker} from './catalog.js';
import {applyLetterhead,practice,prescriptionPage,printModeSelect} from './letterhead.js';

const REQUIREMENT=/** @type {Record<string,string>} */ ({ATENDIDO:'Atendido',PENDENTE:'Pendente',NAO_ATENDIDO:'Não atendido'});
/** Patient identification: memory only, cleared on logout/reload. */
const patient={name:'',cpf:'',rg:'',card_number:'',birth_date:'',phone:'',email:'',address:'',operadora:''};
/** @type {{id:string,view:Record<string,any>}|null} */ let current=null;
/** Request fields shared with the report card; the edited report text goes into the request. */
const draft={procedure:'',laterality:'',templateId:/** @type {string|null} */(null),reportText:'',autoReport:false,
  /** Report sections as edited by the physician: [title, text]. */ reportSections:/** @type {[string,string][]} */([]),
  /** Hospital scheduling stated by the physician. */
  schedule:{hospital:'',date:'',time:'',duration_minutes:0,anesthesia:'',icu:/** @type {boolean|null} */(null),blood_reserve:/** @type {boolean|null} */(null),supplier:'',notes:''},
  regime:''};
/** Inputs of the identification card, so values read from the documents can fill them. */
const identityInputs=/** @type {Record<string,HTMLInputElement>} */ ({});
export function clearCase(){for(const k of Object.keys(patient))/** @type {Record<string,string>} */(patient)[k]='';current=null;draft.procedure='';draft.laterality='';draft.templateId=null;draft.reportText='';draft.autoReport=false;draft.reportSections=[];draft.regime='';
  draft.schedule={hospital:'',date:'',time:'',duration_minutes:0,anesthesia:'',icu:null,blood_reserve:null,supplier:'',notes:''};}
function identifiers(){const {operadora,...ids}=patient;return ids;}

/** @param {Blob} file @returns {Promise<string>} */
async function base64(file){const bytes=new Uint8Array(await file.arrayBuffer());let bin='';for(let i=0;i<bytes.length;i+=0x8000)bin+=String.fromCharCode(...bytes.subarray(i,i+0x8000));return btoa(bin);}

/** @type {any} */ let science=null;
const MAX_UPLOAD=700000;
const ACCEPT='.pdf,.txt,.docx,.jpg,.jpeg,.png,.heic,application/pdf,text/plain,image/*';
/** Photos of reports are redrawn here as a smaller JPEG (no location/EXIF) and read on the server by local OCR, never by the AI.
 * @param {File} f @returns {Promise<{name:string,content_base64:string}>} */
async function prepared(f){
  if(!f.type.startsWith('image/')&&!/\.(jpe?g|png|heic|heif)$/i.test(f.name)){
    if(f.size>MAX_UPLOAD)throw new Error(`"${f.name}" passa de 700 KB. Envie o PDF do laudo, uma foto ou copie o texto na história.`);
    return {name:f.name,content_base64:await base64(f)};}
  const url=URL.createObjectURL(f);
  try{
    const img=new Image();img.src=url;await img.decode();
    const scale=Math.min(1,2400/Math.max(img.naturalWidth,img.naturalHeight));
    const canvas=document.createElement('canvas');canvas.width=Math.round(img.naturalWidth*scale);canvas.height=Math.round(img.naturalHeight*scale);
    const ctx=canvas.getContext('2d');if(!ctx)throw new Error('canvas');
    ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(img,0,0,canvas.width,canvas.height);
    for(const q of [0.85,0.7,0.55,0.4]){
      const blob=await new Promise((/** @type {(b:Blob|null)=>void} */ done)=>canvas.toBlob(done,'image/jpeg',q));
      if(blob&&blob.size<=MAX_UPLOAD)return {name:f.name.replace(/\.[^.]+$/,'')+'.jpg',content_base64:await base64(blob)};
    }
  }catch{/* reported below */}finally{URL.revokeObjectURL(url);}
  throw new Error(`Não consegui abrir a foto "${f.name}". Envie em JPG ou PNG, ou fotografe de novo.`);
}

/** Renders the page; pass the live root to re-render it in place. @param {import('./evidence.js').EvidenceClient} client @param {HTMLElement} [root] */
export function casePage(client,root=box('div','page-grid')){
  root.replaceChildren(requestIntakeCard(client,root),identityCard(),documentsCard(client,root));
  if(current)root.append(factsCard(client,root),reportCard(client),requestCard(client));
  return root;
}

/** What the physician wants: understood by the AI, filled into the form for review. @param {import('./evidence.js').EvidenceClient} client @param {HTMLElement} root */
function requestIntakeCard(client,root){
  const card=box('section','card');
  card.append(box('h2','card-title','O que você quer solicitar'),
    box('p','muted','Fale ou escreva como pediria à secretária: procedimento, lado, fornecedor, hospital, dia e horário, anestesia, UTI, sangue. Ex.: "Artroplastia total do joelho direito, Zimmer, Hospital Santa Cruz, dia 20/10 às 7h, raqui, reservar UTI". A IA preenche os campos; você confere. Não diga o nome do paciente aqui.'));
  const text=textarea('Ex.: Artroplastia total do joelho direito, Zimmer, Hospital Santa Cruz, dia 20/10 às 7h, raqui, reservar UTI e 2 bolsas de sangue');text.rows=3;
  const go=button(session.model?'Entender pedido com o Claude':'IA não configurada');go.disabled=!session.model;
  const status=box('div','status-area');const a=box('div','actions');a.append(go);
  card.append(field('Pedido',text),dictation(text),a,status);
  go.onclick=()=>busy(go,async()=>{
    try{
      const r=await client.requestParse(text.value);
      if(r.template_id){draft.templateId=r.template_id;draft.procedure=r.template_name;}else if(r.procedure)draft.procedure=r.procedure;
      if(r.laterality)draft.laterality=r.laterality;if(r.regime)draft.regime=r.regime;
      draft.schedule={hospital:r.hospital,date:r.date,time:r.time,duration_minutes:r.duration_minutes,anesthesia:r.anesthesia,icu:r.icu,blood_reserve:r.blood_reserve,supplier:r.supplier,notes:r.notes};
      casePage(client,root);
      const s=/** @type {HTMLElement|null} */(root.querySelector('.status-area'));
      if(s)say(s,'Pedido entendido'+(r.template_name?`: modelo "${r.template_name}"`:r.procedure?`: ${r.procedure} (sem modelo correspondente na base)`:'')+'. Confira o modelo e o lado em "Documentos e história" e o agendamento em "Pedido médico".','ok');
    }catch(e){say(status,e instanceof Error?e.message:'Falha.');}
  });
  return card;
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
    box('p','muted','Envie laudos em PDF, Word, .txt ou foto — ressonância, raio-x, tomografia, exames. Fotos e PDFs escaneados são lidos aqui no seu computador, sem IA. Ao escolher os arquivos, nome, CPF e carteirinha são lidos localmente e preenchem a identificação acima; confira. As imagens em si nunca são enviadas à IA.'));
  const picker=templatePicker(client,(t)=>{draft.templateId=t?t.template_id:null;if(t)draft.procedure=t.name;},draft.templateId||'');
  const side=select([['','—'],['Direito','Direito'],['Esquerdo','Esquerdo'],['Bilateral','Bilateral']]);side.value=draft.laterality;side.onchange=()=>{draft.laterality=side.value;};
  const history=textarea('História resumida: queixa, tempo de evolução, tratamentos realizados e por quanto tempo, exame físico, escalas (EVA, KOOS…), indicação.');history.rows=7;
  const files=document.createElement('input');files.type='file';files.multiple=true;files.accept=ACCEPT;
  const consent=document.createElement('input');consent.type='checkbox';
  const consentLabel=box('label','chip');consentLabel.append(consent,el('span','Consentimento do paciente registrado para tratamento dos dados (LGPD)'));
  const go=button(session.model?'Remover identificação e ler com o Claude':'Remover identificação e enviar');const status=box('div','status-area');const preview=box('div','');
  const found=box('div','status-area');
  files.onchange=async()=>{
    /** @type {Set<string>} */ const filled=new Set();
    for(const f of Array.from(files.files||[])){
      try{const r=await client.caseScan(await prepared(f));
        for(const [k,v] of Object.entries(r.identifiers||{})){const box_=identityInputs[k];if(box_&&!box_.value.trim()&&typeof v==='string'){box_.value=v;/** @type {Record<string,string>} */(patient)[k]=v;filled.add(k);}}
      }catch{/* unreadable file: reported when sending */}
    }
    say(found,filled.size?'Identificação lida dos documentos (no seu computador, sem IA). Confira os campos acima antes de enviar.':'Nenhuma identificação encontrada nos arquivos. Preencha ao menos o nome acima.',filled.size?'ok':'info');
  };
  const actions=box('div','actions');actions.append(go);
  card.append(picker,field('Lateralidade',side),field('História resumida',history),dictation(history),field('Laudos (PDF, Word, .txt ou foto, até 8)',files),found,consentLabel,actions,status,preview);
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
        view=await client.caseDocument(id,{...(await prepared(f)),identifiers:identifiers()});
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
  const sync=()=>{draft.reportSections=areas.map((t,i)=>/** @type {[string,string]} */([titles[i],t.value.trim()])).filter(x=>x[1]);draft.reportText=draft.reportSections.map(([t,v])=>`${t}: ${v}`).join('\n\n');};
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
    const open=button('Relatório final com dados do paciente'),save=button('Baixar relatório (.html)','ghost');const fa=box('div','actions');fa.append(printModeSelect(),open,save);
    body.append(box('p','muted','O relatório final é montado aqui no seu computador, com nome, nascimento, CPF e carteirinha da identificação acima. Esses dados não vão para a IA.'),fa);
    open.onclick=()=>busy(open,async()=>{const html=await finalReport(client);const url=URL.createObjectURL(new Blob([html],{type:'text/html'}));if(!window.open(url,'_blank'))body.append(box('div','alert alert-info','Nova aba bloqueada. Use "Baixar relatório".'));setTimeout(()=>URL.revokeObjectURL(url),60000);});
    save.onclick=()=>busy(save,async()=>download('relatorio-medico.html',await finalReport(client),'text/html'));
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
  const regime=select([['Internação','Internação'],['Ambulatorial','Ambulatorial'],['Hospital-dia','Hospital-dia']]);if(draft.regime)regime.value=draft.regime;
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
  const sch=draft.schedule;
  /** @param {string} type @param {string} value @param {(v:string)=>void} set */
  const typed=(type,value,set)=>{const i=input('',value);i.type=type;i.oninput=()=>set(i.value);return i;};
  /** @param {boolean|null} value @param {(v:boolean|null)=>void} set */
  const yesNo=(value,set)=>{const s=select([['','Não informado'],['true','Sim'],['false','Não']]);s.value=value===null?'':String(value);s.onchange=()=>set(s.value===''?null:s.value==='true');return s;};
  const sgrid=box('div','form-grid');
  sgrid.append(field('Hospital',typed('text',sch.hospital,v=>{sch.hospital=v;})),field('Data',typed('date',sch.date,v=>{sch.date=v;})),
    field('Horário',typed('time',sch.time,v=>{sch.time=v;})),field('Duração prevista (min)',typed('number',sch.duration_minutes?String(sch.duration_minutes):'',v=>{sch.duration_minutes=Math.max(0,Math.min(1440,Number(v)||0));})),
    field('Anestesia',typed('text',sch.anesthesia,v=>{sch.anesthesia=v;})),field('Reserva de UTI',yesNo(sch.icu,v=>{sch.icu=v;})),
    field('Reserva de sangue',yesNo(sch.blood_reserve,v=>{sch.blood_reserve=v;})),field('Fornecedor preferencial',typed('text',sch.supplier,v=>{sch.supplier=v;})),
    field('Observações ao hospital',typed('text',sch.notes,v=>{sch.notes=v;})));
  card.append(picker,field('Procedimento solicitado',procedure),grid,box('div','field-label','Agendamento no hospital'),sgrid,box('div','field-label','TUSS'),tussBox,box('div','field-label','OPME'),opmeBox,field('Alternativas do Rol',alt),dictation(alt),field('Texto clínico adicional',summary),dictation(summary));
  const go=button('Gerar pedido');const status=box('div','status-area');const result=box('div','');const actions=box('div','actions');actions.append(printModeSelect(),go);card.append(actions,status,result);
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
        opme:opme().map(([description,anvisa,quantity])=>({description,anvisa,quantity:Number(quantity)||1})),schedule:draft.schedule});
      say(status,`Pedido gerado com ${r.included} referência(s) científica(s).`,'ok');
      result.replaceChildren();
      if(r.checks&&r.checks.length){result.append(box('h3','section-title','Checagem anti-negativa (SBOT)'));
        for(const c of r.checks)result.append(box('div','alert alert-'+(c.level==='BLOQUEIO'?'error':c.level==='OK'?'ok':'warn'),`${c.level==='BLOQUEIO'?'Corrigir':c.level==='OK'?'OK':'Atenção'} · ${c.topic}: ${c.message}`));}
      if(r.deadline)result.append(box('p','muted',r.deadline));
      for(const q of r.requirements){const row=box('div','row');const m=box('div','row-main');m.append(box('strong','',q.label),box('span','muted',q.basis));row.append(pill(REQUIREMENT[q.status]||q.status,q.status),m);result.append(row);}
      for(const w of r.warnings)result.append(box('div','alert alert-warn','Pendência: '+w));
      const {letterhead,profile}=await practice(client);
      const html=withIdentification(r.html,(doc)=>applyLetterhead(doc,letterhead,profile));
      const open=button('Abrir para imprimir / PDF'),save=button('Baixar pedido (.html)','ghost');const a=box('div','actions');a.append(open,save);result.append(box('p','muted','Modelo de impressão escolhido no momento de gerar: com logo e cabeçalho, ou sem cabeçalho.'),a);
      open.onclick=()=>{const url=URL.createObjectURL(new Blob([html],{type:'text/html'}));if(!window.open(url,'_blank'))result.append(box('div','alert alert-info','Nova aba bloqueada. Use "Baixar pedido".'));setTimeout(()=>URL.revokeObjectURL(url),60000);};
      save.onclick=()=>download('pedido-medico.html',html,'text/html');
      const tcle=button('Termo de consentimento com dados do paciente','ghost');a.append(tcle);
      tcle.onclick=()=>busy(tcle,async()=>{try{const doc=await consentForm(client,templateId,procedure.value,laterality.value);
        const url=URL.createObjectURL(new Blob([doc],{type:'text/html'}));if(!window.open(url,'_blank'))download('termo-consentimento.html',doc,'text/html');setTimeout(()=>URL.revokeObjectURL(url),60000);}
        catch(e){result.append(box('div','alert alert-warn',e instanceof Error?e.message:'Falha ao montar o termo.'));}});
    }catch(e){say(status,e instanceof Error?e.message:'Falha ao gerar.');}
  });
  return card;
}

/** Fill identification locally (the server never receives it for the document). @param {string} html @param {(doc:Document)=>void} [decorate] */
function withIdentification(html,decorate){
  const doc=new DOMParser().parseFromString(html,'text/html');
  /** @type {Record<string,string>} */ const values={paciente:patient.name,nascimento:patient.birth_date,cpf:patient.cpf,carteirinha:patient.card_number,operadora:patient.operadora,data:new Date().toLocaleDateString('pt-BR')};
  for(const span of doc.querySelectorAll('[data-ident]')){const v=values[span.getAttribute('data-ident')||''];if(v){span.textContent=v;span.classList.remove('fill');}}
  if(decorate)decorate(doc);
  return '<!doctype html>\n'+doc.documentElement.outerHTML;
}

/** Final medical report, assembled in the browser with the patient's identification (never sent to the AI). */
/** @param {import('./evidence.js').EvidenceClient} client */
async function finalReport(client){
  const {letterhead,profile}=await practice(client);
  const doc=document.implementation.createHTMLDocument('Relatório médico');
  const meta=doc.createElement('meta');meta.setAttribute('charset','utf-8');doc.head.prepend(meta);
  const style=doc.createElement('style');
  style.textContent='body{font-family:Georgia,serif;max-width:760px;margin:32px auto;padding:0 16px;color:#111;line-height:1.55}h1{text-align:center;font-size:20px;letter-spacing:.06em}h2{font-size:15px;margin:22px 0 6px;text-transform:uppercase}table{border-collapse:collapse;width:100%}td{padding:3px 6px;vertical-align:top}td:first-child{width:38%;color:#444}.sign{margin-top:56px;text-align:center}.draft{border:1px solid #b45309;color:#b45309;padding:6px 10px;font-size:13px}@media print{.draft{display:none}}';
  doc.head.append(style);
  /** @param {string} tag @param {string} text */
  const add=(tag,text)=>{const e=doc.createElement(tag);e.textContent=text;doc.body.append(e);return e;};
  add('div','RASCUNHO — revise e assine antes de enviar. Este aviso não aparece na impressão.').className='draft';
  add('h1','RELATÓRIO MÉDICO');
  const table=doc.createElement('table');
  const confirmed=current&&current.view.confirmed;
  /** @type {[string,string][]} */
  const rows=[['Paciente',patient.name],['Data de nascimento',patient.birth_date],['CPF',patient.cpf],['Carteirinha',patient.card_number],['Operadora / plano',patient.operadora],
    ['Procedimento',[draft.procedure,draft.laterality].filter(Boolean).join(' — ')],['CID-10',confirmed?confirmed.icd10.join(', '):'']];
  for(const [k,v] of rows){if(!v)continue;const tr=doc.createElement('tr');const a=doc.createElement('td'),b=doc.createElement('td');a.textContent=k+':';b.textContent=v;tr.append(a,b);table.append(tr);}
  doc.body.append(table);
  for(const [title,text] of draft.reportSections){add('h2',title);for(const para of text.split(/\n+/))if(para.trim())add('p',para.trim());}
  add('p',new Date().toLocaleDateString('pt-BR',{day:'numeric',month:'long',year:'numeric'}));
  const sign=add('div','');sign.className='sign';sign.append(doc.createTextNode('_______________________________________'),doc.createElement('br'),doc.createTextNode(profile.name||'Médico assistente'),doc.createElement('br'),doc.createTextNode(profile.crm?`CRM-${profile.uf||''} ${profile.crm}`:(session.reviewer||'CRM')));
  applyLetterhead(doc,letterhead,profile);
  return '<!doctype html>\n'+doc.documentElement.outerHTML;
}

/** Consent form from the physician's model, filled in the browser (patient data never leaves it).
 * @param {import('./evidence.js').EvidenceClient} client @param {string|null} templateId @param {string} procedure @param {string} side */
async function consentForm(client,templateId,procedure,side){
  const [model,{letterhead,profile},catalog]=await Promise.all([client.consentGet(),practice(client),client.catalog()]);
  if(!model.text)throw new Error('Envie o seu modelo de termo em "Modelos de cirurgia" > "Meu termo de consentimento".');
  const t=(catalog.templates||[]).find((/** @type {any} */ x)=>x.template_id===templateId)||{};
  const fold=(/** @type {string} */ v)=>v.normalize('NFKD').replace(/[̀-ͯ]/g,'').toLowerCase();
  const name=[procedure||t.name||'',side?`(${side.toLowerCase()})`:''].filter(Boolean).join(' ');
  const crm=profile.crm?`CRM-${profile.uf||''} ${profile.crm}`:'';
  const anesthesia=draft.schedule.anesthesia||t.anesthesia||'';
  const risks=/** @type {string[]} */(t.consent_risks||[]);
  const today=new Date().toLocaleDateString('pt-BR',{day:'numeric',month:'long',year:'numeric'});
  /** @param {string} inside @returns {string|null} */
  const value=(inside)=>{const k=fold(inside);
    if(k.includes('complicac'))return null;
    if(k.includes('paciente'))return patient.name||null;
    if(k.includes('nome e crm'))return [profile.name,crm].filter(Boolean).join(', ')||null;
    if(k.includes('medico')||k.includes('profissional'))return profile.name||null;
    if(k.includes('estado'))return profile.uf||null;
    if(k.includes('crm'))return profile.crm||null;
    if(k.includes('definic'))return t.consent_definition||null;
    if(k.includes('procedimento'))return name||null;
    if(k.includes('anestesia'))return anesthesia||null;
    if(k.includes('local'))return profile.city||null;
    if(k.includes('data'))return today;
    return null;};
  const doc=document.implementation.createHTMLDocument('Termo de consentimento');
  const meta=doc.createElement('meta');meta.setAttribute('charset','utf-8');doc.head.prepend(meta);
  const style=doc.createElement('style');style.textContent='body{font-family:Georgia,serif;max-width:760px;margin:32px auto;padding:0 16px;line-height:1.6;color:#111}p{margin:8px 0;text-align:justify}.fill{background:#fde68a}.draft{border:1px solid #b45309;color:#b45309;padding:6px 10px;font-size:13px}@media print{.draft{display:none}.fill{background:none}}';
  doc.head.append(style);
  const warn=doc.createElement('div');warn.className='draft';warn.textContent='Confira antes de imprimir. Campos em amarelo ficaram sem dado. Este aviso não aparece na impressão.';doc.body.append(warn);
  let block='paciente';
  /** @type {Record<string,string>} */ const own={'nome do paciente':patient.name,'endereco':patient.address,'cpf':patient.cpf,'telefones':patient.phone,'telefone':patient.phone};
  for(const line of String(model.text).split('\n')){
    const f=fold(line);if(/^(responsavel|testemunha)/.test(f))block='outro';
    const p=doc.createElement('p');
    if(/inserir,? em topicos,? as possiveis complicac/.test(f)&&risks.length){const ul=doc.createElement('ul');for(const r of risks){const li=doc.createElement('li');li.textContent=r;ul.append(li);}doc.body.append(ul);continue;}
    const label=f.match(/^([a-z ]+):\s*_+\s*$/);
    if(label&&block==='paciente'&&own[label[1].trim()]){p.textContent=line.replace(/_+\s*$/,'')+' '+own[label[1].trim()];doc.body.append(p);continue;}
    let rest=line;const re=/\((inserir[^)]*)\)/i;let m;
    while((m=re.exec(rest))){p.append(doc.createTextNode(rest.slice(0,m.index)));const v=value(m[1]);
      const span=doc.createElement('span');if(v){span.textContent=v;}else{span.textContent='('+m[1]+')';span.className='fill';}p.append(span);rest=rest.slice(m.index+m[0].length);}
    p.append(doc.createTextNode(rest));
    if(/^termo de consentimento/.test(f)){const h=doc.createElement('h1');h.textContent=line;h.style.textAlign='center';h.style.fontSize='18px';doc.body.append(h);}else doc.body.append(p);
  }
  applyLetterhead(doc,letterhead,profile);
  return '<!doctype html>\n'+doc.documentElement.outerHTML;
}

/** @param {number} ms */ const pause=(ms)=>new Promise(r=>setTimeout(r,ms));

/** One-click flow: request + documents -> de-identified extraction -> report in the physician's model -> review.
 * @param {import('./evidence.js').EvidenceClient} client */
export function quickPage(client){
  const root=box('div','page-grid');
  const ask=box('section','card');
  ask.append(box('h2','card-title','1. O que você quer solicitar'),
    box('p','muted','Fale ou escreva: procedimento, lado, fornecedor, hospital, dia e horário. Ou escolha o modelo de cirurgia abaixo. Não diga o nome do paciente aqui.'));
  const text=textarea('Ex.: Artroplastia total do joelho direito, Zimmer, Hospital Santa Cruz, dia 20/10 às 7h, raqui, reservar UTI');text.rows=3;
  const picker=templatePicker(client,(t)=>{draft.templateId=t?t.template_id:null;if(t)draft.procedure=t.name;},draft.templateId||'');
  const side=select([['','Lado —'],['Direito','Direito'],['Esquerdo','Esquerdo'],['Bilateral','Bilateral']]);side.value=draft.laterality;side.onchange=()=>{draft.laterality=side.value;};
  ask.append(field('Pedido',text),dictation(text),picker,field('Lateralidade',side));
  const docs=box('section','card');
  docs.append(box('h2','card-title','2. Documentos do paciente'),
    box('p','muted','Laudos, exames, relatórios e pedidos anteriores (PDF, Word, .txt ou foto). Fotos e PDFs escaneados são lidos aqui no seu computador; nome, CPF e carteirinha são lidos e removidos localmente, sem IA.'));
  const files=document.createElement('input');files.type='file';files.multiple=true;files.accept=ACCEPT;
  const history=textarea('Opcional: história, exame físico, tratamentos e tempo de evolução (pode ditar).');history.rows=5;
  const consent=document.createElement('input');consent.type='checkbox';const cl=box('label','chip');cl.append(consent,el('span','Consentimento do paciente registrado para tratamento dos dados (LGPD)'));
  docs.append(field('Arquivos (até 8)',files),field('História (opcional)',history),dictation(history),cl);
  const go=button(session.model?'Gerar relatório e pedido':'IA não configurada');go.disabled=!session.model;go.classList.add('btn-wide');
  const steps=box('ol','steps-list');const status=box('div','status-area');const result=box('div','page-grid');
  const run=box('section','card');run.append(go,steps,status);
  root.append(ask,docs,run,result);
  /** @param {string} label */
  const step=(label)=>{const li=el('li','… '+label);steps.append(li);return (/** @type {string} */ end='✓')=>{li.textContent=end+' '+label;};};
  go.onclick=()=>busy(go,async()=>{
    steps.replaceChildren();status.replaceChildren();result.replaceChildren();
    try{
      if(!consent.checked)throw new Error('Registre o consentimento do paciente (LGPD).');
      const list=Array.from(files.files||[]);
      if(!list.length&&history.value.trim().length<20)throw new Error('Anexe os documentos ou escreva a história.');
      const ready=[];for(const f of list)ready.push(await prepared(f));
      if(text.value.trim().length>=6){const done=step('Entendendo o pedido');
        const r=await client.requestParse(text.value);
        if(r.template_id){draft.templateId=r.template_id;draft.procedure=r.template_name;}else if(r.procedure)draft.procedure=r.procedure;
        if(r.laterality)draft.laterality=r.laterality;if(r.regime)draft.regime=r.regime;
        draft.schedule={hospital:r.hospital,date:r.date,time:r.time,duration_minutes:r.duration_minutes,anesthesia:r.anesthesia,icu:r.icu,blood_reserve:r.blood_reserve,supplier:r.supplier,notes:r.notes};
        done();}
      if(!draft.procedure&&!draft.templateId)throw new Error('Diga o procedimento ou escolha o modelo de cirurgia.');
      let done=step('Lendo a identificação nos documentos (no seu computador)');
      for(const f of ready){try{const r=await client.caseScan(f);
        for(const [k,v] of Object.entries(r.identifiers||{})){const rec=/** @type {Record<string,string>} */(patient);if(!rec[k]&&typeof v==='string')rec[k]=v;}}catch{/* reported on upload */}}
      done();
      if(!patient.name.trim())throw new Error('Não encontrei o nome do paciente nos documentos. Digite-o em "Pedido médico" > Identificação e tente de novo.');
      done=step('Removendo a identificação e enviando');
      if(current)await client.caseDelete(current.id).catch(()=>{});
      let view=await client.caseCreate({history:history.value,identifiers:identifiers(),consent:true});const id=String(view.case_id);
      for(const f of ready)view=await client.caseDocument(id,{...f,identifiers:identifiers()});
      current={id,view};done();
      done=step('Claude lendo o texto sem identificação');
      view=await client.caseExtract(id);for(let i=0;i<90&&view.status==='RUNNING';i++){await pause(2000);view=await client.caseGet(id);}
      if(!view.facts||!view.facts.length)throw new Error(view.error||'Não encontrei fatos clínicos com trecho comprovado nos documentos.');
      done();
      done=step('Separando os fatos comprovados e o CID');
      const icd=(view.icd10_suggestions||[]).map((/** @type {any} */ c)=>c.code).filter((/** @type {string} */ c)=>/^[A-Z]\d{2}(\.\d{1,2})?$/.test(c));
      view=await client.caseConfirm(id,{fact_ids:view.facts.map((/** @type {any} */ f)=>f.fact_id),edits:{},icd10:icd});current.view=view;done();
      done=step('Redigindo o relatório no formato do seu modelo');
      view=await client.caseReport(id,{procedure:draft.procedure,laterality:draft.laterality,template_id:draft.templateId});
      for(let i=0;i<90&&view.report&&view.report.status==='RUNNING';i++){await pause(2000);view=await client.caseGet(id);}
      if(!view.report||view.report.status!=='READY')throw new Error((view.report&&view.report.error)||'Falha ao redigir o relatório.');
      current.view=view;draft.reportSections=view.report.sections.map((/** @type {any} */ sec)=>[sec.title,sec.sentences.map((/** @type {any} */ x)=>x.text).join(' ')]).filter((/** @type {any} */ x)=>x[1]);
      done();
      /** @type {any} */ let check=null;
      if(draft.templateId){done=step('Conferindo com a SBOT e o prazo da ANS');check=await client.caseCheck(id,{template_id:draft.templateId,regime:draft.regime}).catch(()=>null);done();
        done=step('Conferindo os artigos da biblioteca desta cirurgia no PubMed e no Crossref');
        science=await client.libraryReferences(draft.templateId).catch(()=>null);done(science&&science.references.length?'✓':'!');}
      else science=null;
      say(status,'Pronto. Revise o relatório e a solicitação abaixo antes de imprimir.','ok');
      result.replaceChildren(...quickResult(client,view,check).children);
    }catch(e){say(status,e instanceof Error?e.message:'Falha.');}
  });
  return root;
}

/** Review screen of the one-click flow. @param {import('./evidence.js').EvidenceClient} client @param {Record<string,any>} view @param {any} check */
function quickResult(client,view,check){
  const wrap=box('div','page-grid');
  const review=box('section','card');
  review.append(box('h2','card-title','3. Revise e imprima'),
    box('div','alert alert-warn','Os fatos e o CID sugerido foram aceitos automaticamente para agilizar. Confira o texto abaixo; se algo estiver errado, corrija aqui ou ajuste os fatos em "Pedido médico".'));
  const ids=box('div','form-grid');
  /** @type {[keyof typeof patient,string][]} */
  const idf=[['name','Paciente'],['birth_date','Nascimento'],['cpf','CPF'],['card_number','Carteirinha'],['operadora','Operadora']];
  for(const [k,l] of idf){const i=input(l,patient[k]);i.oninput=()=>{patient[k]=i.value;};ids.append(field(l,i));}
  review.append(box('h3','section-title','Identificação (só no seu computador)'),ids);
  const confirmed=view.confirmed||{};review.append(box('p','muted',`CID-10: ${(confirmed.icd10||[]).join(', ')||'— (informe em Pedido médico)'} · Procedimento: ${[draft.procedure,draft.laterality].filter(Boolean).join(' — ')}`));
  for(const g of view.report.gaps||[])review.append(box('div','alert alert-warn','Lacuna: '+g));
  draft.reportSections.forEach((sec,n)=>{const t=textarea('');t.rows=Math.max(3,Math.min(12,Math.ceil(sec[1].length/110)));t.value=sec[1];t.oninput=()=>{draft.reportSections[n]=[sec[0],t.value];};review.append(field(sec[0],t));});
  wrap.append(review);
  const sci=box('section','card');sci.append(box('h2','card-title','Fundamentação científica'));
  if(science&&science.references.length){sci.append(box('p','muted',`${science.references.length} artigo(s) da biblioteca desta cirurgia, conferidos agora no PubMed e no Crossref. Entram no pedido com o trecho literal e a referência em Vancouver.`));
    for(const r of science.references)sci.append(box('p','',`[${r.number}] ${DIRECTIONS[/** @type {keyof typeof DIRECTIONS} */(r.direction)]||r.direction}${r.study?' · '+r.study:''} — ${r.vancouver}`));}
  else sci.append(box('div','alert alert-warn','Esta cirurgia ainda não tem artigos aprovados. Em "Modelos de cirurgia", use "Montar artigos com o Claude" uma vez; os próximos pedidos já saem com a fundamentação.'));
  for(const e of (science&&science.excluded)||[])sci.append(box('p','muted',`PMID ${e.pmid} não entrou: ${e.reason}`));
  wrap.append(sci);
  if(check){const c=box('section','card');c.append(box('h2','card-title','Checagem anti-negativa'));
    if(!check.codes_confirmed)c.append(box('div','alert alert-warn','Os códigos TUSS deste modelo ainda não foram confirmados por você (Modelos de cirurgia).'));
    for(const f of check.checks||[])c.append(box('div','alert alert-'+(f.level==='BLOQUEIO'?'error':f.level==='OK'?'ok':'warn'),`${f.level==='BLOQUEIO'?'Corrigir':f.level==='OK'?'OK':'Atenção'} · ${f.topic}: ${f.message}`));
    if(check.deadline)c.append(box('p','muted',check.deadline));wrap.append(c);}
  const out=box('section','card');const open=button('Abrir relatório e solicitação'),save=button('Baixar (.html)','ghost'),tcle=button('Termo de consentimento','ghost');
  const a=box('div','actions');a.append(printModeSelect(),open,save,tcle);const st=box('div','status-area');out.append(box('p','muted','O documento é montado aqui com os dados do paciente. Imprima ou salve em PDF pelo navegador.'),a,st);
  const build=async()=>combinedDocument(client,check);
  open.onclick=()=>busy(open,async()=>{const html=await build();const url=URL.createObjectURL(new Blob([html],{type:'text/html'}));if(!window.open(url,'_blank'))download('relatorio-e-solicitacao.html',html,'text/html');setTimeout(()=>URL.revokeObjectURL(url),60000);});
  save.onclick=()=>busy(save,async()=>download('relatorio-e-solicitacao.html',await build(),'text/html'));
  tcle.onclick=()=>busy(tcle,async()=>{try{const html=await consentForm(client,draft.templateId,draft.procedure,draft.laterality);const url=URL.createObjectURL(new Blob([html],{type:'text/html'}));if(!window.open(url,'_blank'))download('termo-consentimento.html',html,'text/html');setTimeout(()=>URL.revokeObjectURL(url),60000);}catch(e){say(st,e instanceof Error?e.message:'Falha.');}});
  wrap.append(out);return wrap;
}

/** Medical report + surgery and material request, assembled in the browser.
 * @param {import('./evidence.js').EvidenceClient} client @param {any} check */
async function combinedDocument(client,check){
  const [{letterhead,profile},catalog]=await Promise.all([practice(client),client.catalog().catch(()=>({templates:[]}))]);
  const t=(catalog.templates||[]).find((/** @type {any} */ x)=>x.template_id===draft.templateId)||null;
  const doc=document.implementation.createHTMLDocument('Relatório médico e solicitação');
  const meta=doc.createElement('meta');meta.setAttribute('charset','utf-8');doc.head.prepend(meta);
  const style=doc.createElement('style');
  style.textContent='body{font-family:Georgia,serif;max-width:780px;margin:28px auto;padding:0 16px;color:#111;line-height:1.5;font-size:14px}h1{text-align:center;font-size:17px;letter-spacing:.04em;margin:18px 0}h2{font-size:13.5px;margin:18px 0 4px;text-transform:uppercase}table{border-collapse:collapse;width:100%;margin:4px 0}td,th{padding:3px 6px;vertical-align:top;text-align:left;border-bottom:1px solid #ddd}.ident td:first-child{width:32%;color:#444}.head{border-bottom:2px solid #111;padding-bottom:6px}.small{font-size:12px;color:#444}.sign{margin-top:48px;text-align:center}.draft{border:1px solid #b45309;color:#b45309;padding:6px 10px;font-size:12px}@media print{.draft{display:none}}';
  doc.head.append(style);
  /** @param {string} tag @param {string} txt @param {HTMLElement} [parent] */
  const add=(tag,txt,parent)=>{const e=doc.createElement(tag);e.textContent=txt;(parent||doc.body).append(e);return e;};
  /** @param {string[][]} rows @param {string[]} [headers] @param {string} [cls] */
  const table=(rows,headers,cls)=>{const tb=doc.createElement('table');if(cls)tb.className=cls;if(headers){const tr=doc.createElement('tr');for(const h of headers)add('th',h,tr);tb.append(tr);}
    for(const r of rows){const tr=doc.createElement('tr');for(const c of r)add('td',c,tr);tb.append(tr);}doc.body.append(tb);};
  add('div','RASCUNHO — revise e assine antes de enviar. Este aviso não aparece na impressão.').className='draft';
  add('h1','RELATÓRIO MÉDICO E SOLICITAÇÃO DE PROCEDIMENTO CIRÚRGICO');
  if(patient.operadora)add('p',`À ${patient.operadora} — Setor de Autorizações`);
  const confirmed=current&&current.view.confirmed||{};
  table([['Paciente',patient.name],['Data de nascimento',patient.birth_date],['CPF',patient.cpf],['Carteirinha',patient.card_number],['Operadora / plano',patient.operadora]].filter(r=>r[1]),undefined,'ident');
  for(const [title,txt] of draft.reportSections){add('h2',title);for(const para of txt.split(/\n+/))if(para.trim())add('p',para.trim());}
  add('h2','Solicitação');
  const proc=[draft.procedure||(t&&t.name)||'',draft.laterality?`— ${draft.laterality.toLowerCase()}`:''].filter(Boolean).join(' ');
  /** @type {string[][]} */ const info=[['Procedimento',proc],['CID-10',(confirmed.icd10||[]).join(', ')],['Caráter','Eletivo'],['Regime',draft.regime||(t&&t.regime)||'']];
  if(t&&(t.icu_days!=null||t.ward_days!=null))info.push(['Internação prevista',`UTI ${t.icu_days??0} dia(s), quarto ${t.ward_days??0} dia(s)`]);
  const s=draft.schedule;if(s.hospital)info.push(['Hospital',s.hospital]);
  if(s.date)info.push(['Data proposta',s.date.split('-').reverse().join('/')+(s.time?` às ${s.time}`:'')]);
  if(s.anesthesia)info.push(['Anestesia',s.anesthesia]);if(s.icu!==null)info.push(['Reserva de UTI',s.icu?'Sim':'Não']);if(s.blood_reserve!==null)info.push(['Reserva de sangue',s.blood_reserve?'Sim':'Não']);
  table(info.filter(r=>r[1]),undefined,'ident');
  if(t&&t.tuss_codes.length){add('p','Códigos (TUSS):');table(t.tuss_codes.map((/** @type {string} */ c)=>[c,t.tuss_terms[c]||'']),['Código','Descrição']);}
  if(t&&t.opme.length){add('p','Órteses, próteses e materiais especiais (OPME):');table(t.opme.map((/** @type {any} */ i)=>[i.description,String(i.quantity)]),['Material','Qtd.']);}
  const brands=t?(t.suppliers||[]).filter((/** @type {any} */ x)=>x.label):[];
  if(t&&t.opme.length&&brands.length<3)throw new Error(`O modelo "${t.name}" tem ${brands.length} empresa(s) de material. Cadastre 3, de fabricantes diferentes, em Modelos de cirurgia (CFM 1.956/2010).`);
  if(brands.length){add('p','Fornecedores indicados, de fabricantes diferentes (CFM 1.956/2010, art. 5º):'+(s.supplier?` preferência: ${s.supplier}.`:''));
    for(const b of brands){add('p',b.label).style.fontWeight='bold';if(b.materials.length)table(b.materials.map((/** @type {any} */ m)=>[t.opme[m.item_index]?.description||'',`${m.tuss_code} ${m.term}`,m.manufacturer,m.anvisa]),['Item','Material (TUSS 19)','Fabricante','Anvisa']);}}
  if(science&&science.references.length){
    add('h2','Fundamentação científica');
    add('p',`Afirmação clínica: ${science.claim}`);
    for(const r of science.references)add('p',`[${r.number}] ${DIRECTIONS[/** @type {keyof typeof DIRECTIONS} */(r.direction)]||r.direction}${r.study?` (${r.study})`:''}: "${r.quote}"`);
    add('p','Referências (Vancouver):');const ol=doc.createElement('ol');for(const r of science.references)add('li',r.vancouver,ol);doc.body.append(ol);
    add('p','Trechos literais dos resumos publicados; artigos classificados com confirmação do médico e metadados verificados no PubMed e no Crossref.').className='small';}
  if(t&&t.sbot_entry)add('p',`Codificação conforme SBOT, Manual de Diretrizes de Codificação, procedimento ${t.sbot_entry}.`).className='small';
  if(check&&check.deadline)add('p',check.deadline).className='small';
  add('p','Anexos: laudos dos exames e termo de consentimento assinado.');
  add('p',`${profile.city?profile.city+', ':''}${new Date().toLocaleDateString('pt-BR',{day:'numeric',month:'long',year:'numeric'})}.`);
  const sign=add('div','');sign.className='sign';sign.append(doc.createTextNode('_______________________________________'),doc.createElement('br'),
    doc.createTextNode(profile.name||'Médico assistente'),doc.createElement('br'),doc.createTextNode([profile.crm?`CRM-${profile.uf||''} ${profile.crm}`:'CRM',profile.rqe?`RQE ${profile.rqe}`:''].filter(Boolean).join(' · ')));
  applyLetterhead(doc,letterhead,profile);
  return '<!doctype html>\n'+doc.documentElement.outerHTML;
}

/** Prescription pad with the patient's name from this session. @param {import('./evidence.js').EvidenceClient} client */
export function prescription(client){return prescriptionPage(client,patient,dictation,download);}

/** What the contestation page may use from the open case: ids for removal, patient data for the local header only. */
export function caseContext(){
  return {caseId:current?current.id:null,hasFacts:Boolean(current&&current.view.confirmed),identifiers:identifiers(),
    patient:/** @type {Record<string,string>} */({...patient})};
}

