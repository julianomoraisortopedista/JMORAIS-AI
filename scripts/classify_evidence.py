#!/usr/bin/env python3
"""AI proposes, physician confirms: support direction of PubMed articles for one claim.

Abstracts come from PubMed; proposals go through the Canonical LLM Gateway to
Claude (Anthropic). Each proposal is shown with its verbatim quote and the
physician decides: accept, override (with reason) or reject. Only public
bibliographic data is sent; never put patient identifiers in the claim.
Decisions are printed and optionally written as JSON (`--out`); they are not yet
persisted in the database.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from jmoraIs.application.support_classification import PhysicianDecisionType, ProposalStatus, decision_record
from jmoraIs.connect.pubmed import AbstractUnavailable, PubMedConnector
from jmoraIs.application.support_classification_runtime import (
    DEFAULT_MODEL, MODEL_PRICES, build_service, credentials_configured,
)
from jmoraIs.scientific_domain import SupportDirection
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext

NOT_CONFIGURED = ("MODEL_NOT_CONFIGURED: set ANTHROPIC_API_KEY in your shell (see docs/SUPPORT_CLASSIFICATION.md). "
                  "Nothing was sent.")


def model_configured(environ=os.environ) -> bool:
    return credentials_configured(environ)


def local_tenant(reviewer: str) -> TenantContext:
    return TenantContext("local-physician", "local-org", reviewer, "CLINICIAN", "CLINICAL_DOCUMENTATION",
                         "ST-02", "corr-classify-" + uuid4().hex[:16])


def ask_decision(service, proposal, reviewer, read=input, write=print):
    write(f"\nPMID {proposal.pmid} - {proposal.source_locator}")
    write(f"Status: {proposal.status.value}")
    if proposal.status is not ProposalStatus.PENDING_PHYSICIAN_REVIEW:
        write(f"Reason: {proposal.rationale}")
        return service.decide(proposal, reviewer_id=reviewer, decision=PhysicianDecisionType.REJECT,
                              note="automatic: proposal not reviewable")
    write(f"AI proposal: {proposal.proposed_direction.value}")
    write(f'Quote: "{proposal.quote}"')
    write(f"Rationale: {proposal.rationale}")
    while True:
        answer = read("[a]ccept / [o]verride / [r]eject? ").strip().lower()
        if answer in ("a", "accept"):
            return service.decide(proposal, reviewer_id=reviewer, decision=PhysicianDecisionType.ACCEPT)
        if answer in ("r", "reject"):
            return service.decide(proposal, reviewer_id=reviewer, decision=PhysicianDecisionType.REJECT,
                                  note=read("Reason (optional): ").strip())
        if answer in ("o", "override"):
            choices = [d for d in SupportDirection if d is not proposal.proposed_direction]
            pick = read("New direction (" + "/".join(d.value for d in choices) + "): ").strip().upper()
            note = read("Reason (required): ").strip()
            if pick in {d.value for d in choices} and note:
                return service.decide(proposal, reviewer_id=reviewer, decision=PhysicianDecisionType.OVERRIDE,
                                      final_direction=SupportDirection(pick), note=note)
            write("Invalid direction or empty reason.")


def main(argv=None, *, service=None, pubmed=None, read=input, write=print, environ=os.environ) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claim", required=True, help="Specific clinical claim, in English, no patient data")
    parser.add_argument("--pmid", required=True, help="Comma list of PMIDs")
    parser.add_argument("--reviewer", required=True, help="Physician identifier (e.g. CRM)")
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODEL_PRICES))
    parser.add_argument("--out", help="Write decisions as JSON to this file")
    args = parser.parse_args(argv)
    if service is None and not model_configured(environ):
        write(NOT_CONFIGURED)
        return 2
    service = service or build_service(args.model)
    pubmed = pubmed or PubMedConnector()
    records = []
    with TenantContextBinder().bind_tenant(local_tenant(args.reviewer)):
        for pmid in dict.fromkeys(v.strip() for v in args.pmid.split(",") if v.strip()):
            try:
                abstract = pubmed.fetch_abstract(pmid)
            except AbstractUnavailable as exc:
                write(f"\nPMID {pmid}: abstract unavailable ({exc}); skipped")
                continue
            proposal = service.propose(args.claim, abstract)
            records.append(decision_record(ask_decision(service, proposal, args.reviewer, read, write)))
    if args.out:
        path = Path(args.out)
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2))
        path.chmod(0o600)
        write(f"\nSaved {len(records)} decision(s) to {path}")
    write("\nNot yet persisted in the database. Physician review remains mandatory before any external use.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
