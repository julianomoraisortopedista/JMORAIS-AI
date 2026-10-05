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

## Limits

- Abstract-level appraisal only; full text and risk-of-bias are not assessed.
- Proposals and decisions are in-memory in this slice; durable persistence is pending.
- Credentials are never stored in the repository; tests use fakes and never call the API.
