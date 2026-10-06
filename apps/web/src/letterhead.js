/** Practice letterhead for every printed document (built with DOM APIs, never HTML strings). */
import {box,button,busy,field,input,say,select,textarea} from './evidence.js';

/** @typedef {{logo_base64:string,logo_type:string,header_lines:string[],footer:string,color:string}} Letterhead */
/** @typedef {Record<string,string>} Profile */

/** Print mode chosen by the physician for this session: 'full' (logo and header) or 'plain' (pre-printed paper). */
export const printing={mode:'full'};

/** @returns {HTMLSelectElement} */
export function printModeSelect(){
  const s=select([['full','Com logo e cabeçalho'],['plain','Sem cabeçalho (papel timbrado)']]);s.value=printing.mode;
  s.onchange=()=>{printing.mode=s.value;};s.setAttribute('aria-label','Modelo de impressão');return s;
}

/** @param {import('./evidence.js').EvidenceClient} client @returns {Promise<{letterhead:Letterhead,profile:Profile}>} */
export async function practice(client){
  const [letterhead,profile]=await Promise.all([client.letterheadGet().catch(()=>({logo_base64:'',logo_type:'',header_lines:[],footer:'',color:'#0f3d5e'})),
    client.profileGet().catch(()=>({}))]);
  return {letterhead,profile};
}

/** Default header lines from the profile. @param {Profile} p */
export function profileLines(p){
  return [p.name,[p.specialty,p.crm?`CRM-${p.uf||''} ${p.crm}`:'',p.rqe?`RQE ${p.rqe}`:''].filter(Boolean).join(' · ')].filter(Boolean);
}

/** Wrap the body of a generated document with the letterhead (or blank space for pre-printed paper).
 * @param {Document} doc @param {Letterhead} lh @param {Profile} profile @param {string} [mode] */
export function applyLetterhead(doc,lh,profile,mode=printing.mode){
  const style=doc.createElement('style');
  const color=/^#[0-9a-f]{6}$/i.test(lh.color||'')?lh.color:'#0f3d5e';
  style.textContent=`.lh-head{display:flex;align-items:center;gap:16px;border-bottom:2px solid ${color};padding-bottom:8px;margin-bottom:12px}`+
    `.lh-head img{max-height:72px;max-width:180px}.lh-lines{line-height:1.35}.lh-lines div:first-child{font-weight:bold;font-size:16px;color:${color}}`+
    `.lh-foot{border-top:1px solid ${color};margin-top:28px;padding-top:6px;font-size:11px;color:#444;text-align:center}.lh-space{height:3.2cm}`+
    `@media print{.lh-foot{position:fixed;bottom:0;left:0;right:0;background:#fff}body{margin-bottom:2cm}}`;
  doc.head.append(style);
  const first=doc.body.firstChild;
  if(mode==='plain'){const space=doc.createElement('div');space.className='lh-space';doc.body.insertBefore(space,first);return;}
  const head=doc.createElement('div');head.className='lh-head';
  if(lh.logo_base64&&/^image\/(png|jpeg)$/.test(lh.logo_type)){const img=doc.createElement('img');img.setAttribute('alt','Logo');img.setAttribute('src',`data:${lh.logo_type};base64,${lh.logo_base64}`);head.append(img);}
  const lines=doc.createElement('div');lines.className='lh-lines';
  for(const line of (lh.header_lines&&lh.header_lines.length?lh.header_lines:profileLines(profile))){const d=doc.createElement('div');d.textContent=line;lines.append(d);}
  head.append(lines);doc.body.insertBefore(head,first);
  const footer=lh.footer||[profile.address,profile.phone,profile.email].filter(Boolean).join(' · ');
  if(footer){const f=doc.createElement('div');f.className='lh-foot';f.textContent=footer;doc.body.append(f);}
}

/** Settings card: logo, header lines, footer and color. @param {import('./evidence.js').EvidenceClient} client */
export function letterheadCard(client){
  const card=box('section','card');
  card.append(box('h2','card-title','Meu papel timbrado'),
    box('p','muted','Logo e cabeçalho usados no receituário, no relatório, na solicitação e no termo. Na hora de imprimir você escolhe: com logo e cabeçalho, ou sem cabeçalho para imprimir no papel timbrado.'));
  const file=document.createElement('input');file.type='file';file.accept='image/png,image/jpeg';
  const preview=box('div','');const lines=textarea('Uma linha por item. Ex.: Dr. Juliano Morais\nOrtopedia e Traumatologia · CRM-SP 000000 · RQE 0000');lines.rows=4;
  const footer=input('Endereço · telefone · e-mail do consultório');const color=document.createElement('input');color.type='color';color.value='#0f3d5e';
  const save=button('Salvar papel timbrado'),removeLogo=button('Remover logo','ghost');const status=box('div','status-area');const a=box('div','actions');a.append(save,removeLogo);
  card.append(field('Logo (PNG ou JPG, até 400 KB)',file),preview,field('Linhas do cabeçalho',lines,'em branco: usa nome, especialidade, CRM e RQE do Meu perfil'),field('Rodapé',footer),field('Cor',color),a,status);
  /** @type {Letterhead} */ let lh={logo_base64:'',logo_type:'',header_lines:[],footer:'',color:'#0f3d5e'};
  const show=()=>{preview.replaceChildren();if(lh.logo_base64){const img=document.createElement('img');img.alt='Logo';img.src=`data:${lh.logo_type};base64,${lh.logo_base64}`;img.style.maxHeight='72px';preview.append(img);}};
  client.letterheadGet().then((/** @type {Letterhead} */ r)=>{lh=r;lines.value=r.header_lines.join('\n');footer.value=r.footer;color.value=r.color||'#0f3d5e';show();}).catch(()=>{say(status,'Papel timbrado indisponível neste servidor.','info');});
  file.onchange=async()=>{const f=file.files?.[0];if(!f)return;
    if(f.size>400000){say(status,'Logo acima de 400 KB. Reduza a imagem.');file.value='';return;}
    const bytes=new Uint8Array(await f.arrayBuffer());let bin='';for(let i=0;i<bytes.length;i+=0x8000)bin+=String.fromCharCode(...bytes.subarray(i,i+0x8000));
    lh={...lh,logo_base64:btoa(bin),logo_type:f.type==='image/png'?'image/png':'image/jpeg'};file.value='';show();say(status,'Logo carregado. Clique em Salvar.','info');};
  removeLogo.onclick=()=>{lh={...lh,logo_base64:'',logo_type:''};show();};
  save.onclick=()=>busy(save,async()=>{try{lh=await client.letterheadSave({...lh,header_lines:lines.value.split('\n'),footer:footer.value,color:color.value});show();say(status,'Papel timbrado salvo.','ok');}
    catch(e){say(status,e instanceof Error?e.message:'Falha ao salvar.');}});
  return card;
}

/** Prescription pad: filled and printed in the browser only.
 * @param {import('./evidence.js').EvidenceClient} client @param {{name:string}} patient @param {(t:HTMLTextAreaElement)=>HTMLElement} dictation @param {(n:string,t:string,m:string)=>void} download */
export function prescriptionPage(client,patient,dictation,download){
  const root=box('div','page-grid');const card=box('section','card');
  card.append(box('h2','card-title','Receituário'),box('p','muted','Preenchido e impresso aqui no seu computador; nada vai para a IA nem é gravado.'));
  const name=input('Nome do paciente',patient.name);name.oninput=()=>{patient.name=name.value;};
  const date=input('',new Date().toLocaleDateString('pt-BR'));
  const kind=select([['','Receita simples'],['Uso oral','Uso oral'],['Uso tópico','Uso tópico'],['Uso injetável','Uso injetável']]);
  const body=textarea('1) Medicamento, dose — posologia — duração\n2) ...\n\nOrientações: ...');body.rows=12;
  const grid=box('div','form-grid');grid.append(field('Paciente',name),field('Data',date),field('Tipo',kind),field('Modelo de impressão',printModeSelect()));
  const open=button('Abrir receituário'),save=button('Baixar (.html)','ghost');const a=box('div','actions');a.append(open,save);const status=box('div','status-area');
  card.append(grid,field('Prescrição',body),dictation(body),a,status);root.append(card);
  const build=async()=>{const {letterhead,profile}=await practice(client);
    const doc=document.implementation.createHTMLDocument('Receituário');const meta=doc.createElement('meta');meta.setAttribute('charset','utf-8');doc.head.prepend(meta);
    const style=doc.createElement('style');style.textContent='body{font-family:Georgia,serif;max-width:720px;margin:28px auto;padding:0 16px;color:#111;line-height:1.6;font-size:15px}h1{text-align:center;font-size:17px;letter-spacing:.08em}.rx{white-space:pre-wrap;margin:18px 0 0}.sign{margin-top:64px;text-align:center}';
    doc.head.append(style);
    /** @param {string} tag @param {string} text */ const add=(tag,text)=>{const e=doc.createElement(tag);e.textContent=text;doc.body.append(e);return e;};
    add('h1','RECEITUÁRIO');add('p',`Paciente: ${name.value}`);if(kind.value)add('p',kind.value).style.fontWeight='bold';
    add('div',body.value).className='rx';
    add('p',`${profile.city?profile.city+', ':''}${date.value}`).style.marginTop='28px';
    const sign=add('div','');sign.className='sign';sign.append(doc.createTextNode('_______________________________________'),doc.createElement('br'),
      doc.createTextNode(profile.name||'Médico'),doc.createElement('br'),doc.createTextNode([profile.crm?`CRM-${profile.uf||''} ${profile.crm}`:'CRM',profile.rqe?`RQE ${profile.rqe}`:''].filter(Boolean).join(' · ')));
    applyLetterhead(doc,letterhead,profile);
    return '<!doctype html>\n'+doc.documentElement.outerHTML;};
  open.onclick=()=>busy(open,async()=>{if(!body.value.trim()){say(status,'Escreva a prescrição.');return;}const html=await build();
    const url=URL.createObjectURL(new Blob([html],{type:'text/html'}));if(!window.open(url,'_blank'))download('receituario.html',html,'text/html');setTimeout(()=>URL.revokeObjectURL(url),60000);});
  save.onclick=()=>busy(save,async()=>download('receituario.html',await build(),'text/html'));
  return root;
}
