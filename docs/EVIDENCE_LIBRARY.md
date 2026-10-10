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
