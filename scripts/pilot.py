#!/usr/bin/env python3
"""Local process control around the existing production ASGI factory, not a deployer."""
from __future__ import annotations
import argparse
from dataclasses import dataclass
import getpass
import hashlib
import json
import os
from pathlib import Path
import signal
import ssl
import stat
import subprocess
import sys
import time
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]


class PilotRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    origin: str
    port: int
    certificate: Path
    private_key: Path
    state: Path
    ca_file: str | None

    @classmethod
    def load(cls):
        required = ('JMORAIS_PRODUCTION_COMPOSITION_FACTORY','JMORAIS_WEB_DIST',
            'JMORAIS_PILOT_ORIGIN','JMORAIS_PILOT_PORT','JMORAIS_PILOT_TLS_CERT',
            'JMORAIS_PILOT_TLS_KEY','JMORAIS_PILOT_STATE_DIR')
        if any(not os.environ.get(name,'').strip() for name in required):
            raise PilotRejected('CONFIGURATION_REQUIRED')
        factory = os.environ[required[0]]
        if ':' not in factory or factory.startswith('tests.'):
            raise PilotRejected('REAL_PRODUCTION_FACTORY_REQUIRED')
        origin = os.environ['JMORAIS_PILOT_ORIGIN'].rstrip('/')
        parsed = urlsplit(origin)
        if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or parsed.hostname.endswith('.invalid')):
            raise PilotRejected('VALID_HTTPS_ORIGIN_REQUIRED')
        port = int(os.environ['JMORAIS_PILOT_PORT'])
        if not 1024 <= port <= 65535:raise PilotRejected('UNPRIVILEGED_PORT_REQUIRED')
        state = Path(os.environ['JMORAIS_PILOT_STATE_DIR']).expanduser()
        if not state.is_absolute() or state.is_symlink() or state.resolve().is_relative_to(ROOT):
            raise PilotRejected('PRIVATE_EXTERNAL_STATE_DIRECTORY_REQUIRED')
        certificate = Path(os.environ['JMORAIS_PILOT_TLS_CERT'])
        key = Path(os.environ['JMORAIS_PILOT_TLS_KEY'])
        for path in (certificate,key):
            if not path.is_absolute() or not path.is_file() or path.is_symlink():
                raise PilotRejected('EXTERNAL_TLS_FILES_REQUIRED')
        if key.resolve().is_relative_to(ROOT) or key.stat().st_mode & 0o077:
            raise PilotRejected('PRIVATE_KEY_MUST_BE_EXTERNAL_AND_OWNER_ONLY')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate,key)
        public = json.loads((Path(os.environ['JMORAIS_WEB_DIST'])/'workspace-config.json').read_text())
        redirect = urlsplit(public.get('redirect_uri',''))
        if (public.get('environment')!='PRODUCTION' or
            (redirect.scheme,redirect.netloc)!=(parsed.scheme,parsed.netloc)):
            raise PilotRejected('PRODUCTION_SAME_ORIGIN_CALLBACK_REQUIRED')
        return cls(origin,port,certificate,key,state,os.getenv('JMORAIS_PILOT_CA_FILE') or None)


def token_input(use_stdin):
    if use_stdin:value=sys.stdin.readline().strip()
    elif sys.stdin.isatty():value=getpass.getpass('Authorized operations bearer (memory only): ').strip()
    else:raise PilotRejected('OPERATIONS_CREDENTIAL_REQUIRED')
    if not value or any(x.isspace() for x in value):raise PilotRejected('INVALID_OPERATIONS_CREDENTIAL')
    return value


def fingerprint(pid):
    result = subprocess.run(['ps','-p',str(pid),'-o','lstart=,args='],capture_output=True,text=True)
    if result.returncode or not result.stdout.strip():return None
    return hashlib.sha256(result.stdout.strip().encode()).hexdigest()


def state_path(settings):return settings.state/'process.json'


def read_state(settings):
    path=state_path(settings)
    if path.is_symlink() or not path.is_file():raise PilotRejected('NO_MANAGED_PROCESS')
    if path.stat().st_uid!=os.getuid() or path.stat().st_mode & 0o077:
        raise PilotRejected('UNSAFE_PROCESS_RECORD')
    value=json.loads(path.read_text())
    if not isinstance(value.get('pid'),int) or value['pid']<=1 or value.get('origin')!=settings.origin:
        raise PilotRejected('INVALID_PROCESS_RECORD')
    if not value.get('fingerprint') or fingerprint(value['pid'])!=value['fingerprint']:
        raise PilotRejected('PROCESS_IDENTITY_CHANGED_NO_SIGNAL_SENT')
    return value


def probe(settings, bearer=None):
    results=dict(DATABASE='UNKNOWN',MIGRATIONS='UNKNOWN',BACKEND='DOWN',LIVENESS='FAIL',READINESS='AUTH_REQUIRED',UI='FAIL')
    context=ssl.create_default_context(cafile=settings.ca_file)
    with httpx.Client(base_url=settings.origin,verify=context,timeout=5,follow_redirects=False,trust_env=False) as client:
        live=client.get('/internal/api/v1/health/live')
        if live.status_code==200:results.update(BACKEND='UP',LIVENESS='PASS')
        ui=client.get('/')
        public=client.get('/workspace-config.json')
        if ui.status_code==200 and public.status_code==200:results['UI']='PASS'
        if bearer:
            ready=client.get('/internal/api/v1/health/ready',headers={'authorization':'Bearer '+bearer,'x-purpose':'INTERNAL_OPERATIONS'})
            results['READINESS']='PASS' if ready.status_code==200 and ready.json().get('status')=='READY' else 'FAIL'
            for check in ready.json().get('checks',[]) if ready.status_code==200 else []:
                if check['name'] in ('postgresql','migrations'):
                    results['DATABASE' if check['name']=='postgresql' else 'MIGRATIONS']='PASS' if check['ready'] else 'FAIL'
    return results


def up(settings, bearer):
    settings.state.mkdir(mode=0o700,parents=True,exist_ok=True)
    if settings.state.stat().st_uid!=os.getuid() or settings.state.stat().st_mode & 0o077:
        raise PilotRejected('OWNER_ONLY_STATE_DIRECTORY_REQUIRED')
    # Exclusive creation refuses duplicate starts and stale records; never replaces one.
    descriptor=os.open(state_path(settings),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    process=None
    try:
        with os.fdopen(descriptor,'w') as record:
            command=[sys.executable,'-m','uvicorn','jmoraIs.api.production_asgi:create','--factory',
                '--host','127.0.0.1','--port',str(settings.port),'--ssl-certfile',str(settings.certificate),
                '--ssl-keyfile',str(settings.private_key),'--no-access-log','--no-server-header']
            process=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,start_new_session=True)
            time.sleep(0.2)
            identity=fingerprint(process.pid)
            if not identity:raise PilotRejected('PRODUCTION_STARTUP_REJECTED')
            json.dump(dict(pid=process.pid,fingerprint=identity,origin=settings.origin),record)
        for _ in range(30):
            if process.poll() is not None:raise PilotRejected('PRODUCTION_STARTUP_REJECTED')
            try:
                results=probe(settings,bearer)
                if all(value in ('PASS','UP') for value in results.values()):return results
            except (httpx.HTTPError,ValueError):pass
            time.sleep(1)
        raise PilotRejected('HEALTH_OR_AUTHENTICATED_READINESS_FAILED')
    except BaseException:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=35)
        state_path(settings).unlink(missing_ok=True)
        raise


def down(settings):
    record=read_state(settings)
    os.kill(record['pid'],signal.SIGTERM)
    for _ in range(35):
        if fingerprint(record['pid'])!=record['fingerprint']:
            state_path(settings).unlink()
            return {'BACKEND':'STOPPED'}
        time.sleep(1)
    raise PilotRejected('GRACEFUL_SHUTDOWN_PENDING_NO_FORCE_KILL')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('check','up','status','down'))
    parser.add_argument('--token-stdin',action='store_true',help='Read an operations token from stdin; never an argument/file')
    args=parser.parse_args()
    try:
        settings=Settings.load()
        if args.action=='check':result={'CONFIGURATION':'PASS','LIVE_READINESS':'NOT_PROVEN'}
        elif args.action=='down':result=down(settings)
        elif args.action=='up':result=up(settings,token_input(args.token_stdin))
        else:
            read_state(settings)
            result=probe(settings,token_input(args.token_stdin))
        print(json.dumps(result,sort_keys=True))
        return int(any(value in ('FAIL','UNKNOWN','AUTH_REQUIRED','DOWN') for value in result.values()))
    except Exception as exc:
        code=str(exc) if isinstance(exc,PilotRejected) else type(exc).__name__
        print(json.dumps({'STATUS':'NOT_READY','REASON':code,'SECRET_DETAILS':'WITHHELD'}))
        return 1


if __name__=='__main__':raise SystemExit(main())
