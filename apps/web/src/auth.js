/** @typedef {{environment:string,issuer:string,client_id:string,redirect_uri:string,scopes:string[]}} AuthConfig */
const transactionKey = 'jmorais.oidc.transaction';
const encode = (/** @type {Uint8Array} */ bytes) => btoa(String.fromCharCode(...bytes)).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');
const random = () => encode(crypto.getRandomValues(new Uint8Array(32)));
const decode = (/** @type {string} */ part) => Uint8Array.from(atob(part.replaceAll('-','+').replaceAll('_','/')), c => c.charCodeAt(0));
export class AuthError extends Error { constructor(){ super('Autenticação indisponível. Entre novamente.'); } }

/** @param {unknown} input @param {string} origin @returns {AuthConfig} */
export function validateConfig(input, origin) {
  if (!input || typeof input !== 'object') throw new AuthError();
  const c = /** @type {Record<string, unknown>} */ (input);
  if (Object.keys(c).some(k=>!['environment','issuer','client_id','redirect_uri','scopes'].includes(k)) ||
      !['DEVELOPMENT','HOMOLOGATION','PRODUCTION'].includes(String(c.environment)) ||
      !c.client_id || typeof c.client_id !== 'string' || typeof c.issuer !== 'string' ||
      typeof c.redirect_uri !== 'string' || !Array.isArray(c.scopes) || !c.scopes.includes('openid') ||
      c.scopes.some(v=>typeof v !== 'string' || !v || /\s/.test(v))) throw new AuthError();
  const issuer = new URL(c.issuer), redirect = new URL(c.redirect_uri);
  const local = (/** @type {URL} */ u) => c.environment === 'DEVELOPMENT' && u.protocol === 'http:' && ['localhost','127.0.0.1','[::1]'].includes(u.hostname);
  if ((issuer.protocol !== 'https:' && !local(issuer)) || issuer.username || issuer.password || issuer.search || issuer.hash ||
      (redirect.protocol !== 'https:' && !local(redirect)) || redirect.origin !== origin ||
      redirect.username || redirect.password || redirect.search || redirect.hash) throw new AuthError();
  return /** @type {AuthConfig} */ (c);
}

/** Public client: one-use PKCE transaction survives redirect, tokens never do. */
export class BrowserAuth {
  /** @type {string|null} */ #token = null;
  #expires = 0;
  /** @param {AuthConfig} config @param {Storage} storage @param {typeof fetch} request */
  constructor(config, storage, request = (/** @type {RequestInfo|URL} */ input, /** @type {RequestInit|undefined} */ init) => fetch(input, init)) { this.config=config; this.storage=storage; this.request=request; }
  async discovery() {
    const r=await this.request(this.config.issuer.replace(/\/$/,'')+'/.well-known/openid-configuration',{cache:'no-store',credentials:'omit',redirect:'error'});
    if(!r.ok) throw new AuthError();
    const d=await r.json();
    if(d.issuer!==this.config.issuer || !d.code_challenge_methods_supported?.includes('S256') ||
       !d.response_types_supported?.includes('code') || !d.id_token_signing_alg_values_supported?.includes('RS256')) throw new AuthError();
    for(const k of ['authorization_endpoint','token_endpoint','jwks_uri']) {
      const u=new URL(d[k]);
      if(u.username || u.password || u.hash || (u.protocol!=='https:' && !(this.config.environment==='DEVELOPMENT' && u.protocol==='http:' && ['localhost','127.0.0.1','[::1]'].includes(u.hostname)))) throw new AuthError();
    }
    return d;
  }
  async begin() {
    this.logout();
    const d=await this.discovery(), verifier=random(), state=random(), nonce=random();
    const challenge=encode(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier))));
    this.storage.setItem(transactionKey,JSON.stringify({verifier,state,nonce,created:Date.now(),issuer:this.config.issuer,client:this.config.client_id,redirect:this.config.redirect_uri}));
    const url=new URL(d.authorization_endpoint);
    url.search=new URLSearchParams({response_type:'code',client_id:this.config.client_id,redirect_uri:this.config.redirect_uri,
      scope:this.config.scopes.join(' '),state,nonce,code_challenge:challenge,code_challenge_method:'S256'}).toString();
    return url.href;
  }
  /** @param {URL} url @param {(path:string)=>void} clearURL */
  async callback(url,clearURL) {
    const raw=this.storage.getItem(transactionKey);
    this.storage.removeItem(transactionKey);
    clearURL(new URL(this.config.redirect_uri).pathname);
    try {
      const t=JSON.parse(raw || 'null');
      if(!t || Date.now()-t.created>300000 || Date.now()<t.created || t.issuer!==this.config.issuer ||
          t.client!==this.config.client_id || t.redirect!==this.config.redirect_uri ||
          url.origin+url.pathname!==this.config.redirect_uri || url.searchParams.getAll('state').length!==1 ||
          url.searchParams.get('state')!==t.state || url.searchParams.getAll('code').length!==1 || url.searchParams.has('error')) throw new AuthError();
      const code=url.searchParams.get('code');
      if(!code || (url.searchParams.has('iss') && url.searchParams.get('iss')!==this.config.issuer)) throw new AuthError();
      const d=await this.discovery();
      const r=await this.request(d.token_endpoint,{method:'POST',cache:'no-store',credentials:'omit',redirect:'error',
        headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'authorization_code',
          client_id:this.config.client_id,redirect_uri:this.config.redirect_uri,code,code_verifier:t.verifier})});
      if(!r.ok) throw new AuthError();
      const result=await r.json();
      if(typeof result.access_token!=='string' || !result.access_token || String(result.token_type).toLowerCase()!=='bearer' ||
          !Number.isFinite(result.expires_in) || result.expires_in<=0) throw new AuthError();
      await this.verifyIdentity(result.id_token,t.nonce,d.jwks_uri);
      this.#token=result.access_token; this.#expires=Date.now()+result.expires_in*1000;
    } catch { this.logout(); throw new AuthError(); }
  }
  /** @param {string} token @param {string} nonce @param {string} jwks */
  async verifyIdentity(token,nonce,jwks) {
    if(typeof token!=='string') throw new AuthError();
    const parts=token.split('.'); if(parts.length!==3) throw new AuthError();
    const header=JSON.parse(new TextDecoder().decode(decode(parts[0])));
    const claims=JSON.parse(new TextDecoder().decode(decode(parts[1])));
    const aud=Array.isArray(claims.aud)?claims.aud:[claims.aud];
    if(header.alg!=='RS256' || header.crit || !header.kid || claims.iss!==this.config.issuer ||
       !aud.includes(this.config.client_id) || (aud.length>1 && claims.azp!==this.config.client_id) ||
       (claims.azp && claims.azp!==this.config.client_id) || claims.nonce!==nonce || typeof claims.sub!=='string' || !claims.sub ||
       !Number.isFinite(claims.exp) || claims.exp<=Date.now()/1000 || !Number.isFinite(claims.iat) ||
       claims.iat>Date.now()/1000+30 || (claims.nbf && claims.nbf>Date.now()/1000+30)) throw new AuthError();
    const r=await this.request(jwks,{cache:'no-store',credentials:'omit',redirect:'error'});
    if(!r.ok) throw new AuthError();
    const data=await r.json();
    const keys=data.keys.filter((/** @type {JsonWebKey & {kid?:string}} */ k)=>k.kid===header.kid && k.kty==='RSA' && (!k.use || k.use==='sig') && (!k.alg || k.alg==='RS256') && (!k.key_ops || k.key_ops.includes('verify')));
    if(keys.length!==1) throw new AuthError();
    const key=await crypto.subtle.importKey('jwk',keys[0],{name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['verify']);
    if(!await crypto.subtle.verify('RSASSA-PKCS1-v1_5',key,decode(parts[2]),new TextEncoder().encode(parts[0]+'.'+parts[1]))) throw new AuthError();
  }
  bearer() { if(!this.#token || Date.now()>=this.#expires){this.logout();throw new AuthError();} return this.#token; }
  logout() { this.#token=null; this.#expires=0; this.storage.removeItem(transactionKey); }
}
