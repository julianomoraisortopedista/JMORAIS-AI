/** Contestations: draft a point-by-point reply to an insurer and keep a library of past ones. */
import {el} from './view.js';
import {box,button,busy,download,field,input,say,select,session,textarea} from './evidence.js';
import {templatePicker} from './catalog.js';
import {applyLetterhead,practice,printModeSelect} from './letterhead.js';

const KINDS=/** @type {[string,string][]} */ ([['NEGATIVA','Negativa de autorização'],['GLOSA','Glosa'],['JUNTA_MEDICA','Junta médica / divergência técnica']]);
const OUTCOMES=/** @type {[string,string][]} */ ([['PENDENTE','Pendente'],['DEFERIDA','Deferida'],['PARCIAL','Parcialmente deferida'],['INDEFERIDA','Indeferida']]);
/** @param {string} k */ const kindLabel=(k)=>(KINDS.find(x=>x[0]===k)||['',k])[1];

/** @param {File} file @returns {Promise<string>} */
async function base64(file){const bytes=new Uint8Array(await file.arrayBuffer());let bin='';for(let i=0;i<bytes.length;i+=0x8000)bin+=String.fromCharCode(...bytes.subarray(i,i+0x8000));return btoa(bin);}

/** @typedef {{caseId:string|null,hasFacts:boolean,identifiers:Record<string,string>,patient:Record<string,string>}} CaseContext */

/** @param {import('./evidence.js').EvidenceClient} client @param {()=>CaseContext} caseContext @param {(t:HTMLTextAreaElement)=>HTMLElement} dictation */
export function appealsPage(client,caseContext,dictation){
  const root=box('div','page-grid');
  const library=libraryCard(client);
  root.append(draftCard(client,caseContext,dictation,()=>library.dispatchEvent(new Event('reload'))),library);
  return root;
}

/** @param {import('./evidence.js').EvidenceClient} client @param {()=>CaseContext} caseContext @param {(t:HTMLTextAreaElement)=>HTMLElement} dictation @param {()=>void} reloadLibrary */
function draftCard(client,caseContext,dictation,reloadLibrary){
  const card=box('section','card');
  card.append(box('h2','card-title','Nova contestação'),
    box('p','muted','Cole ou anexe a negativa, a glosa ou o parecer da junta. Os dados do paciente são removidos antes da IA. O Claude responde a cada argumento usando os fatos do caso, a SBOT e as normas da plataforma, e segue as suas contestações deferidas da biblioteca como modelo.'));
  const kind=select(KINDS);const procedure=input('Ex.: Artroplastia total do joelho direito');
  /** @type {string|null} */ let templateId=null;
  const picker=templatePicker(client,(t)=>{templateId=t?t.template_id:null;if(t&&!procedure.value)procedure.value=t.name;});
  const denial=textarea('Cole aqui o texto da negativa / glosa / parecer da operadora');denial.rows=8;
  const file=document.createElement('input');file.type='file';file.accept='.pdf,.docx,.txt';
  const ctx=caseContext();const useCase=document.createElement('input');useCase.type='checkbox';useCase.checked=ctx.hasFacts;useCase.disabled=!ctx.hasFacts;
  const caseLabel=box('label','chip');caseLabel.append(useCase,el('span',ctx.hasFacts?'Usar os fatos confirmados do caso aberto em Pedido médico':'Nenhum caso com fatos confirmados (opcional: abra em Pedido médico)'));
  const grid=box('div','form-grid');grid.append(field('Tipo',kind),field('Procedimento',procedure));
  const go=button(session.model?'Redigir contestação com o Claude':'IA não configurada');go.disabled=!session.model;
  const status=box('div','status-area');const result=box('div','');const a=box('div','actions');a.append(go);
  card.append(grid,picker,field('Texto da operadora',denial),dictation(denial),field('Ou anexe o documento da operadora',file),caseLabel,a,status,result);
  go.onclick=()=>busy(go,async()=>{
    result.replaceChildren();
    try{
      const f=file.files?.[0];if(f&&f.size>700000)throw new Error('Arquivo acima de 700 KB.');
      if(!f&&denial.value.trim().length<20)throw new Error('Cole ou anexe o texto da operadora.');
      const c=caseContext();
      say(status,'O Claude está redigindo a contestação…','info');
      let job=await client.appealDraft({kind:kind.value,denial_text:denial.value,denial_file:f?{name:f.name,content_base64:await base64(f)}:null,
        identifiers:c.identifiers,case_id:useCase.checked?c.caseId:null,template_id:templateId,procedure:procedure.value});
      for(let i=0;i<90&&job.status==='RUNNING';i++){await new Promise(r=>setTimeout(r,2000));job=await client.appealDraftGet(job.job_id);}
      if(job.status!=='READY')throw new Error(job.error||'Falha ao redigir.');
      say(status,`Contestação redigida${job.examples?` usando ${job.examples} contestação(ões) sua(s) da biblioteca como modelo`:''}.${job.dropped?` ${job.dropped} frase(s) sem fonte foram descartadas.`:''} Revise antes de enviar.`,'ok');
      renderDraft(client,result,job,kind.value,procedure.value,caseContext,reloadLibrary);
    }catch(e){say(status,e instanceof Error?e.message:'Falha.');}
  });
  return card;
}

/** @param {import('./evidence.js').EvidenceClient} client @param {HTMLElement} target @param {any} job @param {string} kind @param {string} procedure @param {()=>CaseContext} caseContext @param {()=>void} reloadLibrary */
function renderDraft(client,target,job,kind,procedure,caseContext,reloadLibrary){
  /** @type {[string,HTMLTextAreaElement][]} */ const areas=[];
  for(const g of job.gaps||[])target.append(box('div','alert alert-warn','Lacuna: '+g));
  for(const sec of job.sections){const t=textarea('');t.value=sec.sentences.map((/** @type {any} */ s)=>s.text).join(' ');t.rows=Math.max(3,Math.min(12,Math.ceil(t.value.length/110)));
    const ids=[...new Set(sec.sentences.flatMap((/** @type {any} */ s)=>s.source_ids))];
    target.append(field(sec.title,t,ids.length?'Fontes — '+ids.map(i=>`${i}: ${job.sources[i]||''}`).join(' · '):'Sem conteúdo com fonte — escreva se necessário'));areas.push([sec.title,t]);}
  const open=button('Abrir contestação'),save=button('Baixar (.html)','ghost'),keep=button('Salvar na biblioteca','ghost');const st=box('div','status-area');
  const a=box('div','actions');a.append(printModeSelect(),open,save,keep);target.append(a,st);
  const build=async()=>{const {letterhead,profile}=await practice(client);const p=caseContext().patient;
    const doc=document.implementation.createHTMLDocument('Contestação');const meta=doc.createElement('meta');meta.setAttribute('charset','utf-8');doc.head.prepend(meta);
    const style=doc.createElement('style');style.textContent='body{font-family:Georgia,serif;max-width:780px;margin:28px auto;padding:0 16px;color:#111;line-height:1.55;font-size:14px}h1{text-align:center;font-size:17px}h2{font-size:13.5px;margin:18px 0 4px;text-transform:uppercase}td{padding:2px 6px}.sign{margin-top:48px;text-align:center}.draft{border:1px solid #b45309;color:#b45309;padding:6px 10px;font-size:12px}@media print{.draft{display:none}}';doc.head.append(style);
    /** @param {string} tag @param {string} txt @param {HTMLElement} [parent] */ const add=(tag,txt,parent)=>{const e=doc.createElement(tag);e.textContent=txt;(parent||doc.body).append(e);return e;};
    add('div','RASCUNHO — revise e assine antes de enviar. Este aviso não aparece na impressão.').className='draft';
    if(p.operadora)add('p',`À ${p.operadora} — Setor de Auditoria / Recursos`);
    add('h1',`CONTESTAÇÃO DE ${kindLabel(kind).toUpperCase()}`);
    const tb=doc.createElement('table');for(const [k,v] of [['Paciente',p.name],['Carteirinha',p.card_number],['Procedimento',procedure]]){if(!v)continue;const tr=doc.createElement('tr');add('td',k+':',tr);add('td',v,tr);tb.append(tr);}doc.body.append(tb);
    for(const [title,t] of areas){if(!t.value.trim())continue;add('h2',title);for(const para of t.value.split(/\n+/))if(para.trim())add('p',para.trim());}
    add('p',`${profile.city?profile.city+', ':''}${new Date().toLocaleDateString('pt-BR',{day:'numeric',month:'long',year:'numeric'})}.`);
    const sign=add('div','');sign.className='sign';sign.append(doc.createTextNode('_______________________________________'),doc.createElement('br'),doc.createTextNode(profile.name||'Médico assistente'),doc.createElement('br'),
      doc.createTextNode([profile.crm?`CRM-${profile.uf||''} ${profile.crm}`:'CRM',profile.rqe?`RQE ${profile.rqe}`:''].filter(Boolean).join(' · ')));
    applyLetterhead(doc,letterhead,profile);return '<!doctype html>\n'+doc.documentElement.outerHTML;};
  open.onclick=()=>busy(open,async()=>{const html=await build();const url=URL.createObjectURL(new Blob([html],{type:'text/html'}));if(!window.open(url,'_blank'))download('contestacao.html',html,'text/html');setTimeout(()=>URL.revokeObjectURL(url),60000);});
  save.onclick=()=>busy(save,async()=>download('contestacao.html',await build(),'text/html'));
  keep.onclick=()=>busy(keep,async()=>{try{const text=areas.filter(([,t])=>t.value.trim()).map(([title,t])=>`${title}\n${t.value.trim()}`).join('\n\n');
    await client.appealSave({kind,procedure,outcome:'PENDENTE',text,confirmed:true});say(st,'Salva na biblioteca como "Pendente". Atualize o resultado quando a operadora responder.','ok');reloadLibrary();}
    catch(e){say(st,e instanceof Error?e.message:'Falha ao salvar.');}});
}

/** @param {import('./evidence.js').EvidenceClient} client */
function libraryCard(client){
  const card=box('section','card');
  card.append(box('h2','card-title','Biblioteca de contestações'),
    box('p','muted','Anexe as contestações que você já fez. A identificação é removida aqui, sem IA; confira o texto, apague o que ainda identificar alguém e salve com o tipo, o procedimento e o resultado. As deferidas do mesmo procedimento viram modelo para as novas. Fica só neste computador.'));
  const file=document.createElement('input');file.type='file';file.accept='.pdf,.docx,.txt';
  const text=textarea('O texto sem identificação aparece aqui.');text.rows=10;
  const kind=select(KINDS),outcome=select(OUTCOMES),procedure=input('Procedimento');
  const ok=document.createElement('input');ok.type='checkbox';const okLabel=box('label','chip');okLabel.append(ok,el('span','Conferi: o texto não tem dados de paciente'));
  const save=button('Salvar na biblioteca');const status=box('div','status-area');const list=box('div','rows');
  const grid=box('div','form-grid');grid.append(field('Tipo',kind),field('Procedimento',procedure),field('Resultado',outcome));
  const a=box('div','actions');a.append(save);
  card.append(field('Arquivo da contestação',file),field('Texto',text),grid,okLabel,a,status,box('h3','section-title','Contestações salvas'),list);
  const reload=async()=>{try{const r=await client.appeals();list.replaceChildren();
      if(!r.entries.length)list.append(box('p','muted','Nenhuma contestação ainda.'));
      for(const e of r.entries){const row=box('div','row');const m=box('div','row-main');
        m.append(box('strong','',`${kindLabel(e.kind)} · ${e.procedure||'sem procedimento'}`),box('span','muted',`${e.created_at} · ${e.chars} caracteres — ${e.preview}…`));
        const out=select(OUTCOMES);out.value=e.outcome;out.setAttribute('aria-label','Resultado');out.onchange=async()=>{try{await client.appealOutcome(e.appeal_id,out.value);}catch{out.value=e.outcome;}};
        const del=button('Excluir','quiet');del.onclick=()=>busy(del,async()=>{await client.appealDelete(e.appeal_id);await reload();});
        row.append(m,out,del);list.append(row);}
    }catch(e){say(list,e instanceof Error?e.message:'Biblioteca indisponível.','info');}};
  card.addEventListener('reload',()=>{reload();});
  file.onchange=async()=>{const f=file.files?.[0];if(!f)return;
    if(f.size>700000){say(status,'Arquivo acima de 700 KB.');file.value='';return;}
    try{const r=await client.appealPreview({name:f.name,content_base64:await base64(f)});text.value=r.text;ok.checked=false;file.value='';
      const counts=Object.entries(r.removed||{}).map(([k,v])=>`${v} ${String(k).toLowerCase()}`).join(', ');
      say(status,'Identificação removida'+(counts?` (${counts})`:'')+'. Confira, apague o que ainda identificar alguém e salve.','info');}
    catch(e){file.value='';say(status,e instanceof Error?e.message:'Falha ao ler.');}};
  save.onclick=()=>busy(save,async()=>{
    if(!ok.checked){say(status,'Marque que conferiu que o texto não tem dados de paciente.');return;}
    try{await client.appealSave({kind:kind.value,procedure:procedure.value,outcome:outcome.value,text:text.value,confirmed:true});
      text.value='';procedure.value='';ok.checked=false;say(status,'Contestação salva na biblioteca.','ok');await reload();}
    catch(e){say(status,e instanceof Error?e.message:'Falha ao salvar.');}});
  reload();return card;
}
