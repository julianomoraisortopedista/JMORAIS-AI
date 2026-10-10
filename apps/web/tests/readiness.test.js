import test from 'node:test';
import assert from 'node:assert/strict';
import {readiness} from '../src/readiness.js';

const facts=['TRATAMENTO_CONSERVADOR','ACHADO_IMAGEM','EXAME_FISICO','ESCALA_FUNCIONAL'].map(category=>({category}));
const template={codes_confirmed:true,opme:[{description:'Componente femoral',quantity:1}],suppliers:[{label:'A'},{label:'B'},{label:'C'}]};
const science={references:[{direction:'SUPPORTING',high_level:true}]};
const full={facts,icd10:['M17.1'],gaps:[],science,template,schedule:{hospital:'H',date:'2026-10-20'},checks:[]};

test('a complete request has nothing missing',()=>{
  assert.deepEqual(readiness(full).filter(i=>!i.ok),[]);
});
test('missing conservative treatment, evidence or suppliers block sending',()=>{
  const r=readiness({...full,facts:facts.slice(1),science:{references:[{direction:'NEUTRAL',high_level:false}]},
    template:{...template,suppliers:[{label:'A'},{label:' '}]}});
  const blocking=r.filter(i=>!i.ok&&i.blocking).map(i=>i.label);
  assert.ok(blocking.some(l=>l.startsWith('Tratamento conservador')));
  assert.ok(blocking.some(l=>l.startsWith('Fundamentação científica')));
  assert.ok(blocking.some(l=>l.startsWith('OPME com 3 empresas')));
  assert.ok(r.some(i=>!i.ok&&!i.blocking&&i.label.startsWith('Ao menos uma diretriz')));
});
test('SBOT blocking finding and gaps are reported; no template means no supplier rule',()=>{
  const r=readiness({...full,template:null,gaps:['Exame físico ausente'],checks:[{level:'BLOQUEIO'}]});
  assert.ok(r.some(i=>!i.ok&&i.label==='Codificação conforme SBOT'));
  assert.ok(r.some(i=>!i.ok&&i.label==='Relatório sem lacunas'));
  assert.ok(!r.some(i=>i.label.startsWith('OPME')));
});
