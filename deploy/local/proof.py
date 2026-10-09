"""Local real Keycloak authorization-code/PKCE + seven-viewer acceptance (no mock JWT)."""
import base64
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlencode,urlsplit,parse_qs
import jwt
import requests
from sqlalchemy import create_engine,text
from deploy.local.runtime import database_url,ISSUER

# Remote access mode moves the public origin and issuer to the private HTTPS address.
ORIGIN=os.environ.get('PUBLIC_ORIGIN','http://localhost')
OIDC_PUBLIC=os.environ.get('OIDC_PUBLIC_URL','http://localhost:8081')


class LoginForm(HTMLParser):
    def __init__(self):super().__init__();self.action=None;self.fields={}
    def handle_starttag(self, tag, attrs):
        values=dict(attrs)
        if tag=='form' and values.get('id')=='kc-form-login':self.action=values['action']
        if tag=='input' and values.get('type')=='hidden' and values.get('name'):
            self.fields[values['name']]=values.get('value','')


def login(operations=False):
    client='jmorais-operations' if operations else 'jmorais-local'
    verifier=secrets.token_urlsafe(48);state=secrets.token_urlsafe(24);nonce=secrets.token_urlsafe(24)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    base='http://oidc:8080/realms/jmorais-local/protocol/openid-connect/'
    with requests.Session() as session:
        response=session.get(base+'auth',params=dict(client_id=client,response_type='code',
            redirect_uri='http://localhost/',scope='openid profile',state=state,nonce=nonce,
            code_challenge=challenge,code_challenge_method='S256'),timeout=15)
        response.raise_for_status()
        form=LoginForm();form.feed(response.text)
        if not form.action:raise RuntimeError('OIDC_LOGIN_FORM_UNAVAILABLE')
        target=form.action.replace(OIDC_PUBLIC+'/','http://oidc:8080/')
        if not target.startswith('http://oidc:8080/'):raise RuntimeError('OIDC_LOGIN_ORIGIN_REJECTED')
        response=session.post(target,data={**form.fields,'username':'operations' if operations else 'medico',
            'password':os.environ['LOCAL_OPERATIONS_PASSWORD' if operations else 'LOCAL_PHYSICIAN_PASSWORD']},
            allow_redirects=False,timeout=15)
        location=response.headers.get('location','')
        parts=urlsplit(location);query=parse_qs(parts.query)
        if parts.netloc!='localhost' or query.get('state')!=[state] or not query.get('code'):
            raise RuntimeError('OIDC_LOGIN_REJECTED')
        response=session.post(base+'token',data=dict(grant_type='authorization_code',client_id=client,
            redirect_uri='http://localhost/',code=query['code'][0],code_verifier=verifier),timeout=15)
        response.raise_for_status();tokens=response.json()
        keys=session.get(base+'certs',timeout=15).json()['keys']
        header=jwt.get_unverified_header(tokens['id_token'])
        key=next(k for k in keys if k['kid']==header['kid'])
        claims=jwt.decode(tokens['id_token'],jwt.PyJWK.from_dict(key).key,algorithms=['RS256'],audience=client,issuer=ISSUER)
        if claims.get('nonce')!=nonce:raise RuntimeError('OIDC_NONCE_REJECTED')
        return tokens['access_token']


def main():
    auth={'authorization':'Bearer '+login()}
    ops={'authorization':'Bearer '+login(True),'x-purpose':'INTERNAL_OPERATIONS'}
    base='http://frontend'
    host=urlsplit(ORIGIN).netloc
    def request(method,path,**kwargs):
        response=requests.request(method,base+path,headers={'Host':host,**kwargs.pop('headers',{})},timeout=30,**kwargs)
        return response
    prefix='/internal/api/v1/'
    assert request('GET','/').status_code==200
    assert request('GET','/workspace-config.json').json()['redirect_uri']==ORIGIN+'/'
    assert request('GET',prefix+'health/live').status_code==200
    ready=request('GET',prefix+'health/ready',headers=ops)
    assert ready.status_code==200 and ready.json()['status']=='READY','READINESS_FAILED'
    assert request('GET',prefix+'workspace/context',headers=auth).status_code==200,'CALLER_CONTEXT_FAILED'
    count=0
    for path in sorted(Path('/pilot-output').glob('patient-*-launch.json')):
        body={'reference':json.loads(path.read_text())}
        assert request('POST',prefix+'workspace/bootstrap',json=body).status_code==401
        assert request('POST',prefix+'workspace/bootstrap',json=body,headers={**auth,'x-tenant-id':'forbidden'}).status_code in (401,403)
        wrong={'reference':{**body['reference'],'integrity_hash':'0'*64}}
        assert request('POST',prefix+'workspace/bootstrap',json=wrong,headers=auth).status_code==403
        result=request('POST',prefix+'workspace/bootstrap',json=body,headers=auth)
        assert result.status_code==200, f'BOOTSTRAP_FAILED_HTTP_{result.status_code}'
        references=result.json()['references'];assert len(references)==7 and all(references.values())
        for name,reference in references.items():
            route=prefix+'workspace/'+name.replace('_','-')+'/resolve'
            r=request('POST',route,json={'reference':reference},headers=auth)
            assert r.status_code==200,name+'_VIEWER_FAILED'
            assert 'no-store' in r.headers['cache-control']
            assert request('DELETE',route,headers=auth).status_code==405
        count+=1
    assert count==3,'THREE_SYNTHETIC_LAUNCHES_REQUIRED'
    from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine
    owner=create_engine(database_url(True))
    report=PostgreSQLCryptographicReplayEngine(owner).replay_all()
    assert report.overall_decision.value=='VALID','REPLAY_NOT_VALID'
    with owner.connect() as c:
        assert c.execute(text("SELECT NOT rolsuper AND NOT rolbypassrls FROM pg_roles WHERE rolname='pilot_runtime'")).scalar_one()
    owner.dispose()
    print('LOCAL_PASS: real OIDC code+PKCE, 3 launches, 7 viewers each, readiness, authorization, replay VALID, runtime NOBYPASSRLS')


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('LOCAL_NOT_READY: '+type(exc).__name__+((': '+str(exc)) if isinstance(exc,AssertionError) else ''))
        import traceback
        print('LOCATION: '+ ' -> '.join(f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}' for frame in traceback.extract_tb(exc.__traceback__)))
        raise SystemExit(1)
