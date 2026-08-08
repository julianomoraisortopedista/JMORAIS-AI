CREATE TABLE IF NOT EXISTS scientific_articles (
    id SERIAL PRIMARY KEY,
    pmid VARCHAR(20),
    doi VARCHAR(255),
    title TEXT NOT NULL,
    journal VARCHAR(255),
    year INTEGER,
    abstract TEXT,
    authors TEXT,
    source VARCHAR(64) NOT NULL DEFAULT 'pubmed',
    source_locator VARCHAR(512),
    verification_status VARCHAR(40) NOT NULL DEFAULT 'NOT_VERIFIED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (pmid),
    UNIQUE (doi)
);

CREATE INDEX IF NOT EXISTS idx_scientific_articles_doi ON scientific_articles (doi);
CREATE INDEX IF NOT EXISTS idx_scientific_articles_pmid ON scientific_articles (pmid);
CREATE INDEX IF NOT EXISTS idx_scientific_articles_title ON scientific_articles (title);

CREATE TABLE IF NOT EXISTS evidence_ledger (
    id SERIAL PRIMARY KEY,
    claim_id VARCHAR(64) NOT NULL,
    claim_text TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES scientific_articles(id) ON DELETE CASCADE,
    source_type VARCHAR(64) NOT NULL,
    source_locator VARCHAR(512),
    supporting_passage TEXT,
    pmid VARCHAR(20),
    doi VARCHAR(255),
    verification_status VARCHAR(40) NOT NULL DEFAULT 'NOT_VERIFIED',
    support_direction VARCHAR(24) NOT NULL DEFAULT 'supporting',
    confidence NUMERIC(4,2) NOT NULL DEFAULT 0.00,
    limitations TEXT,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (claim_id)
);

CREATE INDEX IF NOT EXISTS idx_evidence_ledger_source ON evidence_ledger (source_id);
CREATE INDEX IF NOT EXISTS idx_evidence_ledger_pmid ON evidence_ledger (pmid);
