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
    {ok:has('EVOLUCAO'),blocking:false,label:'Data do diagnóstico e tempo de evolução',fix:'Informe desde quando há dor e há quanto tempo dura o tratamento (ex.: diagnóstico em 25/01/2025, 20 meses de tratamento). Os pedidos aprovados traziam isso explícito.'},
    {ok:has('INDICACAO'),blocking:false,label:'Por que este procedimento agora (e não cirurgia ou só conservador)',fix:'Diga por que não há indicação cirúrgica no momento e por que o conservador falhou. Responde ao argumento "não trata a causa primária".'},
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
    if((t.opme||[]).length){
      items.push({ok:suppliers>=3,blocking:true,label:'OPME com 3 empresas de fabricantes diferentes',fix:'Cadastre 3 empresas no modelo (CFM 2.318/2022).'});
      const named=(t.suppliers||[]).filter((/** @type {any} */ s)=>String(s.label||'').trim());
      items.push({ok:named.length>0&&named.every((/** @type {any} */ s)=>/^\d{11}$/.test(String(s.anvisa||''))),blocking:true,label:'Registro ANVISA de cada empresa',fix:'Informe o produto e o registro ANVISA (11 dígitos) de cada uma das 3 empresas no modelo.'});
      items.push({ok:(t.material_specs||[]).length>0,blocking:false,label:'Especificação técnica do material',fix:'Descreva as características (ecogênica, isolada para estímulo, tela radiopaca, calibre, comprimento) para o hospital não trocar por material inferior.'});
    }
    const codes=t.tuss_codes||[];
    if(codes.some((/** @type {string} */ c)=>['31403239','31403204','31403212'].includes(c)))items.push({ok:false,blocking:false,label:'Código de microneurólise',fix:'Negado em 6 de 6 pedidos: as operadoras entendem como cirurgia aberta com microscópio. Reavalie o código para técnica percutânea.'});
    if(codes.includes('31403026')&&codes.includes('31602118'))items.push({ok:false,blocking:true,label:'Dois códigos de bloqueio de nervo periférico',fix:'31403026 e 31602118 no mesmo pedido são lidos como cobrança em duplicidade. Use um só.'});
  }
  items.push({ok:Boolean(r.schedule.hospital&&r.schedule.date),blocking:false,label:'Hospital e data da cirurgia',fix:'Diga o hospital e a data no pedido.'});
  return items;
}
