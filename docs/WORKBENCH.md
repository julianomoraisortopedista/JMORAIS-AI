# Physician workbench (local browser UI)

```bash
make workbench          # then open http://127.0.0.1:8770/
```

Flow: 1) clinical claim + PICO search (PubMed/Crossref, MeSH shown) → 2) per article:
read the abstract, ask Claude for a proposal and confirm/override/reject, or classify
manually by pasting a verbatim abstract passage → 3) coverage facts (ANS list status,
urgency, ANS analysis, Anvisa, CRM, prior request, self-managed plan, physician's
clinical text) → 4) document: everything is re-verified, STF (ADI 7.265) requirements
are shown with their status, and the A4 document can be opened/printed to PDF or
downloaded with the Markdown text and the decisions JSON.

Security: loopback only; foreign `Host` headers rejected; per-process random token
required on every API call (no cookies/CORS); CSP, no-store, nosniff, frame denial;
dynamic text rendered with `textContent` only. Proposals and decisions live
server-side so the page cannot forge a physician decision. State is in memory —
download the decisions JSON to keep them. Do not enter patient identifiers; the
printed document has blank identification lines.

Without `ANTHROPIC_API_KEY` the AI button returns a clear message and manual
classification remains available (same verbatim-quote rule). Connectors are composed
in `scripts/workbench.py` and injected into `jmoraIs/workbench/app.py`.
