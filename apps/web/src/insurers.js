/** Authorization playbook: insurers, denial reasons with prevention and response, recorded cases and outcomes. */
import {el} from './view.js';
import {box,button,busy,field,input,say,select,textarea} from './evidence.js';

const OUTCOME=/** @type {Record<string,string>} */ ({APROVADO:'Aprovado',APROVADO_PARCIAL:'Aprovado em parte',NEGADO:'Negado',REVERTIDO:'Revertido',MANTIDO:'Negativa mantida',PENDENTE:'Pendente'});

/** @param {import('./evidence.js').EvidenceClient} client */
export function insurersPage(client){
  const root=box('div','page-grid');const status=box('div','status-area');
  const head=box('section','card');
  head.append(box('h2','card-title','Convênios: táticas e resultados'),
    box('p','muted','O que cada convênio nega, como responder e o que já deu certo. Sem dados de pacientes. Normas conferidas e artigos com PMID são reconferidos quando usados no pedido ou na contestação.'),status);
  root.append(head);
  const reload=async()=>{
    try{const book=await client.playbook();root.replaceChildren(head);
      const reasons=Object.fromEntries(book.reasons.map((/** @type {any} */ r)=>[r.reason_id,r]));
      for(const i of book.insurers)root.append(insurerCard(client,i,book.cases.filter((/** @type {any} */ c)=>c.insurer_id===i.insurer_id),reasons,reload));
      root.append(reasonsCard(book.reasons),addCaseCard(client,book,reload));
    }catch(e){say(status,e instanceof Error?e.message:'Falha.');}
  };
  reload();return root;
}

/** @param {string} title @param {string[]} items */
function list(title,items){const w=box('div','');if(!items.length)return w;w.append(box('h3','section-title',title));const ul=el('ul');for(const t of items)ul.append(el('li',t));w.append(ul);return w;}

/** @param {import('./evidence.js').EvidenceClient} client @param {any} i @param {any[]} cases @param {Record<string,any>} reasons @param {()=>Promise<void>} reload */
function insurerCard(client,i,cases,reasons,reload){
  const card=box('section','card');
  const record=Object.entries(cases.reduce((/** @type {Record<string,number>} */ a,c)=>{a[c.outcome]=(a[c.outcome]||0)+1;return a;},{})).map(([k,v])=>`${v} ${OUTCOME[k]||k}`).join(' · ');
  card.append(box('h2','card-title',i.name),box('p','muted',i.route),box('p','',record?`${cases.length} caso(s): ${record}`:'Nenhum caso registrado.'));
  card.append(list('Táticas observadas',i.tactics),list('O que funcionou',i.responses),list('Avisos no pedido',i.rules.map((/** @type {any} */ r)=>(r.codes.length?`[${r.codes.join(', ')}] `:'')+r.message)));
  if(i.reviewers.length){card.append(box('h3','section-title','Auditores e desempatadores'));
    for(const r of i.reviewers)card.append(box('p','muted',`${r.name}${r.registry?' ('+r.registry+')':''}${r.role?' — '+r.role:''}${r.note?': '+r.note:''}`));}
  if(cases.length){card.append(box('h3','section-title','Casos'));
    for(const c of cases){const row=box('div','row');const m=box('div','row-main');
      m.append(box('strong','',`${c.on.split('-').reverse().join('/')} · ${c.stage||'pedido'}${c.region?' · '+c.region:''}`),
        box('span','muted',c.lines.map((/** @type {any} */ l)=>`${l.code} ${l.requested}→${l.authorized??'?'}`).join('; ')),
        box('span','muted',c.reasons.map((/** @type {string} */ r)=>(reasons[r]||{label:r}).label).join(' · ')));
      if(c.notes)m.append(box('span','muted',c.notes));
      const out=select(Object.entries(OUTCOME));out.value=c.outcome;
      out.onchange=async()=>{try{await client.playbookOutcome(c.case_id,out.value);await reload();}catch{out.value=c.outcome;}};
      row.append(m,out);card.append(row);}}
  return card;
}

/** @param {any[]} reasons */
function reasonsCard(reasons){
  const card=box('section','card');card.append(box('h2','card-title','Motivos de negativa: prevenção e resposta'));
  for(const r of reasons){const d=document.createElement('details');const s=document.createElement('summary');s.textContent=r.label;d.append(s);
    d.append(list('Prevenir no pedido',r.prevention),list('Responder',r.response));
    if(r.legal.length)d.append(box('p','muted','Normas conferidas: '+r.legal.join(', ')));
    if(r.evidence.length)d.append(box('p','muted','Artigos (PMID, importe na biblioteca da cirurgia): '+r.evidence.join(' ')));
    card.append(d);}
  return card;
}

/** @param {import('./evidence.js').EvidenceClient} client @param {any} book @param {()=>Promise<void>} reload */
function addCaseCard(client,book,reload){
  const card=box('section','card');card.append(box('h2','card-title','Registrar caso'),box('p','muted','Sem nome, CPF ou carteirinha. Uma linha por item: código ou material, quantidade pedida, quantidade autorizada. Ex.: 31403026;6;4'));
  const ins=select(book.insurers.map((/** @type {any} */ i)=>[i.insurer_id,i.name]));
  const on=document.createElement('input');on.type='date';on.value=new Date().toISOString().slice(0,10);
  const stage=input('pedido, consenso, junta, 2ª opinião');const region=input('joelho, ombro, coluna…');
  const lines=textarea('31403026;6;4\nkit Easy Block;2;0');lines.rows=4;
  const boxes=book.reasons.map((/** @type {any} */ r)=>{const c=document.createElement('input');c.type='checkbox';const l=box('label','chip');l.append(c,el('span',r.label));return {id:r.reason_id,c,l};});
  const chips=box('div','chips');for(const b of boxes)chips.append(b.l);
  const outcome=select(Object.entries(OUTCOME));outcome.value='PENDENTE';const notes=textarea('Observações (sem dados do paciente)');notes.rows=3;
  const save=button('Registrar');const st=box('div','status-area');
  const grid=box('div','form-grid');grid.append(field('Convênio',ins),field('Data',on),field('Etapa',stage),field('Região',region));
  card.append(grid,field('Itens',lines),field('Motivos',chips),field('Resultado',outcome),field('Observações',notes),save,st);
  save.onclick=()=>busy(save,async()=>{
    try{const parsed=lines.value.split('\n').map(x=>x.trim()).filter(Boolean).map(x=>{const [code,req,aut]=x.split(';').map(y=>y.trim());
        return {code,requested:Number(req)||0,authorized:aut===undefined||aut===''?null:Number(aut)};});
      await client.playbookCaseAdd({insurer_id:ins.value,on:on.value,stage:stage.value,region:region.value,lines:parsed,
        reasons:boxes.filter((/** @type {any} */ b)=>b.c.checked).map((/** @type {any} */ b)=>b.id),outcome:outcome.value,notes:notes.value});
      say(st,'Caso registrado.','ok');await reload();}
    catch(e){say(st,e instanceof Error?e.message:'Falha.');}});
  return card;
}
