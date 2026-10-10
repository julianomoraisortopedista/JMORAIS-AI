/** Surgical templates: official TUSS procedures, OPME kit, three suppliers, hospital packages. */
import {el} from './view.js';
import {box,button,busy,field,input,pill,say,select,session,textarea} from './evidence.js';
import {letterheadCard} from './letterhead.js';
import {libraryPanel} from './library.js';

/** @typedef {{description:string,quantity:number}} Item */
/** @typedef {{item_index:number,tuss_code:string,term?:string,manufacturer?:string,anvisa?:string}} Material */
/** @typedef {{label:string,materials:Material[]}} Supplier */
/** @typedef {{network:string,package_code:string,description:string,includes_opme:boolean|null,notes:string}} Package */
/** @typedef {{template_id:string,name:string,region:string,tuss_codes:string[],tuss_terms:Record<string,string>,codes_confirmed:boolean,regime:string,opme:Item[],suppliers:Supplier[],packages:Package[],notes:string,warnings?:string[],sbot_entry?:string,icu_days?:number|null,ward_days?:number|null,anesthesia?:string,consent_definition?:string,consent_risks?:string[]}} Template */

/** @param {import('./evidence.js').EvidenceClient} client */
export function catalogPage(client){
  const root=box('div','page-grid');
  const head=box('section','card');
  head.append(box('h2','card-title','Modelos de cirurgia'),
    box('p','muted','Cada modelo reúne o procedimento com códigos da tabela TUSS oficial da ANS, o kit de OPME com quantidades, três fornecedores de fabricantes diferentes (CFM 1.956/2010, art. 5º) e os pacotes das redes. Códigos e materiais vêm da tabela oficial; nada é inventado.'));
  const add=button('Novo modelo');const actions=box('div','actions');actions.append(add);const status=box('div','status-area');head.append(actions,status);
  const list=box('div','page-grid');root.append(profileCard(client),letterheadCard(client),sbotCard(client,()=>reload()),head,list,styleCard(client),consentCard(client));
  const reload=async()=>{
    try{const r=await client.catalog();list.replaceChildren();
      if(r.tuss_version)status.replaceChildren(box('span','muted','Tabela TUSS oficial: versão '+r.tuss_version));
      for(const t of r.templates)list.append(templateCard(client,t,reload,list));
    }catch(e){say(status,e instanceof Error?e.message:'Falha.');}
  };
  add.onclick=()=>list.prepend(editor(client,blank(),reload));
  reload();return root;
}

/** @returns {Template} */
function blank(){return {template_id:'',name:'',region:'',tuss_codes:[],tuss_terms:{},codes_confirmed:false,regime:'Internação',opme:[],suppliers:[],packages:[],notes:''};}

/** @param {import('./evidence.js').EvidenceClient} client @param {Template} t @param {()=>Promise<void>} reload @param {HTMLElement} list */
function templateCard(client,t,reload,list){
  const card=box('section','card');
  const head=box('div','article-head');head.append(box('h3','article-title',t.name),box('span','muted',[t.region,t.regime].filter(Boolean).join(' · ')));
  card.append(head);
  for(const code of t.tuss_codes)card.append(box('p','', `TUSS ${code} — ${t.tuss_terms[code]||''}`));
  if(!t.codes_confirmed)card.append(pill('Códigos a confirmar','PENDENTE'));
  if(t.opme.length)card.append(box('p','muted','OPME: '+t.opme.map(i=>`${i.quantity}× ${i.description}`).join(', ')));
  for(const s of t.suppliers){
    const line=box('p','muted',`${s.label}: `+(s.materials.length?s.materials.map(m=>`${t.opme[m.item_index]?.description||''} → ${m.term} (Anvisa ${m.anvisa})`).join('; '):'materiais ainda não escolhidos'));
    card.append(line);
  }
  for(const p of t.packages)card.append(box('p','muted',`Pacote ${p.network}${p.package_code?' '+p.package_code:''}: ${p.description}`));
  for(const w of t.warnings||[])card.append(box('div','alert alert-warn',w));
  if(t.icu_days!=null||t.ward_days!=null)card.append(box('p','muted',`Internação prevista (SBOT): UTI ${t.icu_days??'—'} dia(s), quarto ${t.ward_days??'—'} dia(s)`));
  if(t.consent_risks&&t.consent_risks.length)card.append(box('p','muted',`Termo de consentimento: ${t.consent_risks.length} complicação(ões) descritas`));
  else card.append(box('p','muted','Termo de consentimento: descreva as complicações em Editar.'));
  if(t.notes)card.append(box('p','muted',t.notes));
  card.append(libraryPanel(client,t));
  const edit=button('Editar','ghost'),del=button('Excluir','quiet');const a=box('div','actions');a.append(edit,del);card.append(a);
  edit.onclick=()=>card.replaceWith(editor(client,structuredClone(t),reload));
  del.onclick=()=>busy(del,async()=>{await client.catalogDelete(t.template_id);await reload();});
  void list;return card;
}

/** @param {import('./evidence.js').EvidenceClient} client @param {Template} t @param {()=>Promise<void>} reload */
function editor(client,t,reload){
  const card=box('section','card');card.append(box('h2','card-title',t.template_id?'Editar modelo':'Novo modelo'));
  const name=input('Ex.: Artroplastia total do joelho com implantes',t.name);const region=input('Joelho',t.region);
  const regime=select([['Internação','Internação'],['Ambulatorial','Ambulatorial'],['Hospital-dia','Hospital-dia']]);regime.value=t.regime||'Internação';
  const grid=box('div','form-grid');grid.append(field('Nome',name),field('Região',region),field('Regime',regime));card.append(grid);

  // TUSS procedures from the official table.
  card.append(box('h3','section-title','Procedimentos (TUSS 22 oficial)'));
  const codes=box('div','rows');const renderCodes=()=>{codes.replaceChildren();for(const c of t.tuss_codes){const row=box('div','row');const rm=button('Remover','quiet');
    rm.onclick=()=>{t.tuss_codes=t.tuss_codes.filter(x=>x!==c);renderCodes();};const m=box('div','row-main');m.append(box('strong','',c),box('span','muted',t.tuss_terms[c]||''));row.append(m,rm);codes.append(row);}};
  renderCodes();
  const q=input('Buscar procedimento: ex. artroplastia joelho');const results=box('div','rows');const find=button('Buscar','ghost');
  const searchRow=box('div','actions');searchRow.append(find);
  find.onclick=()=>busy(find,async()=>{try{const r=await client.tussProcedures(q.value);results.replaceChildren();
    for(const e of r.results){const row=box('div','row');const add=button('Adicionar','ghost');add.disabled=!e.active;
      add.onclick=()=>{if(!t.tuss_codes.includes(e.code)){t.tuss_codes.push(e.code);t.tuss_terms[e.code]=e.term;t.codes_confirmed=false;confirm.checked=false;renderCodes();}};
      const m=box('div','row-main');m.append(box('strong','',e.code+(e.active?'':' (encerrado)')),box('span','muted',e.term));row.append(m,add);results.append(row);}
    if(!r.results.length)results.append(box('p','muted','Nada encontrado na tabela oficial.'));}catch(err){say(results,err instanceof Error?err.message:'Falha.');}});
  const confirm=document.createElement('input');confirm.type='checkbox';confirm.checked=t.codes_confirmed;
  const confirmLabel=box('label','chip');confirmLabel.append(confirm,el('span','Confirmo que estes códigos TUSS correspondem ao procedimento'));
  card.append(codes,field('Buscar na TUSS',q),searchRow,results,confirmLabel);

  // OPME kit.
  card.append(box('h3','section-title','Kit de OPME (itens e quantidades)'));
  const kit=box('div','rows');
  const renderKit=()=>{kit.replaceChildren();t.opme.forEach((item,n)=>{const row=box('div','form-grid');const d=input('Item',item.description);const qy=input('Qtd',String(item.quantity));
    d.oninput=()=>{item.description=d.value;};qy.oninput=()=>{item.quantity=Math.max(1,Number(qy.value)||1);};
    const rm=button('Remover','quiet');rm.onclick=()=>{t.opme.splice(n,1);for(const s of t.suppliers)s.materials=s.materials.filter(m=>m.item_index!==n).map(m=>({...m,item_index:m.item_index>n?m.item_index-1:m.item_index}));renderKit();renderSuppliers();};
    row.append(d,qy,rm);kit.append(row);});};
  const addItem=button('+ Item','quiet');addItem.onclick=()=>{t.opme.push({description:'',quantity:1});renderKit();renderSuppliers();};
  renderKit();card.append(kit,addItem);

  // Suppliers: official TUSS 19 material per kit item.
  card.append(box('h3','section-title','Fornecedores (3 fabricantes diferentes)'),box('p','muted','Para cada fornecedor, escolha na tabela TUSS 19 o material de cada item. O fabricante e o registro Anvisa vêm da tabela oficial.'));
  const suppliers=box('div','page-grid');
  const renderSuppliers=()=>{suppliers.replaceChildren();t.suppliers.forEach((s,sn)=>suppliers.append(supplierBox(client,t,s,sn,renderSuppliers)));};
  const addSupplier=button('+ Fornecedor','quiet');addSupplier.onclick=()=>{t.suppliers.push({label:'',materials:[]});renderSuppliers();};
  renderSuppliers();card.append(suppliers,addSupplier);

  // Hospital network packages.
  card.append(box('h3','section-title','Pacotes de redes hospitalares'));
  const pkgs=box('div','rows');
  const renderPkgs=()=>{pkgs.replaceChildren();t.packages.forEach((p,n)=>{const row=box('div','form-grid');
    const net=input('Rede',p.network),code=input('Código do pacote',p.package_code),desc=input('Descrição',p.description),notes=input('Observações',p.notes);
    const inc=select([['','OPME no pacote?'],['true','Inclui OPME'],['false','Não inclui OPME']]);inc.value=p.includes_opme===null?'':String(p.includes_opme);
    net.oninput=()=>{p.network=net.value;};code.oninput=()=>{p.package_code=code.value;};desc.oninput=()=>{p.description=desc.value;};notes.oninput=()=>{p.notes=notes.value;};
    inc.onchange=()=>{p.includes_opme=inc.value===''?null:inc.value==='true';};
    const rm=button('Remover','quiet');rm.onclick=()=>{t.packages.splice(n,1);renderPkgs();};row.append(net,code,desc,inc,notes,rm);pkgs.append(row);});};
  const addPkg=button('+ Pacote','quiet');addPkg.onclick=()=>{t.packages.push({network:'',package_code:'',description:'',includes_opme:null,notes:''});renderPkgs();};
  renderPkgs();
  const notes=textarea('Observações do modelo');notes.value=t.notes;
  card.append(pkgs,addPkg,field('Observações',notes));

  // Consent form (TCLE) content for this procedure, written by the physician.
  card.append(box('h3','section-title','Termo de consentimento deste procedimento'),
    box('p','muted','Usado para preencher o seu modelo de termo. A definição vem da SBOT quando o modelo foi criado a partir dela; revise. As complicações são escritas por você, uma por linha.'));
  const anesthesia=input('Ex.: raquianestesia com sedação / anestesia geral',t.anesthesia||'');
  const definition=textarea('O que é o procedimento, em linguagem clara para o paciente');definition.rows=4;definition.value=t.consent_definition||'';
  const risks=textarea('Uma complicação por linha. Ex.: Infecção\nTrombose venosa profunda');risks.rows=6;risks.value=(t.consent_risks||[]).join('\n');
  card.append(field('Anestesia',anesthesia),field('Definição do procedimento',definition),field('Riscos e complicações',risks));

  const save=button('Salvar modelo'),cancel=button('Cancelar','quiet');const status=box('div','status-area');const a=box('div','actions');a.append(save,cancel);card.append(a,status);
  cancel.onclick=()=>reload();
  save.onclick=()=>busy(save,async()=>{
    t.name=name.value;t.region=region.value;t.regime=regime.value;t.notes=notes.value;t.codes_confirmed=confirm.checked;
    t.anesthesia=anesthesia.value;t.consent_definition=definition.value;t.consent_risks=risks.value.split('\n').map(x=>x.trim()).filter(Boolean).slice(0,40);
    t.suppliers=t.suppliers.filter(s=>s.label.trim());t.packages=t.packages.filter(p=>p.network.trim());t.opme=t.opme.filter(i=>i.description.trim());
    try{const {warnings,...body}=t;void warnings;await client.catalogSave(body);await reload();}
    catch(e){say(status,e instanceof Error?e.message:'Falha ao salvar.');}
  });
  return card;
}

/** @param {import('./evidence.js').EvidenceClient} client @param {Template} t @param {Supplier} s @param {number} sn @param {()=>void} rerender */
function supplierBox(client,t,s,sn,rerender){
  const wrap=box('div','card');const label=input('Fornecedor / fabricante (ex.: Zimmer Biomet)',s.label);label.oninput=()=>{s.label=label.value;};
  const rm=button('Remover fornecedor','quiet');rm.onclick=()=>{t.suppliers.splice(sn,1);rerender();};
  wrap.append(field(`Fornecedor ${sn+1}`,label));
  t.opme.forEach((item,n)=>{
    const current=s.materials.find(m=>m.item_index===n);
    const row=box('div','row');const m=box('div','row-main');m.append(box('strong','',item.description||`Item ${n+1}`),
      box('span','muted',current?`${current.tuss_code} — ${current.term||''} · ${current.manufacturer||''} · Anvisa ${current.anvisa||''}`:'nenhum material escolhido'));
    const pick=button('Escolher na TUSS 19','ghost');const term=input('Termo de busca',item.description);
    const any=document.createElement('input');any.type='checkbox';const anyLabel=box('label','chip');anyLabel.append(any,el('span','Qualquer fabricante (ex.: pulse lavage)'));
    row.append(m,pick);wrap.append(row,field('Buscar material',term,'use o nome do sistema/modelo para refinar (ex.: Attune, Persona, Vanguard)'),anyLabel);
    const results=box('div','rows');wrap.append(results);
    pick.onclick=()=>busy(pick,async()=>{
      try{const r=await client.tussMaterials(term.value||item.description||'protese',any.checked?'':s.label);results.replaceChildren();
        for(const e of r.results.filter((/** @type {any} */ x)=>x.active).slice(0,15)){const opt=box('div','row');const use=button('Usar','ghost');
          use.onclick=()=>{s.materials=s.materials.filter(x=>x.item_index!==n);s.materials.push({item_index:n,tuss_code:e.code,term:e.term,manufacturer:e.manufacturer,anvisa:e.anvisa});rerender();};
          const mm=box('div','row-main');mm.append(box('strong','',e.code+' — '+e.term),box('span','muted',`${e.manufacturer} · Anvisa ${e.anvisa} · ${e.technical_name}`));opt.append(mm,use);results.append(opt);}
        if(!results.children.length)results.append(box('p','muted','Nada encontrado. Ajuste o nome do item ou do fornecedor (como aparece na tabela oficial).'));
      }catch(err){say(results,err instanceof Error?err.message:'Falha.');}});
  });
  const a=box('div','actions');a.append(rm);wrap.append(a);return wrap;
}

/** Physician profile: fills headers, consent forms and signatures. @param {import('./evidence.js').EvidenceClient} client */
function profileCard(client){
  const card=box('section','card');
  card.append(box('h2','card-title','Meu perfil'),box('p','muted','Seus dados profissionais para cabeçalhos, termos de consentimento e assinaturas.'));
  /** @type {[string,string][]} */
  const fields=[['name','Nome completo'],['crm','CRM (número)'],['uf','UF do CRM'],['rqe','RQE'],['specialty','Especialidade'],['city','Cidade'],['phone','Telefone do consultório'],['email','E-mail do consultório'],['address','Endereço do consultório']];
  /** @type {Record<string,HTMLInputElement>} */ const inputs={};
  const grid=box('div','form-grid');for(const [k,l] of fields){const i=input(l);inputs[k]=i;grid.append(field(l,i));}
  const save=button('Salvar perfil');const status=box('div','status-area');const a=box('div','actions');a.append(save);card.append(grid,a,status);
  client.profileGet().then((/** @type {any} */ p)=>{for(const [k] of fields)inputs[k].value=p[k]||'';if(p.crm)session.reviewer=`CRM-${p.uf} ${p.crm}`;}).catch(()=>{});
  save.onclick=()=>busy(save,async()=>{
    /** @type {Record<string,string>} */
    const p={};
    try{for(const [k] of fields)p[k]=inputs[k].value.trim();p.uf=p.uf.toUpperCase().slice(0,2);
    await client.profileSave(p);if(p.crm)session.reviewer=`CRM-${p.uf} ${p.crm}`;say(status,'Perfil salvo.','ok');}catch(e){say(status,e instanceof Error?e.message:'Falha.');}});
  return card;
}

/** SBOT coding manual: search, inspect and create a template from an entry. @param {import('./evidence.js').EvidenceClient} client @param {()=>void} reload */
function sbotCard(client,reload){
  const card=box('section','card');
  card.append(box('h2','card-title','Base SBOT de codificação'),
    box('p','muted','Manual de Diretrizes de Codificação da SBOT: CID, indicação, exames, códigos com porte, OPME e internação de cada cirurgia. Crie um modelo a partir dele; os códigos são conferidos na TUSS oficial e você confirma.'));
  const q=input('Ex.: artroplastia total joelho, LCA, manguito');const find=button('Buscar','ghost');const a=box('div','actions');a.append(find);
  const results=box('div','rows');const detail=box('div','');card.append(field('Procedimento',q),a,results,detail);
  /** @param {string} id */
  const show=async(id)=>{try{const e=await client.sbotEntry(id);detail.replaceChildren(box('h3','section-title',`${e.entry_id} — ${e.name} (p. ${e.page})`));
      /** @param {string} k @param {string} v */ const line=(k,v)=>{if(v)detail.append(box('p','',`${k}: ${v}`));};
      line('CID',e.icd10.join(', '));line('Caráter',e.character);line('Indicação',e.indication);line('Contraindicação',e.contraindication);line('Exames da indicação',e.exams);
      line('Códigos',e.codes.map((/** @type {any} */ c)=>`${c.cbhpm} ${c.description} (${c.porte})${c.exclusive_group?' ['+c.exclusive_group+']':''}`).join('; '));
      line('OPME',e.opme.map((/** @type {any} */ o)=>`${o.quantity}× ${o.description}`).join(', '));
      if(e.icu_days!=null)line('Internação',`UTI ${e.icu_days} dia(s), quarto ${e.ward_days} dia(s)`);line('Comentários',e.comments);
      const create=button('Criar modelo de cirurgia a partir deste');const st=box('div','status-area');const b=box('div','actions');b.append(create);detail.append(b,st);
      create.onclick=()=>busy(create,async()=>{try{const t=await client.catalogFromSbot(e.entry_id);say(st,`Modelo "${t.name}" criado. Confira os códigos, escolha os materiais dos fornecedores e confirme.`,'ok');reload();}catch(err){say(st,err instanceof Error?err.message:'Falha.');}});
    }catch(err){say(detail,err instanceof Error?err.message:'Falha.');}};
  find.onclick=()=>busy(find,async()=>{try{const r=await client.sbotSearch(q.value);results.replaceChildren();detail.replaceChildren();
    for(const e of r.results){const row=box('div','row');const open=button('Ver','ghost');open.onclick=()=>show(e.entry_id);
      const m=box('div','row-main');m.append(box('strong','',`${e.entry_id} — ${e.name}`),box('span','muted',`${e.character} · ${e.codes.join(', ')}`));row.append(m,open);results.append(row);}
    if(!r.results.length)results.append(box('p','muted','Nada encontrado na base SBOT.'));}catch(err){say(results,err instanceof Error?err.message:'Falha.');}});
  return card;
}

/** The physician's consent-form model, filled with patient data only in the browser. @param {import('./evidence.js').EvidenceClient} client */
function consentCard(client){
  const card=box('section','card');
  card.append(box('h2','card-title','Meu termo de consentimento'),
    box('p','muted','Envie o seu modelo em branco (.docx, PDF com texto ou .txt), com os campos "(inserir ...)". No Pedido médico ele é preenchido no seu computador com os dados do paciente, do procedimento e as complicações do modelo de cirurgia.'));
  const file=document.createElement('input');file.type='file';file.accept='.docx,.pdf,.txt';
  const text=box('div','abstract','');const status=box('div','status-area');const remove=button('Excluir modelo de termo','ghost');const a=box('div','actions');a.append(remove);
  card.append(field('Arquivo do termo',file),status,text,a);
  /** @param {string|null} t */ const show=(t)=>{text.textContent=t?t.slice(0,1500)+(t.length>1500?'…':''):'Nenhum modelo de termo salvo.';};
  client.consentGet().then((/** @type {any} */ r)=>show(r.text)).catch(()=>show(null));
  file.onchange=async()=>{const f=file.files?.[0];if(!f)return;
    try{const bytes=new Uint8Array(await f.arrayBuffer());let bin='';for(let i=0;i<bytes.length;i+=0x8000)bin+=String.fromCharCode(...bytes.subarray(i,i+0x8000));
      const r=await client.consentUpload({name:f.name,content_base64:btoa(bin)});show(r.text);file.value='';say(status,'Modelo de termo salvo.','ok');}
    catch(e){file.value='';say(status,e instanceof Error?e.message:'Falha.');}};
  remove.onclick=()=>busy(remove,async()=>{try{await client.consentDelete();show(null);say(status,'Modelo de termo excluído.','info');}catch(e){say(status,e instanceof Error?e.message:'Falha.');}});
  return card;
}

/** The physician's own report model: de-identified on upload, reviewed, then used as format only. @param {import('./evidence.js').EvidenceClient} client */
function styleCard(client){
  const card=box('section','card');
  card.append(box('h2','card-title','Meu modelo de relatório'),
    box('p','muted','Envie um relatório seu (PDF com texto ou .txt). Nome, CPF, carteirinha e outros dados são removidos aqui, sem IA; confira o texto, apague o que ainda identificar alguém e salve. O Claude passa a seguir a ordem, os títulos e o seu estilo, mas nunca usa os dados clínicos do modelo.'));
  const file=document.createElement('input');file.type='file';file.accept='.pdf,.txt,application/pdf,text/plain';
  const text=textarea('O modelo sem identificação aparece aqui.');text.rows=12;
  const ok=document.createElement('input');ok.type='checkbox';const okLabel=box('label','chip');okLabel.append(ok,el('span','Conferi: o modelo não tem dados de paciente'));
  const save=button('Salvar modelo'),remove=button('Excluir modelo','ghost');const status=box('div','status-area');const a=box('div','actions');a.append(save,remove);
  card.append(field('Arquivo do modelo',file),field('Texto do modelo',text),okLabel,a,status);
  client.styleGet().then((/** @type {any} */ r)=>{if(r.text){text.value=r.text;say(status,'Modelo salvo: os próximos relatórios seguem este formato.','ok');}}).catch(()=>{say(status,'Modelo de relatório indisponível neste servidor.','info');});
  file.onchange=async()=>{const f=file.files?.[0];if(!f)return;
    if(f.size>700000){say(status,'Arquivo acima de 700 KB.');return;}
    try{const bytes=new Uint8Array(await f.arrayBuffer());let bin='';for(let i=0;i<bytes.length;i+=0x8000)bin+=String.fromCharCode(...bytes.subarray(i,i+0x8000));
      const r=await client.stylePreview({name:f.name,content_base64:btoa(bin)});text.value=r.text;ok.checked=false;file.value='';
      const counts=Object.entries(r.removed||{}).map(([k,v])=>`${v} ${String(k).toLowerCase()}`).join(', ');
      say(status,'Identificação removida'+(counts?` (${counts})`:'')+'. Confira o texto, apague o que ainda identificar alguém e salve.','info');
    }catch(e){say(status,e instanceof Error?e.message:'Falha ao ler o arquivo.');}};
  save.onclick=()=>busy(save,async()=>{
    if(!ok.checked){say(status,'Marque que conferiu que o modelo não tem dados de paciente.');return;}
    try{const r=await client.styleSave(text.value);text.value=r.text;say(status,'Modelo salvo: os próximos relatórios seguem este formato.','ok');}
    catch(e){say(status,e instanceof Error?e.message:'Falha ao salvar.');}});
  remove.onclick=()=>busy(remove,async()=>{try{await client.styleDelete();text.value='';ok.checked=false;say(status,'Modelo excluído. Os relatórios voltam ao formato padrão.','info');}catch(e){say(status,e instanceof Error?e.message:'Falha.');}});
  return card;
}

/** Template picker for the medical request. @param {import('./evidence.js').EvidenceClient} client @param {(t:Template|null)=>void} onPick */
export function templatePicker(client,onPick,initial=''){
  const pick=select([['','Sem modelo']]);const info=box('div','status-area');
  /** @type {Template[]} */
  let templates=[];
  client.catalog().then((/** @type {any} */ r)=>{templates=r.templates;for(const t of templates){const o=el('option',t.name+(t.codes_confirmed?'':' (códigos a confirmar)'));o.setAttribute('value',t.template_id);pick.append(o);}if(initial&&templates.some(x=>x.template_id===initial)){pick.value=initial;show();}}).catch(()=>{info.replaceChildren(box('span','muted','Base de modelos indisponível.'));});
  const show=()=>{const t=templates.find(x=>x.template_id===pick.value)||null;info.replaceChildren();if(t)for(const w of t.warnings||[])info.append(box('div','alert alert-warn',w));return t;};
  pick.onchange=()=>onPick(show());
  const wrap=box('div','');wrap.append(field('Modelo de cirurgia',pick,'preenche procedimento, TUSS, OPME e as três marcas'),info);return wrap;
}
