import test from 'node:test';
import assert from 'node:assert/strict';
import {BrowserAuth,validateConfig} from '../src/auth.js';
import {WorkspaceClient,launchReference,viewers} from '../src/client.js';
const config={environment:'PRODUCTION',issuer:'https://identity.example',client_id:'test-public-client',redirect_uri:'https://workspace.example/callback',scopes:['openid','api:read']};
class Storage {data=new Map();setItem(k,v){this.data.set(k,v);}getItem(k){return this.data.get(k)??null;}removeItem(k){this.data.delete(k);}}
const b64=x=>Buffer.from(x).toString('base64url');
const json=x=>new Response(JSON.stringify(x),{headers:{'Content-Type':'application/json'}});
async function fixture(){
 const pair=await crypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
 const jwk={...await crypto.subtle.exportKey('jwk',pair.publicKey),kid:'fixture',alg:'RS256',use:'sig'};
 const storage=new Storage();let nonce='';let exchange;let tokenNonce;
 const request=async(url,options)=>{
  if(url.endsWith('openid-configuration'))return json({issuer:config.issuer,authorization_endpoint:config.issuer+'/authorize',token_endpoint:config.issuer+'/token',jwks_uri:config.issuer+'/jwks',response_types_supported:['code'],code_challenge_methods_supported:['S256'],id_token_signing_alg_values_supported:['RS256']});
  if(url.endsWith('/jwks'))return json({keys:[jwk]});
  if(url.endsWith('/token')){
   exchange=options;const now=Math.floor(Date.now()/1000);
   const input=b64(JSON.stringify({alg:'RS256',kid:'fixture'}))+'.'+b64(JSON.stringify({iss:config.issuer,aud:config.client_id,sub:'doctor',nonce:tokenNonce??nonce,iat:now,exp:now+300}));
   const signature=await crypto.subtle.sign('RSASSA-PKCS1-v1_5',pair.privateKey,Buffer.from(input));
   return json({access_token:'local_test_only_browser_token',token_type:'Bearer',expires_in:300,id_token:input+'.'+b64(signature)});
  }
  throw new Error('Unexpected fixture request');
 };
 const auth=new BrowserAuth(validateConfig(config,'https://workspace.example'),storage,request);
 const url=new URL(await auth.begin());nonce=url.searchParams.get('nonce');
 return {auth,storage,url,get exchange(){return exchange;},set tokenNonce(v){tokenNonce=v;}};
}
test('public config rejects missing fields, secret and unsafe redirects',()=>{
 assert.deepEqual(validateConfig(config,'https://workspace.example'),config);
 for(const c of [{},{...config,client_secret:'forbidden'},{...config,client_id:''},{...config,issuer:'http://identity.example'},{...config,redirect_uri:'https://other.example/callback'}])assert.throws(()=>validateConfig(c,'https://workspace.example'));
});
test('Code + PKCE S256, signed nonce, one-use callback and memory bearer',async()=>{
 const f=await fixture();const t=JSON.parse([...f.storage.data.values()][0]);
 assert.equal(f.url.searchParams.get('response_type'),'code');assert.equal(f.url.searchParams.get('code_challenge_method'),'S256');
 assert.equal(f.url.searchParams.get('code_challenge'),b64(await crypto.subtle.digest('SHA-256',Buffer.from(t.verifier))));
 assert.equal(f.url.searchParams.has('client_secret'),false);
 const callback=new URL(config.redirect_uri+'?code=one-use&state='+t.state);let cleared;
 await f.auth.callback(callback,p=>{cleared=p;});assert.equal(cleared,'/callback');
 assert.equal(f.storage.data.size,0);assert.equal(f.auth.bearer(),'local_test_only_browser_token');
 assert.equal(f.exchange.body.get('code_verifier'),t.verifier);assert.equal(f.exchange.body.has('client_secret'),false);
 const calls=[];const client=new WorkspaceClient(()=>f.auth.bearer(),async(url,options)=>{calls.push({url,options});return json({});});
 const reference=launchReference({launch_id:'cwl_test',version:1,tenant_id:'tenant',integrity_hash:'a'.repeat(64)});
 await client.bootstrap(reference);assert.deepEqual(JSON.parse(calls[0].options.body),{reference});
 assert.equal(calls[0].options.headers.Authorization,'Bearer local_test_only_browser_token');assert.equal(calls[0].options.cache,'no-store');
 assert.equal(Object.keys(calls[0].options.headers).some(x=>x.toLowerCase().startsWith('x-')),false);
 for(const viewer of viewers)await client.view(viewer,{reference_id:'transport-unchanged'},new AbortController().signal);
 assert.equal(calls.length,8);assert.ok(calls.every(c=>c.options.method==='POST'));
 await assert.rejects(f.auth.callback(callback,()=>{}));assert.throws(()=>f.auth.bearer());
});
test('wrong state/nonce rejected, logout clears auth state',async()=>{
 const f=await fixture();let cleared=false;
 await assert.rejects(f.auth.callback(new URL(config.redirect_uri+'?code=c&state=wrong'),()=>{cleared=true;}));assert.equal(cleared,true);assert.equal(f.storage.data.size,0);
 const g=await fixture();g.tokenNonce='wrong';await assert.rejects(g.auth.callback(new URL(config.redirect_uri+'?code=c&state='+g.url.searchParams.get('state')),()=>{}));assert.throws(()=>g.auth.bearer());
 const h=await fixture();h.auth.logout();assert.equal(h.storage.data.size,0);assert.throws(()=>h.auth.bearer());
});
test('scalar launch reconstruction denied; server errors sanitized',async()=>{
 assert.throws(()=>launchReference({launch_id:'alone'}));
 for(const status of [401,403,409,500,503]){const c=new WorkspaceClient(()=> 'test-fixture',async()=>new Response('SECRET CLINICAL ERROR',{status}));await assert.rejects(c.context(),e=>e.status===status&&!e.message.includes('SECRET'));}
});
