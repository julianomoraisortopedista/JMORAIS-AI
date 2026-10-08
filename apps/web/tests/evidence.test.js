import test from 'node:test';
import assert from 'node:assert/strict';
import {EvidenceClient,EvidenceError} from '../src/evidence.js';

const respond=(status,body)=>({ok:status<400,status,json:async()=>body});

test('evidence calls carry the in-memory bearer to the platform route only',async()=>{
  const calls=[];
  const client=new EvidenceClient(()=>'token-1',async(url,init)=>{calls.push([url,init]);return respond(200,{ok:true});});
  await client.search({population:'knee osteoarthritis'});
  await client.remove('26488691');
  const [[url,init],[url2,init2]]=calls;
  assert.equal(url,'/internal/evidence/api/search');
  assert.equal(init.headers.Authorization,'Bearer token-1');
  assert.equal(init.credentials,'omit');assert.equal(init.redirect,'error');assert.equal(init.cache,'no-store');
  assert.deepEqual(JSON.parse(init.body),{population:'knee osteoarthritis'});
  assert.equal(url2,'/internal/evidence/api/decisions/26488691');assert.equal(init2.method,'DELETE');
});

test('server detail is shown, validation lists are joined, unknown errors are generic',async()=>{
  const fail=(status,body)=>new EvidenceClient(()=>'t',async()=>respond(status,body));
  await assert.rejects(fail(400,{detail:'O trecho precisa ser literal.'}).manual({}),(e)=>e instanceof EvidenceError&&e.message==='O trecho precisa ser literal.');
  await assert.rejects(fail(422,{detail:[{msg:'a'},{msg:'b'}]}).document({}),(e)=>e.message==='a; b');
  await assert.rejects(fail(401,null).status(),(e)=>e.status===401&&e.message.includes('Entre novamente'));
  await assert.rejects(fail(500,{}).status(),(e)=>e.message==='Não foi possível concluir a operação.');
});

test('fetch is never stored unbound as a method (browsers throw Illegal invocation)',async()=>{
  const {readFile,readdir}=await import('node:fs/promises');
  for(const f of (await readdir('src')).filter(f=>f.endsWith('.js'))){
    const s=await readFile('src/'+f,'utf8');
    assert.ok(!/request\s*=\s*fetch\b/.test(s),f+' stores fetch unbound');
  }
});

test('external services are links only and identifiers go to the verifying import route',async()=>{
  const {readFile}=await import('node:fs/promises');
  const src=await readFile('src/evidence.js','utf8');
  assert.ok(!/fetch\(\s*['"]https:\/\/(www\.)?(openevidence|myorthoevidence)/.test(src));
  const calls=[];
  const client=new EvidenceClient(()=>'t',async(url,init)=>{calls.push([url,JSON.parse(init.body)]);return respond(200,{candidates:[],invalid:[]});});
  await client.importIds('26488691');
  assert.deepEqual(calls,[['/internal/evidence/api/import',{identifiers:'26488691'}]]);
});

test('patient identification only goes to the de-identifying routes, never to the document request',async()=>{
  const {readFile}=await import('node:fs/promises');
  const src=await readFile('src/case.js','utf8');
  const documentCall=src.slice(src.indexOf('client.document({'),src.indexOf('});',src.indexOf('client.document({')));
  assert.ok(documentCall.length>20 && !/identifiers|patient\./.test(documentCall));
  // identifiers are sent only with case create and each upload (for removal), in both the detailed and the quick flows
  const all=(src.match(/identifiers:identifiers\(\)/g)||[]).length;
  const allowed=(src.match(/client\.case(Create|Document)\([^;]*?identifiers:identifiers\(\)/g)||[]).length
    +(src.match(/export function caseContext\(\)\{[^}]*identifiers:identifiers\(\)/g)||[]).length;
  assert.ok(all>=3 && all===allowed);
  // contestations: identifiers go only to the drafting route (for removal); patient data only into the local document
  const appeals=await readFile('src/appeals.js','utf8');
  assert.equal((appeals.match(/identifiers:c\./g)||[]).length,1);
  assert.ok(/client\.appealDraft\(\{[^;]*identifiers:c\.identifiers/.test(appeals));
  assert.ok(!/client\.\w+\([^)]*patient/.test(appeals));
  assert.ok(src.includes("doc.querySelectorAll('[data-ident]')"));
});

test('dictation appends to the given field only, in pt-BR, and degrades without speech support',async()=>{
  const {readFile}=await import('node:fs/promises');
  const src=await readFile('src/dictation.js','utf8');
  assert.ok(src.includes("r.lang='pt-BR'") && src.includes('target.value=base+committed+interim'));
  assert.ok(!/fetch\(|XMLHttpRequest|WebSocket/.test(src));
  const {dictation}=await import('../src/dictation.js');
  const created=[];
  globalThis.window={};globalThis.document={createElement:(tag)=>{const n={tagName:tag,className:'',textContent:'',children:[],attributes:{},append(...c){this.children.push(...c);},setAttribute(k,v){this.attributes[k]=v;}};created.push(n);return n;}};
  const node=dictation({value:''});
  assert.ok(JSON.stringify(node).includes('Fn duas vezes'));
});

test('portuguese question goes to the drafting route and fills the PICO fields before searching',async()=>{
  const calls=[];
  const client=new EvidenceClient(()=>'t',async(url,init)=>{calls.push([url,JSON.parse(init.body)]);return respond(200,{});});
  await client.question('A ATJ melhora a dor?',null);
  assert.deepEqual(calls,[['/internal/evidence/api/question',{question:'A ATJ melhora a dor?',template_id:null}]]);
  const {readFile}=await import('node:fs/promises');
  const src=await readFile('src/evidence.js','utf8');
  assert.ok(src.includes("population.value=d.population.join('; ')") && src.includes('go.click()'));
});

test('letterhead logo is limited to PNG/JPEG data and the prescription never calls the API with patient data',async()=>{
  const {readFile}=await import('node:fs/promises');
  const src=await readFile('src/letterhead.js','utf8');
  assert.ok(src.includes("/^image\\/(png|jpeg)$/.test(lh.logo_type)"));
  assert.ok(!/innerHTML|outerHTML\s*=|insertAdjacentHTML/.test(src));
  const rx=src.slice(src.indexOf('export function prescriptionPage'));
  assert.ok(!/client\.(case|document|request|question|propose)/.test(rx)); // only letterhead/profile are read
});

test('idle sessions are closed and patient data cleared',async()=>{
  const {readFile}=await import('node:fs/promises');
  const src=await readFile('src/main.js','utf8');
  assert.ok(src.includes('const IDLE_MS=20*60*1000') && /Date\.now\(\)-lastActivity>IDLE_MS\)\{reset\(\);login\(\)/.test(src));
  assert.ok(/function reset\(\)\{[^}]*clearCase\(\)/.test(src));
});
