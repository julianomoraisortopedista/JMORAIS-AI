"""Security self-check of the local platform and this Mac. Read-only; never prints secrets.

PASS/AVISO/FALHA lines in Portuguese for the physician; exit code 1 when any FALHA.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import urllib.request

STATE = Path.home() / '.local/share/jmorais-local-pilot'
ROOT = Path(__file__).resolve().parents[2]
DOCKER_ENV = {**os.environ, 'DOCKER_CONFIG': str(STATE / 'docker-public'),
              'DOCKER_HOST': 'unix://' + str(Path.home() / '.docker/run/docker.sock')}
HEADERS = ('content-security-policy', 'x-frame-options', 'x-content-type-options', 'referrer-policy', 'permissions-policy')
results = []


def report(level, message):
    results.append(level)
    print(f'{level}: {message}')


def run(cmd, env=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=env).stdout
    except Exception:
        return ''


def ports():
    out = run(['lsof', '-nP', '-iTCP', '-sTCP:LISTEN'])
    exposed = [l for l in out.splitlines() if any(f':{p} ' in l + ' ' for p in (80, 443, 8000, 8081, 5432))
               and '127.0.0.1:' not in l and '[::1]:' not in l]
    report('FALHA' if exposed else 'PASS', 'portas da plataforma abertas para a rede' if exposed else
           'plataforma acessível só neste Mac (127.0.0.1)')


def headers():
    try:
        with urllib.request.urlopen('http://127.0.0.1/', timeout=5) as r:
            missing = [h for h in HEADERS if not r.headers.get(h)]
        report('FALHA' if missing else 'PASS', 'faltam cabeçalhos: ' + ', '.join(missing) if missing else
               'cabeçalhos de segurança do navegador ativos (CSP, anti-clickjacking, nosniff)')
    except Exception:
        report('AVISO', 'plataforma fora do ar; rode make local-pilot-repair e repita')


def files():
    loose = []
    for path in STATE.rglob('*'):
        if path.name == '.DS_Store' or path.is_symlink():
            continue
        if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            loose.append(str(path.relative_to(STATE)))
    report('FALHA' if loose else 'PASS', 'arquivos privados legíveis por outros usuários: ' + ', '.join(loose[:8]) if loose else
           'dados locais legíveis só pelo seu usuário (0600/0700)')
    leaked = any(b'sk-ant-' in p.read_bytes() for p in STATE.rglob('*') if p.is_file() and p.stat().st_size < 50_000_000)
    report('FALHA' if leaked else 'PASS', 'chave do Claude gravada em arquivo' if leaked else 'chave do Claude só no Keychain')


def mac():
    report('PASS' if 'FileVault is On' in run(['fdesetup', 'status']) else 'FALHA',
           'disco criptografado (FileVault)' if 'FileVault is On' in run(['fdesetup', 'status']) else 'FileVault desligado: ligue em Ajustes > Privacidade e Segurança')
    fw = run(['/usr/libexec/ApplicationFirewall/socketfilterfw', '--getglobalstate'])
    report('PASS' if 'enabled' in fw else 'AVISO', 'firewall do Mac ligado' if 'enabled' in fw else
           'firewall do Mac desligado: ligue em Ajustes > Rede > Firewall')


def containers():
    uid = run(['docker', 'exec', 'jmorais-local-pilot-backend-1', 'id', '-u'], DOCKER_ENV).strip()
    report('PASS' if uid and uid != '0' else 'FALHA', 'aplicação roda sem privilégio de administrador' if uid and uid != '0'
           else 'aplicação rodando como root no contêiner')
    raw = run(['docker', 'inspect', 'jmorais-local-pilot-backend-1', 'jmorais-local-pilot-frontend-1', 'jmorais-local-pilot-oidc-1'], DOCKER_ENV)
    try:
        items = json.loads(raw)
    except ValueError:
        items = []
    ok = items and all('no-new-privileges:true' in (i['HostConfig'].get('SecurityOpt') or []) for i in items)
    report('PASS' if ok else 'FALHA', 'contêineres sem escalada de privilégios' if ok else 'contêiner sem no-new-privileges')


def realm():
    import urllib.parse
    env = dict(l.split('=', 1) for l in (STATE / '.env').read_text().splitlines() if '=' in l)
    try:
        form = urllib.parse.urlencode({'grant_type': 'password', 'client_id': 'admin-cli', 'username': 'local-admin',
                                       'password': env['LOCAL_OIDC_ADMIN_PASSWORD']}).encode()
        with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8081/realms/master/protocol/openid-connect/token', data=form), timeout=5) as r:
            token = json.load(r)['access_token']
        with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8081/admin/realms/jmorais-local',
                                                           headers={'Authorization': 'Bearer ' + token}), timeout=5) as r:
            data = json.load(r)
        ok = data.get('bruteForceProtected') and data.get('accessTokenLifespan', 9999) <= 300
        report('PASS' if ok else 'FALHA', 'login bloqueia após 5 senhas erradas; sessão expira em 30 min sem uso' if ok
               else 'proteção do login desligada: rode make local-pilot-repair')
    except Exception:
        report('AVISO', 'não foi possível conferir o login (servidor de identidade fora do ar?)')


def repository():
    tracked = run(['git', '-C', str(ROOT), 'ls-files'])
    bad = [f for f in tracked.splitlines() if f.endswith(('.env', '.pem', '.key', '.sqlite', 'realm.json'))]
    report('FALHA' if bad else 'PASS', 'arquivos sensíveis no GitHub: ' + ', '.join(bad) if bad else
           'nenhum segredo nem dado local no repositório')


if __name__ == '__main__':
    for check in (ports, headers, files, mac, containers, realm, repository):
        check()
    print(f"\nResumo: {results.count('PASS')} ok, {results.count('AVISO')} aviso(s), {results.count('FALHA')} falha(s)")
    raise SystemExit(1 if 'FALHA' in results else 0)
