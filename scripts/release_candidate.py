#!/usr/bin/env python3
"""One fail-closed NON-LIVE release gate. Never migrates an operator database."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
STAGES = ('PREFLIGHT','DATABASE','MIGRATIONS','LIFECYCLE_AUTHORITY','POLICY_DOMAIN',
          'CRYPTOGRAPHIC_REPLAY','BACKEND_RUNTIME','LIVENESS','READINESS','SAME_ORIGIN_UI',
          'WORKSPACE_LAUNCH','BOOTSTRAP','SEVEN_VIEWERS','NEGATIVE_AUTH','RLS_APPEND_ONLY',
          'FRONTEND','SECRET_CHECK','GENERATED_ARTIFACT_CHECK','DIFF_CHECK')


class GateFailure(Exception):
    def __init__(self, category, detail, action):
        self.category, self.detail, self.action = category, detail, action


def execute(command, *, cwd=ROOT, env=None, timeout=300):
    try:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise GateFailure('UNKNOWN','Required process unavailable or timed out','Restore the required local dependency') from None
    return result


def require(command, **kwargs):
    result = execute(command, **kwargs)
    if result.returncode:
        raise GateFailure('UNKNOWN','Required command failed (output withheld to protect credentials)',
                          'Inspect the failing stage with its focused command')
    return result.stdout


def test_database():
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL, make_url
    supplied = os.getenv('JMORAIS_TEST_POSTGRES_URL')
    if supplied:
        url = make_url(supplied)
        if url.database != 'jmorais_test' or url.host not in ('127.0.0.1','localhost','postgres-test'):
            raise GateFailure('SECURITY','Only the explicit local jmorais_test database is accepted','Use the existing NON-LIVE Compose test service')
    else:
        require(['docker','compose','-f','docker-compose.postgres-test.yml','up','-d','--wait','postgres-test'])
        identifier = require(['docker','compose','-f','docker-compose.postgres-test.yml','ps','-q','postgres-test']).strip()
        info = json.loads(require(['docker','inspect',identifier]))[0]
        values = dict(item.split('=',1) for item in info['Config']['Env'] if '=' in item)
        port = info['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
        url = URL.create('postgresql+psycopg', username=values['POSTGRES_USER'],
            password=values['POSTGRES_PASSWORD'],host='127.0.0.1',port=int(port),database=values['POSTGRES_DB'])
    admin = create_engine(url, isolation_level='AUTOCOMMIT')
    try:
        with admin.connect() as c:
            version = c.execute(text('SHOW server_version_num')).scalar_one()
            if not version.startswith('16'):raise GateFailure('FIXTURE','PostgreSQL 16 required','Start the approved PostgreSQL 16 service')
            name = 'pilot_release_'+uuid4().hex
            c.execute(text('CREATE DATABASE '+name))
    finally:admin.dispose()
    return url.set(database=name), version


def migrate(url):
    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine
    config = Config(str(ROOT/'alembic.ini'))
    config.set_main_option('sqlalchemy.url',url.render_as_string(hide_password=False).replace('%','%%'))
    # env.py consumes this explicit test-only URL.
    previous = os.environ.get('JMORAIS_TEST_POSTGRES_URL')
    os.environ['JMORAIS_TEST_POSTGRES_URL'] = url.render_as_string(hide_password=False)
    try:command.upgrade(config,'head')
    finally:
        if previous is None:os.environ.pop('JMORAIS_TEST_POSTGRES_URL',None)
        else:os.environ['JMORAIS_TEST_POSTGRES_URL'] = previous
    engine = create_engine(url)
    try:
        with engine.connect() as c:current = MigrationContext.configure(c).get_current_heads()
        head = tuple(ScriptDirectory.from_config(config).get_heads())
        if current != head or len(head)!=1:raise GateFailure('FIXTURE','Alembic current/head mismatch','Resolve the migration gate')
        return head[0]
    finally:engine.dispose()


def run_tests(paths, evidence_dir, url=None):
    target = evidence_dir/(uuid4().hex+'.json')
    env = dict(os.environ)
    if url:env['JMORAIS_TEST_POSTGRES_URL'] = url.render_as_string(hide_password=False)
    result = execute([sys.executable,'scripts/release_pytest.py',str(target),*paths],env=env)
    report = json.loads(target.read_text()) if target.exists() else {}
    if result.returncode or report.get('exit_code') != 0 or report.get('skipped') or not report.get('passed'):
        raise GateFailure(report.get('classification','UNKNOWN'),report.get('first_failure') or 'Focused proof missing, skipped or failed',
                          'Run only the reported focused test and preserve security invariants')
    return report['passed']


def artifact_check():
    names = require(['git','ls-files','-z','--cached','--others','--exclude-standard']).split('\0')
    forbidden = []
    for name in filter(None,names):
        path = Path(name)
        if (any(part in {'node_modules','__pycache__','.pytest_cache','.venv','dist','htmlcov'} or part.endswith('.egg-info') for part in path.parts)
            or path.name in {'coverage.json','.coverage','.env'}
            or (path.name.startswith('.env.') and path.name!='.env.example')
            or path.suffix.lower() in {'.pem','.p12','.key','.dump','.sql.gz','.log','.pyc'}):
            forbidden.append(name)
    if forbidden:raise GateFailure('SECURITY','Generated/private candidate paths: '+', '.join(forbidden[:5]),'Exclude the identified artifacts without deleting user files')


def main():
    os.chdir(ROOT)
    statuses = {stage:'PENDING' for stage in STAGES}
    details = {}
    stage = 'PREFLIGHT'
    failure = None
    try:
        if sys.version_info[:2] != (3,12):raise GateFailure('FIXTURE','Python 3.12 required','Use make setup with Python 3.12')
        if not shutil.which('node'):raise GateFailure('FIXTURE','Node >=22 required','Install the project Node runtime')
        major = int(require(['node','-p','process.versions.node.split(".")[0]']).strip())
        if major<22:raise GateFailure('FIXTURE','Node >=22 required','Use the approved Node runtime')
        require([sys.executable,'-m','pip','check'])
        require([sys.executable,'-m','compileall','-q','jmoraIs','scripts'])
        statuses[stage]='PASS'
        stage='DATABASE';url,version=test_database();details['postgresql']=version;statuses[stage]='PASS'
        stage='MIGRATIONS';details['alembic']=migrate(url);statuses[stage]='PASS'
        with tempfile.TemporaryDirectory(prefix='jmorais-release-') as directory:
            evidence=Path(directory)
            groups = (
                ('LIFECYCLE_AUTHORITY',['tests/test_evidence_lifecycle_authority_postgresql.py','tests/test_governed_evidence_exact_reference_postgresql.py']),
                ('POLICY_DOMAIN',['tests/test_workspace_policy_domains_postgresql.py','tests/test_workspace_launch.py','tests/test_governed_llm_draft_exact_reference_postgresql.py','tests/test_llm_gateway.py','tests/test_llm_gateway_postgresql.py']),
                ('CRYPTOGRAPHIC_REPLAY',['tests/test_release_verifier_permissions.py','tests/test_offline_replay_verifier.py','tests/test_offline_replay_verifier_postgresql.py']),
            )
            for stage,paths in groups:
                # Fresh isolated state per subsystem; no historical database residue.
                isolated,_=test_database();migrate(isolated)
                details[stage]=run_tests(paths,evidence,isolated);statuses[stage]='PASS'
            # Build before the real process proof; use the package's exact build script.
            stage='FRONTEND'
            require(['node','scripts/build.js'],cwd=ROOT/'apps/web')
            require(['node','--test',*map(str,sorted((ROOT/'apps/web/tests').glob('*.test.js')))],cwd=ROOT/'apps/web')
            require(['node','node_modules/typescript/bin/tsc','--noEmit'],cwd=ROOT/'apps/web')
            require(['node','node_modules/eslint/bin/eslint.js','src','tests','scripts'],cwd=ROOT/'apps/web')
            statuses[stage]='PASS'
            stage='BACKEND_RUNTIME';isolated,_=test_database();migrate(isolated)
            details[stage]=run_tests(['tests/test_internal_pilot_runtime.py','tests/test_pilot_static.py'],evidence,isolated)
            for item in ('BACKEND_RUNTIME','LIVENESS','READINESS','SAME_ORIGIN_UI','WORKSPACE_LAUNCH','BOOTSTRAP','SEVEN_VIEWERS','NEGATIVE_AUTH','RLS_APPEND_ONLY'):
                statuses[item]='PASS'
        stage='SECRET_CHECK'
        require([sys.executable,'-m','pytest','-q','tests/test_release_sensitive_scan.py'])
        require([sys.executable,'scripts/scan_release_sensitive_data.py'])
        statuses[stage]='PASS'
        stage='GENERATED_ARTIFACT_CHECK';artifact_check();statuses[stage]='PASS'
        stage='DIFF_CHECK';require(['git','diff','--check']);require(['git','diff','--cached','--check']);statuses[stage]='PASS'
    except GateFailure as exc:failure=exc;statuses[stage]='FAIL'
    except Exception as exc:
        failure=GateFailure('UNKNOWN',type(exc).__name__+' (details suppressed)','Diagnose only this stage without exposing credentials')
        statuses[stage]='FAIL'
    result=dict(stages=statuses,evidence=details,first_failure=stage if failure else None,
        classification=failure.category if failure else None,detail=failure.detail if failure else None,
        next_action=failure.action if failure else 'Configure external deployment prerequisites; do not deploy on fixture credentials',
        software_release_candidate='FAIL' if failure else 'PASS')
    print('JMORAIS RELEASE CANDIDATE')
    for name,status in statuses.items():print(f'{name:.<30} {status}')
    print(json.dumps(result,sort_keys=True))
    print('SOFTWARE_RELEASE_CANDIDATE='+result['software_release_candidate'])
    return int(failure is not None)


if __name__=='__main__':raise SystemExit(main())
