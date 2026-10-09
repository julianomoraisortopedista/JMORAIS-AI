"""Start/stop only the isolated synthetic Compose project; never prints credentials."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
STATE=Path.home()/'.local/share/jmorais-local-pilot'


def prepare():
    STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    if STATE.is_symlink() or STATE.stat().st_mode & 0o077:raise RuntimeError('private state directory required')
    env=STATE/'.env'
    if not env.exists():
        values={name:secrets.token_hex(32) for name in ('LOCAL_DB_PASSWORD','LOCAL_RUNTIME_PASSWORD',
            'LOCAL_OIDC_ADMIN_PASSWORD','LOCAL_PHYSICIAN_PASSWORD','LOCAL_OPERATIONS_PASSWORD',
            'LOCAL_DRAFT_KEY','LOCAL_PSEUDO_KEY')}
        values.update(JMORAIS_LOCAL_SYNTHETIC='YES',LOCAL_PILOT_DIR=str(STATE))
        fd=os.open(env,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(''.join(f'{k}={v}\n' for k,v in values.items()))
    if env.is_symlink() or env.stat().st_mode & 0o077:raise RuntimeError('private env required')
    values=dict(line.split('=',1) for line in env.read_text().splitlines() if line)
    if values.get('LOCAL_PILOT_DIR')!=str(STATE):raise RuntimeError('state location mismatch')
    output=STATE/'output';output.mkdir(exist_ok=True,mode=0o700)
    for name in ('reference','catalog'):(STATE/name).mkdir(exist_ok=True,mode=0o700)
    realm=STATE/'realm.json'
    if not realm.exists():
        def mapper(name,claim,value,multi=False):
            return dict(name=name,protocol='openid-connect',protocolMapper='oidc-hardcoded-claim-mapper',
                config={'claim.name':claim,'claim.value':value,'jsonType.label':'String',
                        'access.token.claim':'true','id.token.claim':'true'})
        clients=[]
        for client,role in (('jmorais-local','reviewer'),('jmorais-operations','service')):
            clients.append(dict(clientId=client,enabled=True,publicClient=True,standardFlowEnabled=True,
                directAccessGrantsEnabled=False,redirectUris=['http://localhost/'],webOrigins=['http://localhost'],
                attributes={'pkce.code.challenge.method':'S256'},defaultClientScopes=['basic','profile','email'],
                protocolMappers=[mapper('role','roles',role),mapper('organization','organization_id','synthetic-org'),
                  {'name':'audience','protocol':'openid-connect','protocolMapper':'oidc-audience-mapper',
                   'config':{'included.client.audience':'jmorais-local','access.token.claim':'true','id.token.claim':'false'}}]))
        users=[]
        for name,subject,key in [('medico','synthetic-physician','LOCAL_PHYSICIAN_PASSWORD'),
                                 ('operations','synthetic-operations','LOCAL_OPERATIONS_PASSWORD')]:
            users.append(dict(id=subject,username=name,enabled=True,emailVerified=True,firstName='Sintético',
                lastName='Piloto',email=name+'@example.invalid',
                credentials=[{'type':'password','value':values[key],'temporary':False}]))
        payload=dict(realm='jmorais-local',enabled=True,sslRequired='none',registrationAllowed=False,
            resetPasswordAllowed=False,loginWithEmailAllowed=False,clients=clients,users=users,**REALM_HARDENING)
        fd=os.open(realm,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(payload,f)
    return env


REALM_HARDENING=dict(bruteForceProtected=True,failureFactor=5,waitIncrementSeconds=60,maxFailureWaitSeconds=900,
    maxDeltaTimeSeconds=43200,permanentLockout=False,accessTokenLifespan=300,ssoSessionIdleTimeout=1800,
    ssoSessionMaxLifespan=36000,passwordPolicy='length(12) and notUsername',revokeRefreshToken=True)


def harden_realm(env_path,url='http://127.0.0.1:8081'):
    """Brute-force lockout, short tokens and sessions on the local realm (idempotent; prints nothing secret)."""
    import urllib.parse
    values=dict(line.split('=',1) for line in Path(env_path).read_text().splitlines() if '=' in line)
    form=urllib.parse.urlencode({'grant_type':'password','client_id':'admin-cli','username':'local-admin',
        'password':values['LOCAL_OIDC_ADMIN_PASSWORD']}).encode()
    for _ in range(30):
        try:
            with urllib.request.urlopen(urllib.request.Request(url+'/realms/master/protocol/openid-connect/token',data=form),timeout=5) as r:
                token=json.load(r)['access_token'];break
        except Exception:
            time.sleep(2)
    else:
        return False
    request=urllib.request.Request(url+'/admin/realms/jmorais-local',data=json.dumps(REALM_HARDENING).encode(),method='PUT',
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=10) as r:
        return r.status in (200,204)


TAILSCALE=('/Applications/Tailscale.localized/Tailscale.app/Contents/MacOS/Tailscale','/Applications/Tailscale.app/Contents/MacOS/Tailscale','/usr/local/bin/tailscale','/opt/homebrew/bin/tailscale')
REMOTE=STATE/'remote.env'


def tailscale(*args,timeout=30):
    for path in TAILSCALE:
        if Path(path).exists():
            r=subprocess.run([path,*args],capture_output=True,text=True,timeout=timeout)
            if 'CLI failed to start' not in (r.stdout+r.stderr):return r
    raise RuntimeError('Tailscale CLI not available')


def private_host():
    data=json.loads(tailscale('status','--json').stdout)
    if data.get('BackendState')!='Running':raise RuntimeError('Tailscale not connected')
    return data['Self']['DNSName'].rstrip('.')


def admin_token(env_path,url='http://127.0.0.1:8081'):
    import urllib.parse
    values=dict(line.split('=',1) for line in Path(env_path).read_text().splitlines() if '=' in line)
    form=urllib.parse.urlencode({'grant_type':'password','client_id':'admin-cli','username':'local-admin',
        'password':values['LOCAL_OIDC_ADMIN_PASSWORD']}).encode()
    for _ in range(40):
        try:
            with urllib.request.urlopen(urllib.request.Request(url+'/realms/master/protocol/openid-connect/token',data=form),timeout=5) as r:
                return json.load(r)['access_token']
        except Exception:
            time.sleep(2)
    raise RuntimeError('identity server not ready')


def admin(token,method,path,body=None,url='http://127.0.0.1:8081'):
    request=urllib.request.Request(url+'/admin/realms/jmorais-local'+path,method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=10) as r:
        raw=r.read()
        return json.loads(raw) if raw else None


def sync_clients(env_path):
    """Redirect URIs and web origins of the browser clients: localhost plus the private address when on."""
    origins=['http://localhost']
    if REMOTE.exists():
        origins.append(dict(l.split('=',1) for l in REMOTE.read_text().splitlines() if '=' in l)['PUBLIC_ORIGIN'])
    token=admin_token(env_path)
    for client in admin(token,'GET','/clients'):
        if client['clientId'] in ('jmorais-local','jmorais-operations'):
            client.update(redirectUris=[o+'/' for o in origins],webOrigins=origins)
            admin(token,'PUT','/clients/'+client['id'],client)
    return True


def reachable(url='http://127.0.0.1/',attempts=10):
    """The page must answer through the host port, not only inside the container."""
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url,timeout=5) as r:
                if r.status==200:return True
        except Exception:
            pass
        time.sleep(1)
    return False


def repair(base,process_env,log):
    """Docker Desktop sometimes keeps the port bound but stops forwarding it; recreate the web front."""
    if reachable(attempts=3):return True
    subprocess.run(base+['restart','frontend'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=process_env)
    if reachable():return True
    subprocess.run(base+['up','-d','--force-recreate','--no-deps','frontend'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=process_env)
    return reachable(attempts=20)


def main():
    os.umask(0o077)  # every file this tool creates is private to the user
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('up','down','proof','repair','remote-on','remote-off'))
    args=parser.parse_args()
    try:
        env=prepare()
        public=STATE/'docker-public';public.mkdir(exist_ok=True,mode=0o700)
        (public/'config.json').write_text(json.dumps({'cliPluginsExtraDirs':['/Applications/Docker.app/Contents/Resources/cli-plugins']}))
        process_env={**os.environ,'DOCKER_CONFIG':str(public),
            'DOCKER_HOST':'unix://'+str(Path.home()/'.docker/run/docker.sock')}
        if args.action in ('up','repair','remote-on','remote-off') and not process_env.get('ANTHROPIC_API_KEY'):
            # Optional Claude key for the evidence workbench, from the Keychain; process env only.
            from jmoraIs.application.support_classification_runtime import keychain_api_key
            key=keychain_api_key()
            if key:process_env['ANTHROPIC_API_KEY']=key

        if args.action=='remote-on':
            host=private_host()
            fd=os.open(REMOTE,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w') as f:f.write(f'PUBLIC_ORIGIN=https://{host}\nOIDC_PUBLIC_URL=https://{host}:8443\n')
            for port,target in (('443','http://127.0.0.1:80'),('8443','http://127.0.0.1:8081')):
                r=tailscale('serve','--bg','--https='+port,target)
                if r.returncode!=0:
                    REMOTE.unlink(missing_ok=True);print('NOT_READY: '+(r.stdout+r.stderr).strip().splitlines()[-1][:200]);return 1
        elif args.action=='remote-off':
            REMOTE.unlink(missing_ok=True)
            try:tailscale('serve','reset')
            except RuntimeError:pass
        base=['docker','compose','--env-file',str(env)]+(['--env-file',str(REMOTE)] if REMOTE.exists() else [])+['-f',str(ROOT/'deploy/local/compose.yml')]
        if args.action=='up':command=base+['up','--build','-d','--wait','--wait-timeout','300']
        elif args.action=='down':command=base+['down'] # Persist named volumes; never -v.
        elif args.action in ('repair','remote-on','remote-off'):command=base+['up','-d','--wait','--wait-timeout','300']
        else:command=base+['run','--rm','--no-deps','seed','python','-m','deploy.local.proof']
        # Persist output privately; sanitized terminal result only.
        log=STATE/(args.action+'.log')
        fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:
            result=subprocess.run(command,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,env=process_env)
            ok=result.returncode==0
            if ok and args.action in ('up','repair','remote-on','remote-off'):
                f.flush();ok=repair(base,process_env,f) and harden_realm(env) and sync_clients(env)
        print(('PASS' if ok else 'NOT_READY')+': '+args.action)
        if args.action in ('up','repair','remote-on','remote-off') and ok:
            print((dict(l.split('=',1) for l in REMOTE.read_text().splitlines() if '=' in l)['PUBLIC_ORIGIN']+'/' if REMOTE.exists() else 'http://localhost/')
                  +' — credentials and launches in private local state directory')
        return 0 if ok else 1
    except Exception as exc:
        print('NOT_READY: '+type(exc).__name__);return 1


if __name__=='__main__':raise SystemExit(main())
