export const viewers = /** @type {const} */ (['summary','timeline','evidence','explainability','medical_document','human_review','audit_defense']);
/** @typedef {typeof viewers[number]} Viewer */
/** @typedef {import('./contracts.js').PersistedClinicalWorkspaceLaunchReference} LaunchReference */
/** @typedef {NonNullable<Bootstrap['references'][keyof Bootstrap['references']]>} ExactReference */
/** @typedef {import('./contracts.js').WorkspaceBootstrapResponse} Bootstrap */
/** @typedef {import('./contracts.js').WorkspaceContextResponse} Caller */
export class ApiError extends Error {
  /** @param {number} status */
  constructor(status){super(status===401?'Sessão encerrada. Entre novamente.':status===403?'Acesso não autorizado.':status===503?'Workspace indisponível.':'Não foi possível carregar os dados.');this.status=status;}
}
/** @param {unknown} raw @returns {LaunchReference} */
export function launchReference(raw) {
  if(!raw || typeof raw!=='object') throw new ApiError(422);
  const r=/** @type {Record<string,unknown>} */(raw);
  if(Object.keys(r).sort().join(',')!=='integrity_hash,launch_id,tenant_id,version' || r.version!==1 ||
     typeof r.launch_id!=='string' || !r.launch_id || r.launch_id.length>80 ||
     typeof r.tenant_id!=='string' || !r.tenant_id || typeof r.integrity_hash!=='string' || !/^[a-f0-9]{64}$/.test(r.integrity_hash)) throw new ApiError(422);
  return /** @type {LaunchReference} */(r);
}
export class WorkspaceClient {
  /** @param {()=>string} bearer @param {typeof fetch} request */
  constructor(bearer,request=fetch){this.bearer=bearer;this.request=request;}
  /** @param {string} path @param {unknown} body @param {AbortSignal|undefined} signal */
  async read(path,body=undefined,signal=undefined){
    const r=await this.request('/internal/api/v1/workspace/'+path,{method:body===undefined?'GET':'POST',
      headers:{Authorization:'Bearer '+this.bearer(),...(body===undefined?{}:{'Content-Type':'application/json'})},
      body:body===undefined?undefined:JSON.stringify(body),signal,cache:'no-store',credentials:'omit',redirect:'error'});
    if(!r.ok) throw new ApiError(r.status);
    return r.json();
  }
  /** @returns {Promise<Caller>} */
  context(){return this.read('context');}
  /** @param {LaunchReference} reference @returns {Promise<Bootstrap>} */
  bootstrap(reference){return this.read('bootstrap',{reference});}
  /** @param {Viewer} viewer @param {ExactReference} reference @param {AbortSignal} signal @returns {Promise<Record<string,unknown>>} */
  view(viewer,reference,signal){
    if(!viewers.includes(viewer)) throw new ApiError(422);
    return this.read(viewer.replaceAll('_','-')+'/resolve',{reference},signal);
  }
}
