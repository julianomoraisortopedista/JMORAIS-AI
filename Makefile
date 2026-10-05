PYTHON312 ?= python3.12
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python

.PHONY: setup verify-python test coverage hygiene security-tools supply-chain-local

setup:
	@command -v "$(PYTHON312)" >/dev/null 2>&1 || { \
		echo "Python 3.12 is required. Install it or run make setup PYTHON312=/path/to/python3.12" >&2; \
		exit 1; \
	}
	@"$(PYTHON312)" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else "Python 3.12.x is required")'
	@"$(PYTHON312)" -m venv "$(VENV)"
	@"$(VENV_PYTHON)" -m pip install -e '.[dev]'
	@$(MAKE) verify-python

verify-python:
	@test -x "$(VENV_PYTHON)" || { echo "Missing .venv; run make setup" >&2; exit 1; }
	@"$(VENV_PYTHON)" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else "The project virtual environment must use Python 3.12.x")'
	@"$(VENV_PYTHON)" --version

test: verify-python
	@"$(VENV_PYTHON)" -m pytest -q

coverage: verify-python
	@"$(VENV_PYTHON)" -m pytest -q --cov=jmoraIs --cov-report=term --cov-fail-under=90

hygiene: verify-python
	@"$(VENV_PYTHON)" scripts/check_source_hygiene.py
	@git diff --check

security-tools: verify-python
	@"$(VENV_PYTHON)" -m pip install --require-hashes -r requirements-security.lock

supply-chain-local: security-tools
	@mkdir -p artifacts
	@"$(VENV_PYTHON)" -m pip_audit --require-hashes -r requirements-production.lock --strict -f json -o artifacts/pip-audit.json
	@"$(VENV)/bin/bandit" -r jmoraIs scripts --severity-level medium --confidence-level medium -f json -o artifacts/bandit.json
	@"$(VENV_PYTHON)" scripts/scan_release_sensitive_data.py
	@"$(VENV)/bin/cyclonedx-py" requirements requirements-production.lock --output-format JSON --output-file artifacts/python-sbom.cdx.json --validate

.PHONY: release-candidate
release-candidate:
	@"$(VENV_PYTHON)" scripts/release_candidate.py

.PHONY: pilot-check pilot-up pilot-status pilot-down
pilot-check:
	@"$(VENV_PYTHON)" scripts/pilot.py check
pilot-up:
	@"$(VENV_PYTHON)" scripts/pilot.py up $(PILOT_FLAGS)
pilot-status:
	@"$(VENV_PYTHON)" scripts/pilot.py status $(PILOT_FLAGS)
pilot-down:
	@"$(VENV_PYTHON)" scripts/pilot.py down

.PHONY: pilot-link-physician pilot-create-launch
pilot-link-physician:
	@"$(VENV_PYTHON)" -m scripts.pilot_admin link-physician $(PILOT_FLAGS)
pilot-create-launch:
	@"$(VENV_PYTHON)" -m scripts.pilot_admin create-launch $(PILOT_FLAGS)

.PHONY: local-pilot-up local-pilot-down local-pilot-proof
local-pilot-up:
	@$(VENV_PYTHON) -m deploy.local.control up
local-pilot-down:
	@$(VENV_PYTHON) -m deploy.local.control down
local-pilot-proof:
	@$(VENV_PYTHON) -m deploy.local.control proof

.PHONY: evidence-search
# Read-only PubMed + Crossref discovery; candidates only, never patient data. Usage: make evidence-search Q="..."
evidence-search: verify-python
	@test -n "$(Q)$(ARGS)" || { echo 'Usage: make evidence-search Q="question" or ARGS="--population ... --intervention ..."' >&2; exit 2; }
	@"$(VENV_PYTHON)" scripts/evidence_search.py $(if $(Q),"$(Q)") $(ARGS)

.PHONY: classify-evidence
# AI proposes, physician confirms (Claude via the Canonical LLM Gateway). Usage:
# make classify-evidence ARGS='--claim "..." --pmid 26488691 --reviewer CRM-UF-000000'
classify-evidence: verify-python
	@test -n "$(ARGS)" || { echo 'Usage: make classify-evidence ARGS="--claim ... --pmid ... --reviewer ..."' >&2; exit 2; }
	@"$(VENV_PYTHON)" scripts/classify_evidence.py $(ARGS)
