import test from 'node:test';
import assert from 'node:assert/strict';
import {opmeRxContent} from '../src/opmerx.js';

const t={name:'Bloqueio de nervos geniculares',tuss_codes:['31403026'],tuss_terms:{'31403026':'Bloqueio de nervo periférico'},
  opme:[{description:'Kit cânula com tela radiopaca',quantity:1}],material_specs:['Cânula ecogênica'],imaging_guidance:['Ultrassonografia'],
  material_justification:'Segurança',equivalent_brands:['Evereast'],
  suppliers:[{label:'DNA Biotecnologia',product:'Spineedle',anvisa:'81420899005',contact:'vendas@x'},{label:'Orthoprime',product:'Spineedle',anvisa:'81420899005'},{label:'Alpine',product:'Spineedle',anvisa:'81420899005'}]};

test('OPME prescription lists material, specification, three suppliers with ANVISA and justification',()=>{
  const c=opmeRxContent(t);
  assert.deepEqual(c.problems,[]);
  assert.equal(c.suppliers.length,3);assert.deepEqual(c.suppliers[0],['DNA Biotecnologia','Spineedle','81420899005','vendas@x']);
  assert.ok(c.lines.some(l=>l.startsWith('OPME: 01 (um) Kit cânula'))&&c.lines.some(l=>l==='Justificativa: Segurança'));
});
test('missing suppliers or ANVISA block the prescription',()=>{
  const c=opmeRxContent({...t,suppliers:[{label:'A',anvisa:'123'}]});
  assert.equal(c.problems.length,2);
});
