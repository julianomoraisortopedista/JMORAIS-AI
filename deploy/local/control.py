"""Start/stop only the isolated synthetic Compose project; never prints credentials."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess

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
            resetPasswordAllowed=False,loginWithEmailAllowed=False,clients=clients,users=users)
        fd=os.open(realm,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(payload,f)
    return env


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('up','down','proof'))
    args=parser.parse_args()
    try:
        env=prepare()
        public=STATE/'docker-public';public.mkdir(exist_ok=True,mode=0o700)
        (public/'config.json').write_text(json.dumps({'cliPluginsExtraDirs':['/Applications/Docker.app/Contents/Resources/cli-plugins']}))
        process_env={**os.environ,'DOCKER_CONFIG':str(public),
            'DOCKER_HOST':'unix://'+str(Path.home()/'.docker/run/docker.sock')}

        base=['docker','compose','--env-file',str(env),'-f',str(ROOT/'deploy/local/compose.yml')]
        if args.action=='up':command=base+['up','--build','-d','--wait','--wait-timeout','300']
        elif args.action=='down':command=base+['down'] # Persist named volumes; never -v.
        else:command=base+['run','--rm','--no-deps','seed','python','-m','deploy.local.proof']
        # Persist output privately; sanitized terminal result only.
        log=STATE/(args.action+'.log')
        fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:result=subprocess.run(command,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,env=process_env)
        print(('PASS' if result.returncode==0 else 'NOT_READY')+': '+args.action)
        if args.action=='up' and result.returncode==0:print('http://localhost/ — synthetic only; credentials and launches in private local state directory')
        return result.returncode
    except Exception as exc:
        print('NOT_READY: '+type(exc).__name__);return 1


if __name__=='__main__':raise SystemExit(main())
