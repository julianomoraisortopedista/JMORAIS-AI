/** Scientific library of a surgery template: articles the physician accepted once, re-verified on every request. */
import {DIRECTIONS,box,button,busy,field,input,say,session,textarea} from './evidence.js';

const MAX_PROPOSALS=8;

/** @param {import('./evidence.js').EvidenceClient} client @param {{template_id:string,name:string}} t */
export function libraryPanel(client,t){
  const wrap=box('div','library');
  const summary=box('div','');const work=box('div','');const status=box('div','status-area');
  const build=button('Montar artigos com o Claude','ghost'),more=button('Importar PMIDs/DOIs','quiet');
  const actions=box('div','actions');actions.append(build,more);
  wrap.append(box('h3','section-title','Artigos científicos desta cirurgia'),summary,actions,status,work);
  /** @type {string} */ let claim='';
  const show=(/** @type {any} */ lib)=>{
    claim=lib.claim||claim;summary.replaceChildren();
    if(!lib.articles.length){summary.append(box('p','muted','Nenhum artigo aprovado ainda. Monte uma vez; os pedidos desta cirurgia passam a usar estes artigos, conferidos de novo no PubMed e no Crossref a cada pedido.'));return;}
    summary.append(box('p','muted',`${lib.articles.length} artigo(s) aprovados por você para: "${lib.claim}"`));
    for(const a of lib.articles){const row=box('div','row');const m=box('div','row-main');
      m.append(box('strong','',`PMID ${a.pmid} · ${DIRECTIONS[/** @type {keyof typeof DIRECTIONS} */(a.direction)]||a.direction}`),box('span','muted',`"${a.quote}"`));
      const rm=button('Remover','quiet');rm.onclick=()=>busy(rm,async()=>{show(await client.libraryRemove(t.template_id,a.pmid));});
      row.append(m,rm);summary.append(row);}
  };
  client.libraryGet(t.template_id).then(show).catch(()=>{summary.replaceChildren(box('p','muted','Biblioteca indisponível.'));});

  /** Proposals for each candidate, one at a time, then the physician decides each one. @param {{pmid:string,title:string}[]} candidates */
  const review=async(candidates)=>{
    const reviewer=await signer(client);
    const list=box('div','rows');const save=button('Salvar na biblioteca desta cirurgia');save.disabled=true;
    work.replaceChildren(box('p','muted',`Afirmação: "${claim}"`),list,save);
    let accepted=0;
    for(const [n,c] of candidates.slice(0,MAX_PROPOSALS).entries()){
      say(status,`O Claude está lendo o resumo ${n+1} de ${Math.min(candidates.length,MAX_PROPOSALS)}…`,'info');
      const row=box('div','card');row.append(box('strong','',c.title||'PMID '+c.pmid),box('span','muted',' PMID '+c.pmid));list.append(row);
      /** @type {any} */ let p;
      try{p=await client.propose(claim,c.pmid);}catch(e){row.append(box('p','muted',e instanceof Error?e.message:'Falha.'));continue;}
      if(!p.direction||!p.quote){row.append(box('p','muted','Sem trecho literal que trate da afirmação; não entra.'));continue;}
      row.append(box('p','',`Sugestão: ${DIRECTIONS[/** @type {keyof typeof DIRECTIONS} */(p.direction)]}`),box('blockquote','abstract',p.quote),box('p','muted',p.rationale||''));
      const ok=button('Aceitar','ghost'),no=button('Rejeitar','quiet');const a=box('div','actions');a.append(ok,no);row.append(a);
      /** @param {'ACCEPT'|'REJECT'} decision */
      const decide=(decision)=>busy(decision==='ACCEPT'?ok:no,async()=>{
        try{await client.decide({proposal_id:p.proposal_id,decision,reviewer:reviewer.value,note:''});
          a.replaceWith(box('p',decision==='ACCEPT'?'ok':'muted',decision==='ACCEPT'?'✓ Aceito por você':'Rejeitado'));
          if(decision==='ACCEPT'){accepted++;save.disabled=false;}}
        catch(e){say(status,e instanceof Error?e.message:'Falha.');}});
      ok.onclick=()=>decide('ACCEPT');no.onclick=()=>decide('REJECT');
    }
    say(status,'Leia cada trecho e aceite só o que sustenta a indicação. Depois salve.','info');
    save.onclick=()=>busy(save,async()=>{
      try{show(await client.librarySave(t.template_id,claim));work.replaceChildren();say(status,`Biblioteca salva (${accepted} novo(s)). Os próximos pedidos já usam estes artigos.`,'ok');}
      catch(e){say(status,e instanceof Error?e.message:'Falha ao salvar.');}});
  };

  build.onclick=()=>busy(build,async()=>{
    if(!session.model){say(status,'Claude não configurado. Use "Importar PMIDs/DOIs" ou a página Evidências.');return;}
    try{
      say(status,'Montando a pergunta clínica e buscando no PubMed…','info');
      const q=await client.question(`Indicação, eficácia e segurança de ${t.name} em comparação ao tratamento conservador ou alternativas`,t.template_id);
      claim=claim||q.claim;
      const r=await client.search({population:q.population.join('; '),intervention:q.intervention.join('; '),comparison:q.comparison.join('; '),
        outcome:q.outcome.join('; '),designs:q.designs,since_years:15});
      if(!r.candidates.length){say(status,'Nenhum artigo encontrado. Tente importar PMIDs/DOIs.');return;}
      await review(r.candidates);
    }catch(e){say(status,e instanceof Error?e.message:'Falha.');}
  });
  more.onclick=()=>{
    const ids=textarea('PMIDs ou DOIs (ex.: do OpenEvidence ou OrthoEvidence), separados por espaço ou vírgula');ids.rows=3;
    const own=input('Afirmação clínica (ex.: A artroplastia total do joelho melhora dor e função na osteoartrose avançada)',claim);
    const go=button('Conferir e classificar','ghost');work.replaceChildren(field('Afirmação',own),field('Artigos',ids),go);
    go.onclick=()=>busy(go,async()=>{
      claim=own.value.trim();if(claim.length<10){say(status,'Escreva a afirmação clínica.');return;}
      try{const r=await client.importIds(ids.value);
        if(r.invalid.length)say(status,'Ignorados (formato inválido): '+r.invalid.join(', '));
        if(!r.candidates.length){say(status,'Nenhum artigo verificado no PubMed.');return;}
        if(!session.model){say(status,'Artigos conferidos. Classifique-os na página Evidências e salve aqui.','info');return;}
        await review(r.candidates);}
      catch(e){say(status,e instanceof Error?e.message:'Falha.');}});
  };
  return wrap;
}

/** The physician's CRM from the profile; asked once if missing. @param {import('./evidence.js').EvidenceClient} client */
async function signer(client){
  const crm=input('CRM-UF 000000',session.reviewer);
  if(!crm.value){try{const p=await client.profileGet();if(p.crm)crm.value=`CRM-${p.uf||''} ${p.crm}`.trim();}catch{/* typed below */}}
  if(!crm.value.trim()){const typed=window.prompt('Seu CRM (assina as decisões sobre os artigos):','')||'';crm.value=typed.trim();}
  session.reviewer=crm.value;return crm;
}
