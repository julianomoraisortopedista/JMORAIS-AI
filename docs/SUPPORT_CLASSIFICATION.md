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

## Running it with Claude

Model: `claude-opus-5-5` (default) or `claude-sonnet-5-5` (`--model`). Transport:
`jmoraIs/llm_gateway/anthropic_transport.py`, official `anthropic` SDK as the optional
extra `.[anthropic]` (not part of the production lock). Requests use structured JSON
output, `effort: low`, server-side refusal fallback (`fallbacks: "default"`), and no
sampling parameters. A refusal becomes a `BLOCKED` proposal; truncation, rate limits
and timeouts become gateway failures without provider message text.

One-time setup on macOS (key stored in Keychain, not in a file):

```bash
.venv/bin/python -m pip install -e '.[anthropic]'
security add-generic-password -a "$USER" -s anthropic-api-key -w
echo 'export ANTHROPIC_API_KEY="$(security find-generic-password -a "$USER" -s anthropic-api-key -w 2>/dev/null)"' >> ~/.zshrc
```

Then, in a new terminal:

```bash
make classify-evidence ARGS='--claim "Total knee replacement improves pain and function versus nonsurgical treatment in knee osteoarthritis" --pmid 26488691 --reviewer CRM-UF-000000 --out decisions.json'
```

Without credentials the command prints `MODEL_NOT_CONFIGURED` and sends nothing.

## Justification draft

`jmoraIs/application/scientific_justification.py`, command:

```bash
make build-justification ARGS='--decisions decisions.json --out justificativa.md'
```

Each confirmed decision is re-verified before use: same abstract SHA-256, quote still
verbatim, publication still VERIFIED through the PubMed/Crossref pipeline
(`issue_trusted_publications` returns each package with the exact record it is bound
to), and Vancouver text only from `StrictVancouverFormatter`. Supporting, opposing,
neutral and inconclusive evidence are all listed; rejected, changed, unverified or
duplicate items appear under "Não incluídos" with the reason. No model-generated
prose and no patient data enter the draft; it requires physician review and signature.

## Legal section and printable document

`jmoraIs/application/legal_basis.py` holds verbatim excerpts checked against official
sources on 2026-10-05 (Planalto: Lei 9.656/1998 art. 10 §§ 12-13 and art. 35-C, CDC
art. 47; STJ: Súmula 608; CNJ guide: ADI 7.265 thesis and the five cumulative
requirements). Their hashes are pinned in tests; re-verify at the source before editing.
From the physician's coverage facts (`--procedure --rol --ans-analysis --urgency
--no-rol-alternative --anvisa --crm --prior-request --autogestao`) it assembles fixed
paragraphs and, outside the ANS list, reports each STF requirement as atendido /
pendente / não atendido. Requirement 4 is evaluated from the confirmed supporting
references whose PubMed publication type is randomized trial, systematic review or
meta-analysis. `--html` writes an A4 document (print to PDF) with blank identification
lines, the physician's clinical text verbatim, evidence, legal section, references and
a signature block. All values are HTML-escaped. Legal review is still recommended.

## Limits

- Abstract-level appraisal only; full text and risk-of-bias are not assessed.
- Proposals and decisions are in-memory in this slice; durable persistence is pending.
- Credentials are never stored in the repository; tests use fakes and never call the API.
