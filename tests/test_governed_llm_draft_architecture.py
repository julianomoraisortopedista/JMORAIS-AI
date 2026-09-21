from pathlib import Path
ROOT=Path(__file__).parents[1]/"jmoraIs"
def test_draft_is_separate_bounded_context_and_gateway_does_not_persist_content():
    assert (ROOT/"governed_llm_draft"/"domain.py").exists()
    gateway_persistence=(ROOT/"llm_gateway"/"persistence.py").read_text()
    assert "reviewable_content_hash" in gateway_persistence
    assert "reviewable_content" not in gateway_persistence.replace("reviewable_content_hash","")
    assert "GovernedLLMDraft" not in (ROOT/"llm_gateway"/"domain.py").read_text()
def test_domain_has_no_sqlalchemy_provider_or_reviewer_dependencies():
    domain=(ROOT/"governed_llm_draft"/"domain.py").read_text().casefold()
    for forbidden in ("sqlalchemy","provideradapter","humanreviewservice","reviewerrepository","evaluation"):
        assert forbidden not in domain
def test_draft_context_has_ports_and_postgresql_adapter_but_no_provider_call():
    ports=(ROOT/"governed_llm_draft"/"ports.py").read_text();persistence=(ROOT/"governed_llm_draft"/"persistence.py").read_text();application=(ROOT/"governed_llm_draft"/"application.py").read_text()
    assert "GovernedLLMDraftRepository" in ports and "GovernedLLMDraftQueryPort" in ports
    assert "PostgreSQLGovernedLLMDraftRepository" in persistence
    assert "ProviderAdapter" not in application and ".invoke(" not in application
    assert "evaluation" not in persistence+application
def test_lifecycle_is_owned_by_draft_context_without_human_review_or_mutation_api():
    lifecycle=(ROOT/"governed_llm_draft"/"lifecycle.py").read_text();ports=(ROOT/"governed_llm_draft"/"ports.py").read_text();domain=(ROOT/"governed_llm_draft"/"domain.py").read_text()
    assert "GovernedLLMDraftLifecycleEvent" in domain and "GovernedLLMDraftLifecycleRepository" in ports
    assert "ReviewerIdentity" not in lifecycle and "ProviderAdapter" not in lifecycle and "clinical reasoning" not in lifecycle.casefold()
    assert "def update" not in ports and "def delete" not in ports and "evaluation" not in lifecycle
