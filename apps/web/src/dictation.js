/** Voice dictation into a text field using the browser's built-in speech recognition (pt-BR). */
import {box,button} from './evidence.js';

/** @returns {any} */
function recognitionClass(){const w=/** @type {any} */(window);return w.SpeechRecognition||w.webkitSpeechRecognition||null;}

/**
 * Microphone button that appends dictated text to `target`. The browser's speech service
 * processes the audio (Chrome: Google; Safari: Apple). Avoid saying patient identifiers;
 * the text still goes through de-identification before any AI step.
 * @param {HTMLTextAreaElement} target
 */
export function dictation(target){
  const wrap=box('div','dictation');
  const Recognition=recognitionClass();
  if(!Recognition){
    wrap.append(box('span','hint','Ditado: este navegador não oferece reconhecimento de voz. No Mac, use o ditado do sistema (tecla Fn duas vezes) dentro do campo.'));
    return wrap;
  }
  const mic=button('🎤 Ditar','ghost');mic.setAttribute('aria-pressed','false');
  const status=box('span','hint','Fale em português. Não diga nome, CPF ou carteirinha do paciente.');
  wrap.append(mic,status);
  /** @type {any} */ let active=null;
  const stop=()=>{if(active){active.onend=null;active.stop();}active=null;mic.textContent='🎤 Ditar';mic.setAttribute('aria-pressed','false');mic.classList.remove('is-recording');};
  mic.onclick=()=>{
    if(active){stop();status.textContent='Ditado encerrado.';return;}
    const r=new Recognition();r.lang='pt-BR';r.continuous=true;r.interimResults=true;
    const base=target.value&&!/\s$/.test(target.value)?target.value+' ':target.value;let committed='';
    r.onresult=(/** @type {any} */ e)=>{
      let interim='';
      for(let i=e.resultIndex;i<e.results.length;i++){const t=e.results[i][0].transcript;if(e.results[i].isFinal)committed+=t.trim()+' ';else interim+=t;}
      target.value=base+committed+interim;target.dispatchEvent(new Event('input'));
    };
    r.onerror=(/** @type {any} */ e)=>{status.textContent=e.error==='not-allowed'?'Permita o uso do microfone no navegador.':'Ditado interrompido ('+e.error+').';stop();};
    r.onend=()=>{if(active){try{active.start();}catch{stop();}}};
    try{r.start();active=r;mic.textContent='⏹ Parar';mic.setAttribute('aria-pressed','true');mic.classList.add('is-recording');status.textContent='Ouvindo… fale normalmente; clique em Parar ao terminar.';}
    catch{status.textContent='Não foi possível iniciar o microfone.';}
  };
  return wrap;
}
