import {viewers} from './client.js';
/** @typedef {import('./client.js').Viewer} Viewer */
export const labels={summary:'Resumo clínico',timeline:'Linha do tempo',evidence:'Evidências',explainability:'Explicabilidade',medical_document:'Documentos médicos',human_review:'Revisão humana',audit_defense:'Defesa de auditoria'};
/** Only fields present in the approved S004 projections are presented. */
const fields={summary:['pseudonymous_patient_id','state_version','as_of','review_status','quality_flags','provenance_references','integrity_status'],
 evidence:['evidence_level','methodological_quality','recommendation_strength','guideline_governance_status','applicability','support_directions','conflict_status','limitations','provenance_references','ledger_references','integrity_status'],
 explainability:['review_status','readiness','missing_data_references','conflicting_data_references','stale_data_references','review_required','integrity_status'],
 medical_document:['status','review_status','validation_valid','provenance_references','created_at','integrity_status'],
 human_review:['decision','resulting_state','reviewer_role','occurred_at','integrity_status','audit_status'],
 audit_defense:['state','status','review_status','previous_package_id','provenance_references','integrity_status','replay_status','completeness_verified']};
/** @type {Record<string,string>} */
const titles={pseudonymous_patient_id:'Paciente pseudonimizado',state_version:'Versão exata',as_of:'Registrado em',review_status:'Revisão',quality_flags:'Alertas de qualidade',provenance_references:'Proveniência',integrity_status:'Integridade',evidence_level:'Nível de evidência',methodological_quality:'Qualidade metodológica',recommendation_strength:'Força da recomendação',guideline_governance_status:'Governança',applicability:'Aplicabilidade',support_directions:'Direções de suporte',conflict_status:'Conflitos',limitations:'Limitações',ledger_references:'Registros de evidência',readiness:'Prontidão',missing_data_references:'Dados ausentes',conflicting_data_references:'Dados conflitantes',stale_data_references:'Dados desatualizados',review_required:'Revisão necessária',status:'Status',validation_valid:'Validação',created_at:'Criado em',decision:'Decisão',resulting_state:'Estado resultante',reviewer_role:'Papel do revisor',occurred_at:'Data da revisão',audit_status:'Verificação da cadeia',state:'Vínculo Stage 11',previous_package_id:'Pacote predecessor',replay_status:'Replay',completeness_verified:'Completude'};
/** @param {string} tag @param {string} text @returns {HTMLElement} */
export function el(tag,text=''){const n=document.createElement(tag);n.textContent=text;return n;}
/** @param {unknown} value @returns {string} */
function text(value){if(value===null || value===undefined)return 'Não informado';if(typeof value==='boolean')return value?'Sim':'Não';if(typeof value==='string'||typeof value==='number')return String(value);return 'Formato indisponível';}
/** @param {Viewer} viewer @param {Record<string,unknown>} data @returns {HTMLElement} */
export function renderView(viewer,data){
 const root=el('section');root.setAttribute('aria-label',labels[viewer]);
 if(viewer==='timeline'){
   const entries=Array.isArray(data.entries)?data.entries:[];
   if(!entries.length){root.append(el('p','Nenhum evento disponível neste contexto.'));return root;}
   const list=el('ol');list.className='timeline';
   for(const entry of entries){const item=el('li');item.append(el('h3',text(entry.as_of)),renderView('summary',entry));list.append(item);}root.append(list);return root;
 }
 const dl=el('dl');
 for(const key of fields[viewer]){if(!(key in data))continue;dl.append(el('dt',titles[key]));const dd=el('dd');
   const value=data[key]; if(Array.isArray(value)){const list=el('ul');for(const item of value)list.append(el('li',text(item)));dd.append(value.length?list:el('span','Nenhum item registrado'));}
   else dd.textContent=text(data[key]);dl.append(dd);}
 root.append(dl);
 if(!dl.children.length)root.append(el('p','Nenhum dado disponível neste contexto.'));
 if(viewer==='audit_defense' && data.stage11_document && typeof data.stage11_document==='object'){
   root.append(el('h3','Documento Stage 11 vinculado'),renderView('medical_document',/** @type {Record<string,unknown>} */(data.stage11_document)));}
 return root;
}
export function navigation(){const nav=el('nav');nav.setAttribute('aria-label','Viewers clínicos');for(const name of viewers){const b=el('button',labels[name]);b.dataset.viewer=name;nav.append(b);}return nav;}
