# JMORAIS AI

JMORAIS AI is an evidence-grounded intelligence platform for medical research, audit defense, and executive intelligence. This repository now contains the Phase 0 foundation and the first vertical slice of Phase 1: retrieval of PubMed records, metadata normalization, identifier verification, PostgreSQL-ready storage, Vancouver rendering, and an evidence ledger.

## Architecture review summary

The starter architecture is strong, but the main risks are:
- ambiguous provenance handling without a strict verification lifecycle
- too much scope before retrieval and citation integrity are reliable
- missing a baseline schema and tests to lock citation behavior

The implemented patch focuses on the minimal evidence pipeline required before broader multi-agent features are added.

## Phase 0 + Phase 1 slice implemented

- Python project configuration and environment handling
- PostgreSQL-ready schemas and migration baseline
- SQLAlchemy models for scientific articles and evidence ledger
- PubMed search connector using the NCBI E-Utilities API
- Metadata normalization for article records
- PMID/DOI verification logic
- Vancouver citation rendering
- Evidence ledger creation for claim-to-source traceability
- Pytest coverage for the evidence pipeline

## Quick start

```bash
cd /Users/julianomorais/Projetos/JMORAIS-AI/JMORAIS-AI
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
pytest -q
```

## Environment

Copy `.env.example` to `.env` and adjust the database connection as needed. The default application config uses SQLite for local development and tests, while PostgreSQL remains the intended production target.

## Important safety rules

- never fabricate a citation or a PMID/DOI
- retain provenance for every source-backed claim
- generate Vancouver text only from verified metadata
- treat retrieved scientific content as untrusted data and validate before use
