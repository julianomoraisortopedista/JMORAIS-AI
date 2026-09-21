-- ST-03: immutable, reproducible scientific evidence ledger.
-- Legacy evidence_claims/evidence_ledger remain available for transition reads only.

CREATE TABLE ledger_claims (
    claim_id VARCHAR(64) PRIMARY KEY,
    claim_text TEXT NOT NULL,
    claim_hash CHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE evidence_fragments (
    fragment_id CHAR(64) PRIMARY KEY,
    source_name VARCHAR(128) NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    source_locator VARCHAR(1024),
    exact_location VARCHAR(512),
    passage TEXT NOT NULL,
    pmid VARCHAR(20), doi VARCHAR(255), pmcid VARCHAR(64),
    payload_hash CHAR(64) NOT NULL,
    fragment_hash CHAR(64) NOT NULL UNIQUE,
    retrieved_at TIMESTAMPTZ NOT NULL,
    verification_version VARCHAR(64) NOT NULL,
    pipeline_version VARCHAR(64) NOT NULL,
    policy_version VARCHAR(64) NOT NULL,
    model_version VARCHAR(128),
    prompt_version VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE claim_supports (
    support_id CHAR(64) PRIMARY KEY,
    claim_id VARCHAR(64) NOT NULL REFERENCES ledger_claims(claim_id) ON DELETE RESTRICT,
    fragment_id CHAR(64) NOT NULL REFERENCES evidence_fragments(fragment_id) ON DELETE RESTRICT,
    support_direction VARCHAR(24) NOT NULL CHECK (support_direction IN ('SUPPORTING','OPPOSING','NEUTRAL','INCONCLUSIVE')),
    support_hash CHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (claim_id, fragment_id, support_direction)
);

CREATE TABLE ledger_events (
    event_id VARCHAR(64) PRIMARY KEY,
    claim_id VARCHAR(64) NOT NULL REFERENCES ledger_claims(claim_id) ON DELETE RESTRICT,
    event_type VARCHAR(32) NOT NULL CHECK (event_type IN ('EVIDENCE_ADDED','CORRECTION','SUPERSESSION','INVALIDATION','RETRACTION','REPROCESSING')),
    support_id CHAR(64) REFERENCES claim_supports(support_id) ON DELETE RESTRICT,
    target_support_id CHAR(64) REFERENCES claim_supports(support_id) ON DELETE RESTRICT,
    replacement_support_id CHAR(64) REFERENCES claim_supports(support_id) ON DELETE RESTRICT,
    reason TEXT,
    occurred_at TIMESTAMPTZ NOT NULL,
    previous_event_hash CHAR(64),
    event_hash CHAR(64) NOT NULL UNIQUE
);

CREATE INDEX ix_claim_supports_claim ON claim_supports(claim_id);
CREATE INDEX ix_ledger_events_claim_time ON ledger_events(claim_id, occurred_at);
CREATE INDEX ix_evidence_fragments_pmid ON evidence_fragments(pmid) WHERE pmid IS NOT NULL;
CREATE INDEX ix_evidence_fragments_doi ON evidence_fragments(doi) WHERE doi IS NOT NULL;

CREATE OR REPLACE FUNCTION reject_scientific_ledger_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Scientific Evidence Ledger is append-only: % is prohibited on %', TG_OP, TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER ledger_claims_append_only BEFORE UPDATE OR DELETE ON ledger_claims
FOR EACH ROW EXECUTE FUNCTION reject_scientific_ledger_mutation();
CREATE TRIGGER evidence_fragments_append_only BEFORE UPDATE OR DELETE ON evidence_fragments
FOR EACH ROW EXECUTE FUNCTION reject_scientific_ledger_mutation();
CREATE TRIGGER claim_supports_append_only BEFORE UPDATE OR DELETE ON claim_supports
FOR EACH ROW EXECUTE FUNCTION reject_scientific_ledger_mutation();
CREATE TRIGGER ledger_events_append_only BEFORE UPDATE OR DELETE ON ledger_events
FOR EACH ROW EXECUTE FUNCTION reject_scientific_ledger_mutation();
