CREATE TABLE IF NOT EXISTS clinical_decisions (
    id SERIAL PRIMARY KEY,
    condition TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    confidence NUMERIC(4,2) NOT NULL DEFAULT 0.00,
    evidence_strength VARCHAR(16) NOT NULL DEFAULT 'limited',
    reasoning TEXT NOT NULL,
    supporting_claims TEXT,
    caution TEXT,
    source_ids TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
