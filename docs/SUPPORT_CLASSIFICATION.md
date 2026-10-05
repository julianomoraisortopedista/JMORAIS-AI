# Support classification — AI proposes, physician confirms

Module: `jmoraIs/application/support_classification.py`. Abstracts: `PubMedConnector.fetch_abstract`.

## Flow

1. `PubMedConnector.fetch_abstract(pmid)` returns the exact published abstract
   (`PublishedAbstract`) with SHA-256 hash and PubMed locator. XML with an internal
   DTD subset or entities is refused; missing abstracts fail closed.
2. `SupportClassificationService.propose(claim, abstract)` sends a versioned
   `CanonicalStructuredDTO` (`support-classification-input` v1: claim, pmid, title,
   abstract) through the Canonical LLM Gateway with mandatory human review,
   temperature 0 and the registered prompt `support-classification-v1`.
3. The output must be the governed JSON (`direction`, `quote`, `rationale`). The
   proposal is `PENDING_PHYSICIAN_REVIEW` only when `quote` (>= 20 chars) is a verbatim
   passage of the abstract; otherwise `UNGROUNDED`. Gateway refusal is `BLOCKED`.
4. `decide(...)`: an identified physician ACCEPTs, OVERRIDEs (different direction and a
   mandatory reason) or REJECTs. UNGROUNDED/BLOCKED proposals can only be rejected.
5. `register_confirmed_support(...)` is the only path into the evidence ledger: passage
   = verified quote, `exact_location=abstract`, payload hash = abstract hash, final
   physician direction, model and prompt versions. Existing package issuance and
   strict Vancouver formatting then apply unchanged.

## Limits

- Abstract-level appraisal only; full text and risk-of-bias are not assessed.
- Proposals and decisions are in-memory in this slice; durable persistence is pending.
- A real model provider requires a configured transport and credentials; none is
  configured in the repository. Tests use the gateway's mock provider only.
