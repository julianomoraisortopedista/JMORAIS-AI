from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from jmoraIs.api.security import CallerContext, CallerRole, PurposeOfUse
from jmoraIs.workbench.app import create_app
from jmoraIs.workbench.platform_auth import iam_authenticator
from tests.test_scientific_justification import NOW, Crossref
from tests.test_support_classification import CLAIM, QUOTE
from tests.test_workbench import SearchablePubMed

USERS = {
    "token-dr-a": ("dr-a", CallerRole.CLINICAL_REVIEWER, "HUMAN"),
    "token-dr-b": ("dr-b", CallerRole.CLINICAL_REVIEWER, "HUMAN"),
    "token-service": ("svc", CallerRole.INTERNAL_SERVICE, "SERVICE"),
    "token-denied": ("dr-x", CallerRole.CLINICAL_REVIEWER, "HUMAN"),
}


class Authentication:
    def __init__(self):
        self.purposes = []

    def authenticate(self, credentials, correlation_id):
        self.purposes.append(credentials.purpose)
        if credentials.bearer_token not in USERS:
            raise RuntimeError("rejected")
        caller_id, role, kind = USERS[credentials.bearer_token]
        return CallerContext(caller_id, role, PurposeOfUse.CLINICAL_REVIEW, correlation_id, "MIP-10.1",
                             principal_type=kind)


class Authorization:
    def authorize(self, caller, resource_class):
        assert resource_class == "WORKSPACE_READ"
        if caller.caller_id == "dr-x":
            raise RuntimeError("denied")


def client():
    operations = SimpleNamespace(authentication=Authentication(), authorization=Authorization())
    app = create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW,
                     authenticate=iam_authenticator(operations))
    return TestClient(app, base_url="http://localhost"), operations


def bearer(token):
    return {"Authorization": "Bearer " + token}


@pytest.mark.parametrize("headers,status", [
    ({}, 401), (bearer(""), 401), (bearer("unknown"), 401),
    ({**bearer("token-dr-a"), "X-Tenant-Id": "other"}, 403),
    ({**bearer("token-dr-a"), "X-Role": "ADMINISTRATOR"}, 403),
    ({**bearer("token-dr-a"), "X-Purpose": "INTERNAL_OPERATIONS"}, 403),
    (bearer("token-service"), 403), (bearer("token-denied"), 403),
])
def test_iam_is_mandatory_and_cannot_be_spoofed(headers, status):
    c, _ = client()
    assert c.get("/api/status", headers=headers).status_code == status


def test_standalone_token_and_page_are_not_available_in_platform_mode():
    c, operations = client()
    assert c.get("/").status_code == 404
    assert c.get("/api/status", headers={"X-Workbench-Token": "anything"}).status_code == 401
    assert c.get("/api/status", headers=bearer("token-dr-a")).status_code == 200
    assert set(operations.authentication.purposes) == {"CLINICAL_REVIEW"}


def test_work_state_is_isolated_per_physician_and_signed_with_principal():
    c, _ = client()
    saved = c.post("/api/manual", headers=bearer("token-dr-a"), json={
        "claim": CLAIM, "pmid": "26488691", "direction": "SUPPORTING", "quote": QUOTE, "reviewer": "CRM-SP 1"}).json()
    assert saved["reviewer"] == "CRM-SP 1 · dr-a"
    assert len(c.get("/api/decisions", headers=bearer("token-dr-a")).json()) == 1
    assert c.get("/api/decisions", headers=bearer("token-dr-b")).json() == []
