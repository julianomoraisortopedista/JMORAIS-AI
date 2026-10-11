/** OPME request on the physician's prescription pad: patient, material, three brands/suppliers with ANVISA, justification. */
import {applyLetterhead,practice} from './letterhead.js';

const LEGAL='Características do material definidas pelo médico assistente (RN ANS nº 424/2017, art. 7º, I; Resolução CFM nº 2.318/2022, art. 2º). '+
  'Indicadas três opções de fornecedores, regularizadas na Anvisa (RN nº 424/2017, art. 7º, II; Resolução CFM nº 2.318/2022, art. 8º), sem exigência de marca exclusiva (Resolução CFM nº 2.318/2022, art. 4º).';

/** What the pad says, as plain sections, so it can be checked without a browser.
 * @param {any} t surgery template @returns {{title:string,lines:string[],suppliers:string[][],problems:string[]}} */
export function opmeRxContent(t){
  const suppliers=(t.suppliers||[]).filter((/** @type {any} */ s)=>String(s.label||'').trim());
  /** @type {string[]} */ const problems=[];
  if(suppliers.length<3)problems.push(`O modelo tem ${suppliers.length} empresa(s); são necessárias 3.`);
  if(suppliers.some((/** @type {any} */ s)=>!/^\d{11}$/.test(String(s.anvisa||''))))problems.push('Falta o registro ANVISA (11 dígitos) de alguma empresa.');
  if(!(t.opme||[]).length)problems.push('O modelo não tem itens de OPME.');
  const lines=[`Procedimento: ${t.name}`];
  if((t.tuss_codes||[]).length)lines.push('Códigos TUSS: '+t.tuss_codes.map((/** @type {string} */ c)=>`${c} ${t.tuss_terms&&t.tuss_terms[c]||''}`.trim()).join('; '));
  for(const i of t.opme||[])lines.push(`OPME: ${String(i.quantity).padStart(2,'0')} (${i.quantity===1?'um':i.quantity}) ${i.description}`);
  for(const s of t.material_specs||[])lines.push('Especificação: '+s);
  if((t.imaging_guidance||[]).length)lines.push('Guia de imagem: '+t.imaging_guidance.join(', '));
  if(t.material_justification)lines.push('Justificativa: '+t.material_justification);
  if((t.equivalent_brands||[]).length)lines.push('Marcas tecnicamente equivalentes: '+t.equivalent_brands.join(', '));
  return {title:'RECEITUÁRIO — SOLICITAÇÃO DE OPME',lines,problems,
    suppliers:suppliers.map((/** @type {any} */ s)=>[s.label,s.product||'',s.anvisa||'',s.contact||''])};
}

/** @param {import('./evidence.js').EvidenceClient} client @param {any} t @param {string} patientName @param {string} date @returns {Promise<string>} */
export async function opmePrescription(client,t,patientName,date){
  const c=opmeRxContent(t);
  if(c.problems.length)throw new Error(c.problems.join(' ')+' Complete em Modelos de cirurgia.');
  const {letterhead,profile}=await practice(client);
  const doc=document.implementation.createHTMLDocument('Receituário de OPME');const meta=doc.createElement('meta');meta.setAttribute('charset','utf-8');doc.head.prepend(meta);
  const style=doc.createElement('style');style.textContent='body{font-family:Georgia,serif;max-width:740px;margin:28px auto;padding:0 16px;color:#111;line-height:1.5;font-size:14px}h1{text-align:center;font-size:16px;letter-spacing:.06em}table{border-collapse:collapse;width:100%;margin:6px 0}td,th{border-bottom:1px solid #ccc;padding:4px 6px;text-align:left;vertical-align:top}.small{font-size:12px;color:#333}.sign{margin-top:56px;text-align:center}';
  doc.head.append(style);
  /** @param {string} tag @param {string} text @param {HTMLElement} [parent] */ const add=(tag,text,parent)=>{const e=doc.createElement(tag);e.textContent=text;(parent||doc.body).append(e);return e;};
  add('h1',c.title);
  add('p',`Paciente: ${patientName}`).style.fontWeight='bold';
  for(const line of c.lines)add('p',line);
  add('p','Fornecedores e marcas (três opções):').style.fontWeight='bold';
  const tb=doc.createElement('table');const hr=doc.createElement('tr');for(const h of ['Empresa','Produto / marca','Registro ANVISA','Contato'])add('th',h,hr);tb.append(hr);
  for(const r of c.suppliers){const tr=doc.createElement('tr');for(const v of r)add('td',v,tr);tb.append(tr);}doc.body.append(tb);
  add('p',LEGAL).className='small';
  add('p',`${profile.city?profile.city+', ':''}${date}`).style.marginTop='24px';
  const sign=add('div','');sign.className='sign';sign.append(doc.createTextNode('_______________________________________'),doc.createElement('br'),
    doc.createTextNode(profile.name?`Dr(a). ${profile.name}`:'Médico assistente'),doc.createElement('br'),
    doc.createTextNode([profile.crm?`CRM-${profile.uf||''} ${profile.crm}`:'CRM',profile.rqe?`RQE ${profile.rqe}`:''].filter(Boolean).join(' · ')));
  applyLetterhead(doc,letterhead,profile);
  return '<!doctype html>\n'+doc.documentElement.outerHTML;
}
