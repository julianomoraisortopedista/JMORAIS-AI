-- Scientific Core v3 migration: provenance-first evidence model
-- This migration extends the baseline scientific tables to support the provenance-first core.

ALTER TABLE scientific_articles
    ADD COLUMN IF NOT EXISTS article_id UUID,
    ADD COLUMN IF NOT EXISTS pmcid VARCHAR(64),
    ADD COLUMN IF NOT EXISTS source_type VARCHAR(64) DEFAULT 'pubmed',
    ADD COLUMN IF NOT EXISTS human_review_status VARCHAR(32) DEFAULT 'DRAFT',
    ADD COLUMN IF NOT EXISTS normalized_title VARCHAR(512);

ALTER TABLE evidence_ledger
    ADD COLUMN IF NOT EXISTS pmcid VARCHAR(64),
    ADD COLUMN IF NOT EXISTS support_direction VARCHAR(24) DEFAULT 'SUPPORTING';

CREATE TABLE IF NOT EXISTS authors (
    id SERIAL PRIMARY KEY,
    author_id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    orcid VARCHAR(64),
    affiliation VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS article_authors (
    id SERIAL PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES scientific_articles(id) ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    author_order INTEGER NOT NULL DEFAULT 0,
    is_corresponding BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS mesh_terms (
    id SERIAL PRIMARY KEY,
    term VARCHAR(255) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS article_mesh_terms (
    id SERIAL PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES scientific_articles(id) ON DELETE CASCADE,
    mesh_term_id INTEGER NOT NULL REFERENCES mesh_terms(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS article_topics (
    id SERIAL PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES scientific_articles(id) ON DELETE CASCADE,
    topic VARCHAR(255) NOT NULL,
    score NUMERIC(5,4) NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS source_provenance (
    id SERIAL PRIMARY KEY,
    source_name VARCHAR(64) NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    source_locator VARCHAR(512),
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    record_hash VARCHAR(128),
    raw_payload JSONB
);

CREATE TABLE IF NOT EXISTS citations (
    id SERIAL PRIMARY KEY,
    citation_id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    article_id INTEGER NOT NULL REFERENCES scientific_articles(id) ON DELETE CASCADE,
    source_type VARCHAR(64) NOT NULL,
    rendered_vancouver TEXT,
    verification_status VARCHAR(40) NOT NULL DEFAULT 'NOT_VERIFIED',
    source_locator VARCHAR(512),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evidence_claims (
    id SERIAL PRIMARY KEY,
    claim_id VARCHAR(64) NOT NULL UNIQUE,
    claim_text TEXT NOT NULL,
    support_direction VARCHAR(24) NOT NULL DEFAULT 'SUPPORTING',
    verification_status VARCHAR(40) NOT NULL DEFAULT 'NOT_VERIFIED',
    confidence NUMERIC(4,2) NOT NULL DEFAULT 0.00,
    limitations TEXT,
    provenance_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS search_runs (
    id SERIAL PRIMARY KEY,
    search_id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    query TEXT NOT NULL,
    source VARCHAR(64) NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status VARCHAR(32) NOT NULL DEFAULT 'completed'
);

CREATE TABLE IF NOT EXISTS verification_runs (
    id SERIAL PRIMARY KEY,
    verification_id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    article_id INTEGER NOT NULL REFERENCES scientific_articles(id) ON DELETE CASCADE,
    source_type VARCHAR(64) NOT NULL DEFAULT 'pubmed',
    checks TEXT,
    overall_status VARCHAR(40) NOT NULL DEFAULT 'NOT_VERIFIED',
    notes TEXT,
    run_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
