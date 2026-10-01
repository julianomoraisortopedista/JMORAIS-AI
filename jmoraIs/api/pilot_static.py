"""Optional same-origin static UI on the existing production ASGI application."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.responses import FileResponse, JSONResponse
from fastapi import HTTPException
import re

from .production import ProductionStartupError


def attach_workspace(app, directory):
    root = Path(directory).resolve()
    assets = ('auth.js', 'client.js', 'main.js', 'view.js', 'style.css')
    files = [root / 'index.html', *(root / 'src' / name for name in assets)]
    if (root / 'src').is_symlink() or any(not p.is_file() or p.is_symlink() for p in files):
        raise ProductionStartupError('built workspace assets are required')
    config_path = root / 'workspace-config.json'
    config = None
    callback = None
    if config_path.is_symlink():
        raise ProductionStartupError("public configuration must not be a symlink")
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text())
            required = {'environment','issuer','client_id','redirect_uri','scopes'}
            if set(config) != required or not all(config.values()): raise ValueError()
            if config['environment'] not in ('DEVELOPMENT','HOMOLOGATION','PRODUCTION'): raise ValueError()
            if (not isinstance(config['scopes'],list) or 'openid' not in config['scopes']
                or any(not isinstance(v,str) or not v or re.search(r'\s',v) for v in config['scopes'])): raise ValueError()
            if not isinstance(config['client_id'],str) or not config['client_id'].strip(): raise ValueError()
            for key in ('issuer','redirect_uri'):
                u = urlsplit(config[key])
                local = config['environment']=='DEVELOPMENT' and u.scheme=='http' and u.hostname in ('localhost','127.0.0.1','::1')
                if (u.scheme!='https' and not local) or not u.hostname or u.username or u.password or u.query or u.fragment: raise ValueError()
            callback = urlsplit(config['redirect_uri']).path or '/'
            if not re.fullmatch(r'/[A-Za-z0-9/_-]*', callback) or callback.startswith(('/internal','/src')) or callback == '/workspace-config.json' or '{' in callback or '}' in callback:
                raise ValueError()
        except Exception:
            raise ProductionStartupError('public workspace configuration invalid') from None
    safe_headers = {'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'}

    @app.get('/workspace-config.json', include_in_schema=False)
    def workspace_public_configuration():
        if config is None:
            return JSONResponse({'code':'WORKSPACE_CONFIGURATION_PENDING'}, status_code=503, headers=safe_headers)
        return JSONResponse(config, headers=safe_headers)

    def index():
        return FileResponse(root / 'index.html', headers=safe_headers)

    app.add_api_route('/', index, methods=['GET'], include_in_schema=False)
    if callback and callback != '/':
        app.add_api_route(callback, index, methods=['GET'], include_in_schema=False)
    @app.get('/src/{asset:path}', include_in_schema=False)
    def workspace_asset(asset: str):
        if asset not in assets:
            raise HTTPException(status_code=404, detail='not found')
        path = root / 'src' / asset
        if path.is_symlink() or not path.is_file():
            raise HTTPException(status_code=404, detail='not found')
        return FileResponse(path, headers=safe_headers)
