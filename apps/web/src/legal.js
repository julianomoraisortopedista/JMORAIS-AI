/** Norms cited in the physician's text, checked against the verified legal library. */
import {box,button,busy} from './evidence.js';

/** @param {import('./evidence.js').EvidenceClient} client @param {()=>string} text @returns {HTMLElement} */
export function legalPanel(client,text){
  const wrap=box('div','');const out=box('div','');const again=button('Conferir citações normativas','quiet');
  wrap.append(box('h3','section-title','Citações normativas'),out,again);
  const run=async()=>{
    try{const r=await client.legalCheck(text());out.replaceChildren();
      if(!r.citations.length){out.append(box('p','muted','Nenhuma norma citada no texto.'));return;}
      for(const c of r.citations){
        if(c.status==='VERIFIED'){const d=document.createElement('details');const s=document.createElement('summary');
          s.textContent=`✓ ${c.cited} — conferida. Compare a frase com o texto oficial:`;d.append(s);
          for(const src of c.sources)d.append(box('p','muted',`${src.citation}: "${src.excerpt}"`));out.append(d);}
        else out.append(box('div','alert alert-warn',`Não conferida: ${c.cited}. Confirme no texto oficial ou retire: "${c.sentence}"`));}
    }catch{out.replaceChildren(box('p','muted','Conferência indisponível agora.'));}
  };
  again.onclick=()=>busy(again,run);run();
  return wrap;
}
