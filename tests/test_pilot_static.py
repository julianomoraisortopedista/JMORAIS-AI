import json
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jmoraIs.api.pilot_static import attach_workspace
from jmoraIs.api.production import ProductionStartupError


def assets(tmp_path):
    (tmp_path/'src').mkdir()
    for name in ('auth.js','client.js','main.js','view.js','style.css'):
        (tmp_path/'src'/name).write_text('/* fixture asset */')
    (tmp_path/'index.html').write_text('<main>Clinical Workspace</main>')
    return tmp_path


def test_missing_config_safe_unavailable_and_static_only(tmp_path):
    app=FastAPI();attach_workspace(app,assets(tmp_path))
    with TestClient(app) as client:
        assert client.get('/').status_code==200
        assert client.get('/src/main.js').status_code==200
        assert client.get('/workspace-config.json').status_code==503
        assert client.get('/').headers['cache-control']=='no-store'
        assert client.post('/').status_code==405
        assert client.get('/internal/api/v1/nonexistent').status_code==404
        assert client.get('/src/../../.env').status_code==404


def test_public_config_callback_and_private_fields_rejected(tmp_path):
    root=assets(tmp_path)
    config=dict(environment='PRODUCTION',issuer='https://identity.example',client_id='fixture-public',
                redirect_uri='https://workspace.example/auth/callback',scopes=['openid'])
    (root/'workspace-config.json').write_text(json.dumps(config))
    app=FastAPI();attach_workspace(app,root)
    with TestClient(app) as client:
        assert client.get('/auth/callback?code=not-logged&state=test').status_code==200
        assert client.get('/workspace-config.json').json()==config
    for changed in ({**config,'client_secret':'forbidden'},{**config,'redirect_uri':'https://workspace.example/internal/api'}):
        (root/'workspace-config.json').write_text(json.dumps(changed))
        with pytest.raises(ProductionStartupError):attach_workspace(FastAPI(),root)


def test_missing_build_fails_closed(tmp_path):
    with pytest.raises(ProductionStartupError):attach_workspace(FastAPI(),tmp_path)


def test_static_allowlist_excludes_private_files_and_symlinks(tmp_path):
    root=assets(tmp_path)
    (root/'src/.env').write_text('must-not-be-served')
    app=FastAPI();attach_workspace(app,root)
    with TestClient(app) as client:
        for path in ('/src/.env','/src/package.json','/src/%2e%2e/index.html','/.env'):
            assert client.get(path).status_code==404
    (root/'src/main.js').unlink()
    (root/'src/main.js').symlink_to(root/'src/.env')
    with pytest.raises(ProductionStartupError):attach_workspace(FastAPI(),root)


def test_factory_static_opt_in_and_failure_shutdown(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    from jmoraIs.api import production_asgi
    from jmoraIs.api.production import ProductionComposition
    composition=object.__new__(ProductionComposition)
    composition.app=FastAPI()
    closed=[]
    composition.shutdown=lambda: closed.append(True)
    monkeypatch.setitem(sys.modules,'pilot_factory_unit',SimpleNamespace(create=lambda:composition))
    monkeypatch.setenv('JMORAIS_PRODUCTION_COMPOSITION_FACTORY','pilot_factory_unit:create')
    monkeypatch.delenv('JMORAIS_WEB_DIST',raising=False)
    app=production_asgi.create()
    with TestClient(app) as client: assert client.get('/').status_code==404
    monkeypatch.setenv('JMORAIS_WEB_DIST',str(tmp_path))
    with pytest.raises(ProductionStartupError):production_asgi.create()
    assert closed==[True]
