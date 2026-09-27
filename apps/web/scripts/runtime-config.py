"""Emit public runtime configuration only. No deployment values are inferred."""
import json
import os
from pathlib import Path
fields = {'environment': 'JMORAIS_WEB_ENVIRONMENT', 'issuer': 'JMORAIS_WEB_OIDC_ISSUER',
          'client_id': 'JMORAIS_WEB_OIDC_CLIENT_ID', 'redirect_uri': 'JMORAIS_WEB_OIDC_REDIRECT_URI'}
config = {key: os.environ.get(env, '') for key, env in fields.items()}
config['scopes'] = os.environ.get('JMORAIS_WEB_OIDC_SCOPES', '').split()
if not all(config.values()) or config['environment'] not in ('DEVELOPMENT', 'HOMOLOGATION', 'PRODUCTION'):
    raise SystemExit('EXTERNAL OIDC CLIENT REGISTRATION = PENDING; required public configuration missing')
Path('dist/workspace-config.json').write_text(json.dumps(config), encoding='utf-8')
