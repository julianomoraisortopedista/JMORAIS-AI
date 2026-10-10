# Scientific library per surgery

Each surgery template (Modelos de cirurgia) keeps one clinical claim and the articles the
physician accepted for it (`jmoraIs/application/evidence_library.py`, stored in
`/catalog/evidence_library.json`, 0600, atomic writes, outside the repository).

**Building it** ("Montar artigos com o Claude" on the template card): the template becomes a
PICO question (`/api/question`), PubMed is searched for the last 15 years (`/api/search`), and
Claude proposes a direction with a verbatim abstract quote for up to 8 articles
(`/api/propose`). The physician accepts or rejects each one (`/api/decide`, signed with the
CRM from the profile). "Importar PMIDs/DOIs" takes identifiers found elsewhere (OpenEvidence,
OrthoEvidence); they are verified in PubMed/Crossref before classification. Those services
require a login and have no open API, so they are never queried automatically.

**Saving** (`PUT /api/library/{template_id}`): only decisions the physician made on the server
in this session (never sent by the browser) for the same claim, not rejected, with the
required fields; previous library records for the same claim are kept. Claims with patient
identifiers are refused. Up to 30 articles per surgery.

**Using it**: every request re-verifies the records through `build_justification` (abstract
unchanged since review, quote literal, PubMed/Crossref metadata VERIFIED, Vancouver from
verified metadata); anything that fails is listed as not included, with the reason. The
Pedido rápido review shows the result and the printed request gets a "Fundamentação
científica" section with direction, study type, literal quote and Vancouver references. The
detailed request (`/api/document`) also uses the library when its claim matches. Supporting,
opposing and neutral articles keep their direction; nothing is filtered by direction.

**Suppliers**: the request lists every named supplier of the template (with or without
per-item TUSS 19 materials) and the Pedido rápido refuses to assemble a request when a
template with OPME has fewer than three suppliers (CFM 1.956/2010, art. 5º).

## From the selected articles to the medical justification

**Report** (`/api/case/{id}/report` with `template_id`): the library is re-verified in the report
job and passed to the report writer as E1, E2... (reference number, verbatim quote, direction,
study type). The new section "Fundamentação científica" links the case facts (F) to the articles
(E): every sentence must cite at least one article, numbers must appear in the cited quote or
facts, and opposing or neutral articles are to be mentioned, not hidden. Cited articles become
the marker "[n]", the same numbering as the printed references (`report.science`). The
"indicação" section may cite articles too. Without a library the section stays empty.

**Pronto para o convênio** (`apps/web/src/readiness.js`, Pedido rápido review): checks what an
auditor usually requires — conservative treatment documented, imaging report, physical exam,
pain/function scale, ICD-10, supporting verified evidence (and at least one guideline,
meta-analysis or RCT), no report gaps, no SBOT blocking finding, confirmed TUSS codes, three
suppliers when there is OPME, hospital and date. Blocking items say "Ainda não envie" with the
fix; the rest strengthen the request.

**Printed request**: the report (with "[n]" markers), then "Trechos citados dos artigos" (literal
quotes with direction and study type) and "Referências bibliográficas" (Vancouver).
