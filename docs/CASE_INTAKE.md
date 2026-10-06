# Medical request from patient documents (Pedido médico)

Platform page **Pedido médico** (http://localhost/ after login).

1. **Identification** (name, CPF, RG, card, birth date, phone, e-mail, address, insurer)
   lives only in the browser. It is sent with each upload solely so the server can
   remove it, is never stored, and fills the printed header client-side
   (`data-ident` placeholders) — the document request itself never carries it.
2. **Documents**: text PDFs or .txt (one per request, <= 700 KB, inside the API's 1 MB
   body limit; up to 8). Images are never sent to AI; scanned PDFs without text are
   refused with guidance. History is free text.
   **Dictation**: "🎤 Ditar" (history, Rol alternatives, extra clinical text) uses the
   browser's built-in speech recognition in pt-BR (Chrome: Google's service; Safari:
   Apple's). Without support, the page points to macOS Dictation (Fn twice). Dictated
   text is de-identified like typed text; avoid saying identifiers aloud.
3. **De-identification** (`jmoraIs/application/deidentification.py`): labelled lines
   (Paciente/Nome/Beneficiário, mother, card/matrícula, birth, address), generic
   patterns (CPF, CNS, RG, phone, e-mail, CEP) and the supplied identifiers
   (accent/case-insensitive name parts, digit sequences). A final check refuses the
   text if a supplied identifier survives. Ages, exam dates, scores and findings are kept.
   The physician sees the exact de-identified text before AI processing.
4. **Consent**: an explicit "consentimento do paciente registrado (LGPD)" is required.
5. **Extraction** (`jmoraIs/application/case_intake.py`): de-identified text only, via the
   Canonical LLM Gateway (Claude, structured JSON, effort medium), as a background job
   polled by the page. Each fact must include a verbatim quote found in its source;
   otherwise it is discarded. ICD-10 codes are suggestions only.
6. **Confirmation**: the physician selects/edits facts and confirms ICD-10 codes.
7. **Request**: procedure, laterality, regime, TUSS (8 digits) and OPME (Anvisa, qty)
   entered by the physician, confirmed facts with source quotes, scientific and legal
   sections, signature block. Draft for physician review and signature.

State is per authenticated principal, in memory only, deletable (`DELETE /api/case/{id}`).
Anthropic's API does not train on API data; default retention up to 30 days (zero data
retention requires an agreement with Anthropic). Residual risk: names not supplied and
not on a labelled line (e.g. a relative mentioned in free text) can remain — review the
preview before extraction.
