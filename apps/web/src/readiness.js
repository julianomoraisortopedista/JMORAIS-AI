/** "Pronto para o convênio": what an insurer's auditor looks for before authorizing, checked on this request. */

/** @typedef {{ok:boolean,label:string,fix:string,blocking:boolean}} ReadinessItem */

/**
 * @param {{facts:{category:string}[],icd10:string[],gaps:string[],science:any,template:any,schedule:{hospital?:string,date?:string},checks:{level:string}[]}} r
 * @returns {ReadinessItem[]}
 */
export function readiness(r){
  const has=(/** @type {string} */ c)=>r.facts.some(f=>f.category===c);
  const refs=(r.science&&r.science.references)||[];
  const favor=refs.filter((/** @type {any} */ x)=>x.direction==='SUPPORTING');
  const t=r.template;
  const suppliers=t?(t.suppliers||[]).filter((/** @type {any} */ s)=>String(s.label||'').trim()).length:0;
  /** @type {ReadinessItem[]} */ const items=[
    {ok:has('TRATAMENTO_CONSERVADOR'),blocking:true,label:'Tratamento conservador documentado (tipo e tempo)',fix:'Anexe ou dite fisioterapia, medicação, infiltrações e por quanto tempo. É o motivo mais comum de negativa.'},
    {ok:has('ACHADO_IMAGEM'),blocking:true,label:'Exame de imagem com laudo',fix:'Anexe o laudo (foto ou PDF) da radiografia, ressonância ou tomografia.'},
    {ok:has('EXAME_FISICO'),blocking:false,label:'Exame físico descrito',fix:'Descreva amplitude de movimento, deformidade, estabilidade e testes.'},
    {ok:has('ESCALA_FUNCIONAL'),blocking:false,label:'Escala de dor ou função (EVA, KOOS, WOMAC…)',fix:'Registre ao menos a EVA; escalas tornam a indicação objetiva.'},
    {ok:r.icd10.length>0,blocking:true,label:'CID-10 informado',fix:'Confirme o CID em "Pedido médico".'},
    {ok:favor.length>0,blocking:true,label:'Fundamentação científica a favor, verificada',fix:'Em Modelos de cirurgia, monte ou importe os artigos desta cirurgia.'},
    {ok:refs.some((/** @type {any} */ x)=>x.high_level),blocking:false,label:'Ao menos uma diretriz, meta-análise ou ensaio randomizado',fix:'Inclua estudos de alto nível na biblioteca da cirurgia.'},
    {ok:!r.gaps.length,blocking:false,label:'Relatório sem lacunas',fix:'Complete o que o relatório apontou como faltando.'},
    {ok:!r.checks.some(c=>c.level==='BLOQUEIO'),blocking:true,label:'Codificação conforme SBOT',fix:'Corrija os itens marcados na checagem anti-negativa.'},
  ];
  if(t){
    items.push({ok:Boolean(t.codes_confirmed),blocking:true,label:'Códigos TUSS confirmados',fix:'Confirme os códigos no modelo de cirurgia.'});
    if((t.opme||[]).length)items.push({ok:suppliers>=3,blocking:true,label:'OPME com 3 empresas de fabricantes diferentes',fix:'Cadastre 3 empresas no modelo (CFM 1.956/2010).'});
  }
  items.push({ok:Boolean(r.schedule.hospital&&r.schedule.date),blocking:false,label:'Hospital e data da cirurgia',fix:'Diga o hospital e a data no pedido.'});
  return items;
}
