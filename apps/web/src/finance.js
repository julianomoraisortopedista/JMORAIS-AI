/** Surgeries performed, invoices and payments: import, reconcile and follow up. Local data, no AI. */
import {el} from './view.js';
import {box,button,busy,field,input,pill,say,select} from './evidence.js';

/** @param {number} cents */
const brl=(cents)=>(cents/100).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
/** @param {string} iso */
const br=(iso)=>iso?iso.split('-').reverse().join('/'):'';
const STATUS=/** @type {Record<string,[string,string]>} */ ({REALIZADA:['Realizada','PENDENTE'],FATURADA:['Faturada','NEUTRAL'],PAGA_PARCIAL:['Paga a menor','NAO_ATENDIDO'],PAGA:['Paga','SUPPORTING']});

/** @param {File} file @returns {Promise<string>} */
async function base64(file){const bytes=new Uint8Array(await file.arrayBuffer());let bin='';for(let i=0;i<bytes.length;i+=0x8000)bin+=String.fromCharCode(...bytes.subarray(i,i+0x8000));return btoa(bin);}

/** @param {string[]} headers @param {Array<Array<string|HTMLElement>>} rows */
function table(headers,rows){
  const t=document.createElement('table');t.className='data-table';const tr=document.createElement('tr');
  for(const h of headers)tr.append(el('th',h));t.append(tr);
  for(const r of rows){const row=document.createElement('tr');for(const c of r){const td=document.createElement('td');if(typeof c==='string')td.textContent=c;else td.append(c);row.append(td);}t.append(row);}
  const wrap=box('div','table-wrap');wrap.append(t);return wrap;
}

/** @param {import('./evidence.js').EvidenceClient} client */
export function financePage(client){
  const root=box('div','page-grid');
  const stats=box('div','stats');const alerts=box('section','card');const months=box('section','card');
  const surgeries=box('section','card');const imports=box('section','card');const links=box('section','card');
  root.append(stats,alerts,imports,surgeries,months,links);
  const reload=async()=>{
    try{
      const [p,s,inv,pay,sug]=await Promise.all([client.financePanel(),client.financeSurgeries(),client.financeInvoices(),client.financePayments(),client.financeSuggestions()]);
      renderStats(stats,p.totals);renderAlerts(alerts,p.alerts);renderMonths(months,p.months);
      renderSurgeries(client,surgeries,s.surgeries,p.statuses,inv.invoices,reload);
      renderLinks(client,links,inv.invoices,pay.payments,sug.suggestions,s.surgeries,reload);
    }catch(e){say(alerts,e instanceof Error?e.message:'Controle financeiro indisponível.');}
  };
  renderImports(client,imports,reload);reload();return root;
}

/** @param {HTMLElement} target @param {Record<string,number>} t */
function renderStats(target,t){
  /** @param {string} label @param {string} value @param {string} hint */
  const stat=(label,value,hint)=>{const s=box('div','stat');s.append(box('span','stat-label',label),box('strong','stat-value',value),box('span','muted',hint));return s;};
  target.replaceChildren(stat('Cirurgias',String(t.cirurgias),'registradas'),stat('Previsto',brl(t.previsto),'honorários'),stat('Faturado',brl(t.faturado),'notas emitidas'),
    stat('Recebido',brl(t.recebido),'repasses'),stat('A faturar',brl(t.a_faturar),'cirurgias sem nota'),stat('A receber',brl(t.a_receber),'notas em aberto'));
}

/** @param {HTMLElement} target @param {any[]} alerts */
function renderAlerts(target,alerts){
  target.replaceChildren(box('h2','card-title','Alertas'));
  if(!alerts.length){target.append(box('p','muted','Nada pendente.'));return;}
  for(const a of alerts.slice(0,60))target.append(box('div','alert alert-'+(a.level==='BLOQUEIO'?'error':a.level==='INFO'?'info':'warn'),a.message));
  if(alerts.length>60)target.append(box('p','muted',`+${alerts.length-60} alertas`));
}

/** @param {HTMLElement} target @param {any[]} rows */
function renderMonths(target,rows){
  target.replaceChildren(box('h2','card-title','Por mês e hospital'));
  if(!rows.length){target.append(box('p','muted','Sem dados ainda.'));return;}
  target.append(table(['Mês','Hospital / pagador','Cirurgias','Previsto','Faturado','Recebido'],
    rows.map(r=>[r.month.split('-').reverse().join('/'),r.hospital,String(r.cirurgias),brl(r.previsto),brl(r.faturado),brl(r.recebido)])));
}

/** @param {import('./evidence.js').EvidenceClient} client @param {HTMLElement} target @param {any[]} list @param {Record<string,string>} statuses @param {any[]} invoices @param {()=>void} reload */
function renderSurgeries(client,target,list,statuses,invoices,reload){
  target.replaceChildren(box('h2','card-title','Cirurgias'));
  const q=input('Filtrar por paciente, hospital, procedimento ou mês (ex.: 2026-09)');const add=button('+ Cirurgia','ghost');
  const bar=box('div','actions');bar.append(add);target.append(q,bar);
  const holder=box('div','');target.append(holder);
  const nf=Object.fromEntries(invoices.map(i=>[i.id,i.number]));
  const draw=()=>{const f=q.value.trim().toLowerCase();
    const rows=list.filter(s=>!f||[s.date,s.hospital,s.patient,s.procedure,s.insurer].join(' ').toLowerCase().includes(f)).slice(0,300).map(s=>{
      const [label,tone]=STATUS[statuses[s.id]]||['—','muted'];const del=button('Excluir','quiet');
      del.onclick=()=>busy(del,async()=>{await client.financeSurgeryDelete(s.id);reload();});
      return [br(s.date),s.hospital,s.insurer,s.patient,s.procedure,brl(s.expected_cents),s.invoice_id?`NF ${nf[s.invoice_id]||''}`:'—',pill(label,tone),del];});
    holder.replaceChildren(rows.length?table(['Data','Hospital','Convênio','Paciente','Procedimento','Previsto','Nota','Status',''],rows):box('p','muted','Nenhuma cirurgia. Importe a sua planilha acima ou adicione.'));};
  q.oninput=draw;draw();
  add.onclick=()=>{const form=box('div','form-grid');
    /** @type {Record<string,HTMLInputElement>} */ const f={};
    for(const [k,l,t] of /** @type {[string,string,string][]} */([['date','Data','date'],['hospital','Hospital','text'],['insurer','Convênio','text'],['patient','Paciente','text'],['card','Carteirinha','text'],['procedure','Procedimento','text'],['codes','TUSS','text'],['role','Função','text'],['expected','Valor previsto (R$)','text'],['guide','Guia/senha','text']])){
      const i=input(l);i.type=t;f[k]=i;form.append(field(l,i));}
    const save=button('Salvar cirurgia');const st=box('div','status-area');const a=box('div','actions');a.append(save);holder.prepend(form,a,st);
    save.onclick=()=>busy(save,async()=>{try{await client.financeSurgerySave({date:f.date.value,hospital:f.hospital.value,insurer:f.insurer.value,patient:f.patient.value,card:f.card.value,
      procedure:f.procedure.value,codes:f.codes.value,role:f.role.value,expected_cents:Math.round(Number(f.expected.value.replace(/\./g,'').replace(',','.'))*100)||0,guide:f.guide.value});reload();}
      catch(e){say(st,e instanceof Error?e.message:'Falha.');}});};
}

/** @param {import('./evidence.js').EvidenceClient} client @param {HTMLElement} target @param {()=>void} reload */
function renderImports(client,target,reload){
  target.replaceChildren(box('h2','card-title','Importar'),box('p','muted','Tudo fica neste computador e nada vai para a IA. Duplicados são ignorados e os vínculos certos (paciente citado na nota, número da nota citado no pagamento) são feitos sozinhos.'));
  // Spreadsheet: preview, then import.
  const sheet=document.createElement('input');sheet.type='file';sheet.accept='.xlsx,.csv';const sheetStatus=box('div','status-area');const sheetPreview=box('div','');
  sheet.onchange=async()=>{const f=sheet.files?.[0];if(!f)return;
    try{const body={name:f.name,content_base64:await base64(f)};const r=await client.financeImportSurgeries({...body,commit:false});
      const mapped=Object.entries(r.mapping).map(([k,i])=>`${k} ← "${r.headers[Number(i)]}"`).join(' · ');
      sheetPreview.replaceChildren(box('p','muted',`Colunas reconhecidas: ${mapped}`),
        table(['Data','Hospital','Paciente','Procedimento','Valor'],r.preview.map((/** @type {any} */ s)=>[br(s.date),s.hospital,s.patient,s.procedure,brl(s.expected_cents)])));
      const go=button(`Importar ${r.count} cirurgia(s)`);const a=box('div','actions');a.append(go);sheetPreview.append(a);
      if(r.skipped.length)sheetPreview.append(box('div','alert alert-warn','Ignoradas: '+r.skipped.join('; ')));
      go.onclick=()=>busy(go,async()=>{try{const done=await client.financeImportSurgeries({...body,commit:true});sheet.value='';sheetPreview.replaceChildren();
        say(sheetStatus,`${done.added} cirurgia(s) importada(s); ${done.duplicates} já existiam; ${done.linked} vínculo(s) automático(s).`,'ok');reload();}catch(e){say(sheetStatus,e instanceof Error?e.message:'Falha.');}});
    }catch(e){sheet.value='';say(sheetStatus,e instanceof Error?e.message:'Falha ao ler a planilha.');}};
  // Invoices: one or many files.
  const nf=document.createElement('input');nf.type='file';nf.multiple=true;nf.accept='.xml,.pdf';const nfStatus=box('div','status-area');
  nf.onchange=async()=>{let added=0,dup=0,linked=0;const errors=[];
    for(const f of Array.from(nf.files||[])){try{const r=await client.financeImportInvoices({name:f.name,content_base64:await base64(f)});added+=r.added;dup+=r.duplicates;linked+=r.linked;}catch(e){errors.push(`${f.name}: ${e instanceof Error?e.message:'falha'}`);}}
    nf.value='';say(nfStatus,`${added} nota(s) importada(s); ${dup} já existiam; ${linked} vínculo(s) automático(s).`+(errors.length?' Erros: '+errors.join('; '):''),errors.length?'error':'ok');reload();};
  // Payments: e-mails dragged from Mail, statements.
  const pay=document.createElement('input');pay.type='file';pay.multiple=true;pay.accept='.eml,.pdf,.xlsx,.csv';const payer=input('Pagador (ex.: Hospital Santa Cruz) — opcional para e-mail');const payStatus=box('div','status-area');
  pay.onchange=async()=>{let added=0,dup=0,linked=0;const errors=[];
    for(const f of Array.from(pay.files||[])){try{const r=await client.financeImportPayments({name:f.name,payer:payer.value,content_base64:await base64(f)});added+=r.added;dup+=r.duplicates;linked+=r.linked;}catch(e){errors.push(`${f.name}: ${e instanceof Error?e.message:'falha'}`);}}
    pay.value='';say(payStatus,`${added} pagamento(s) importado(s); ${dup} já existiam; ${linked} vínculo(s) automático(s).`+(errors.length?' Erros: '+errors.join('; '):''),errors.length?'error':'ok');reload();};
  target.append(field('1. Planilha de cirurgias (.xlsx ou .csv)',sheet),sheetStatus,sheetPreview,
    field('2. Notas fiscais emitidas (XML da NFS-e ou PDF; pode selecionar várias)',nf),nfStatus,
    field('3. Repasses: e-mails de pagamento (arraste do Mail como .eml) ou demonstrativos',pay),payer,payStatus);
}

/** @param {import('./evidence.js').EvidenceClient} client @param {HTMLElement} target @param {any[]} invoices @param {any[]} payments @param {any[]} suggestions @param {any[]} surgeries @param {()=>void} reload */
function renderLinks(client,target,invoices,payments,suggestions,surgeries,reload){
  target.replaceChildren(box('h2','card-title','Notas, pagamentos e vínculos'));
  const byId=Object.fromEntries(invoices.map(i=>[i.id,i]));const surg=Object.fromEntries(surgeries.map(s=>[s.id,s]));const pays=Object.fromEntries(payments.map(p=>[p.id,p]));
  const pending=suggestions.filter(s=>!s.certain);
  if(pending.length){target.append(box('h3','section-title','Sugestões para confirmar'));
    for(const s of pending){const left=s.kind==='SURGERY_INVOICE'?surg[s.left_id]:pays[s.left_id];const inv=byId[s.invoice_id];if(!left||!inv)continue;
      const row=box('div','row');const m=box('div','row-main');
      m.append(box('strong','',s.kind==='SURGERY_INVOICE'?`Cirurgia ${br(left.date)} · ${left.patient} → NF ${inv.number}`:`Pagamento ${br(left.date)} · ${brl(left.value_cents)} → NF ${inv.number}`),box('span','muted',s.reason));
      const ok=button('Vincular','ghost');ok.onclick=()=>busy(ok,async()=>{await client.financeLink({kind:s.kind,left_id:s.left_id,invoice_id:s.invoice_id});reload();});row.append(m,ok);target.append(row);}}
  const options=[['','— sem nota —'],...invoices.map(i=>[i.id,`NF ${i.number} · ${br(i.issue_date)} · ${brl(i.value_cents)}`])];
  target.append(box('h3','section-title','Notas fiscais'));
  target.append(invoices.length?table(['NF','Emissão','Tomador','Valor',''],invoices.map(i=>{const del=button('Excluir','quiet');del.onclick=()=>busy(del,async()=>{await client.financeInvoiceDelete(i.id);reload();});return [i.number,br(i.issue_date),i.hospital,brl(i.value_cents),del];})):box('p','muted','Nenhuma nota importada.'));
  target.append(box('h3','section-title','Pagamentos recebidos'));
  target.append(payments.length?table(['Data','Pagador','Valor','Referência','Nota',''],payments.map(p=>{const s=select(/** @type {[string,string][]} */(options));s.value=p.invoice_id||'';s.setAttribute('aria-label','Nota do pagamento');
      s.onchange=async()=>{await client.financeLink({kind:'PAYMENT_INVOICE',left_id:p.id,invoice_id:s.value||null});reload();};
      const del=button('Excluir','quiet');del.onclick=()=>busy(del,async()=>{await client.financePaymentDelete(p.id);reload();});
      return [br(p.date),p.payer,brl(p.value_cents),p.reference||p.description.slice(0,60),s,del];})):box('p','muted','Nenhum pagamento importado.'));
}
