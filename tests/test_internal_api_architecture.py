import ast
from pathlib import Path


def test_internal_api_is_an_adapter_and_does_not_import_forbidden_raw_boundaries():
    contracts = ("app.py", "schemas.py", "security.py", "security_ports.py")
    source = "\n".join((Path("jmoraIs/api") / name).read_text() for name in contracts)
    forbidden = (
        "jmoraIs.patient_context", "import PatientContext", "import EvidencePackage", "jmoraIs.db",
        "jmoraIs.connect", "sqlalchemy", "psycopg",
    )
    assert all(item not in source for item in forbidden)
    assert "GovernedEvidence" in source and "ClinicalReasoningInput" in source


def test_api_has_no_write_routes_or_public_prefix():
    source = Path("jmoraIs/api/app.py").read_text()
    assert all(token not in source for token in ("@app.put", "@app.patch", "@app.delete"))
    posts = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
             and node.func.value.id == "app" and node.func.attr == "post"]
    expected = {"/workspace/" + name + "/resolve" for name in (
        "summary", "timeline", "evidence", "explainability", "medical-document", "human-review", "audit-defense")}
    expected.add("/workspace/bootstrap")
    suffixes = []
    for node in posts:
        assert len(node.args) == 1 and isinstance(node.args[0], ast.JoinedStr)
        prefix, suffix = node.args[0].values
        assert isinstance(prefix, ast.FormattedValue) and isinstance(prefix.value, ast.Name)
        assert prefix.value.id == "PREFIX" and isinstance(suffix, ast.Constant)
        suffixes.append(suffix.value)
    assert len(suffixes) == 8 and set(suffixes) == expected
    # Only the approved read-only exact-resolution POST routes are allowed.
    assert 'PREFIX = f"/internal/api/{API_VERSION}"' in source
    assert 'openapi_url=f"{PREFIX}/openapi.json"' in source


def test_api_authentication_is_port_driven_and_has_no_external_identity_sdk():
    source = "\n".join(path.read_text() for path in Path("jmoraIs/api").glob("*.py"))
    assert "ApiAuthenticationPort" in source and "CallerContext" in source
    assert all(name not in source.lower() for name in ("auth0", "okta", "oauth2", "boto3"))
    # "openid" is a legitimate OIDC scope value; only identity SDK imports are forbidden.
    forbidden = ("auth0", "okta", "openid", "oauth2", "oauthlib", "authlib", "jose", "keycloak", "boto3")
    for path in Path("jmoraIs/api").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(m.split(".")[0].lower().startswith(forbidden) for m in modules), path


def test_domain_and_application_do_not_depend_on_observability_infrastructure():
    files = list(Path("jmoraIs").glob("*.py")) + list(Path("jmoraIs").glob("*/domain.py")) + \
        list(Path("jmoraIs/application").glob("*.py"))
    source = "\n".join(path.read_text() for path in files)
    assert "api_observability" not in source and "api_operational_audit" not in source


def test_homologation_composition_is_explicit_and_contracts_do_not_leak_infrastructure():
    composition = Path("jmoraIs/api/homologation.py").read_text()
    schemas = Path("jmoraIs/api/schemas.py").read_text()
    assert "compose_homologation" in composition and "startup_self_check" in composition
    assert "PostgreSQLClinicalReasoningInputRepository" in composition
    assert all(name not in schemas for name in ("sqlalchemy", "Engine", "Session", "PostgreSQL"))
