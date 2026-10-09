# Medical request from patient documents (Pedido médico)

Platform page **Pedido médico** (http://localhost/ after login).

1. **Identification** (name, CPF, RG, card, birth date, phone, e-mail, address, insurer)
   lives only in the browser. It is sent with each upload solely so the server can
   remove it, is never stored, and fills the printed header client-side
   (`data-ident` placeholders) — the document request itself never carries it.
   *Pre-fill*: when files are chosen, `POST /api/case/scan` reads labelled
   identifiers (name, CPF with valid checksum, card, birth date, RG, address, e-mail,
   phone) with `detect_identifiers` — deterministic, local, no AI, nothing stored — and
   the page fills only empty fields for the physician to confirm.
2. **Documents**: PDFs, Word (.docx), .txt or photos (one per request, <= 700 KB, inside
   the API's 1 MB body limit; up to 8). History is free text.
   **Photos and scanned PDFs** (`jmoraIs/application/local_ocr.py`): the browser redraws a
   photo as a JPEG of at most 2400 px / 700 KB (dropping EXIF and location); the server
   reads it with Tesseract (Portuguese) on this machine. A PDF without a text layer is
   rendered at 300 dpi (first 10 pages) and read the same way. File type is taken from the
   content, not the name; each page has a 60 s limit; work files live in a private temporary
   directory removed after reading. Images never reach the AI: the recognised text goes
   through identifier pre-fill, de-identification and the physician preview like any other
   document. If OCR is not installed or the text is illegible the file is refused with
   guidance. OCR can misread an identifier so that it escapes removal: check the preview.
   The local pilot image installs `tesseract-ocr`, `tesseract-ocr-por` and `poppler-utils`.
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
7. **Report draft** (`jmoraIs/application/report_drafting.py`): Claude writes the
   professional report (history, conservative treatment, physical exam, imaging, surgical
   indication, OPME justification) from the confirmed facts and the stated procedure/OPME
   only. Every sentence must cite fact ids (or the procedure context) and every number in it
   must appear in the cited sources; otherwise it is dropped and counted. Missing information
   is returned as gaps (e.g. undocumented physical exam), never filled in. Sections are
   editable; the edited text becomes the request's clinical text.
8. **Request**: procedure, laterality, regime, TUSS (8 digits) and OPME (Anvisa, qty)
   entered by the physician, confirmed facts with source quotes, scientific and legal
   sections, signature block. Draft for physician review and signature.

State is per authenticated principal, in memory only, deletable (`DELETE /api/case/{id}`).
Anthropic's API does not train on API data; default retention up to 30 days (zero data
retention requires an agreement with Anthropic). Residual risk: names not supplied and
not on a labelled line (e.g. a relative mentioned in free text) can remain — review the
preview before extraction.

## One-click flow

With Claude configured, "Remover identificação e ler com o Claude" creates the case,
uploads and de-identifies each document, and starts fact extraction in one action.
"Confirmar e redigir o relatório" confirms the facts and starts the report draft for
the surgery template and laterality chosen in the documents card. The physician still
reviews facts, report and request; identification is filled into the final request only
in the browser, after that review.


## Dictated request and hospital scheduling

"O que você quer solicitar" (`jmoraIs/application/request_intake.py`, `POST /api/request/parse`)
turns a spoken or typed request ("ATJ direita, Zimmer, Hospital X, dia 20/10 às 7h, raqui,
UTI") into the surgery template, laterality, preferred supplier and hospital scheduling
(hospital, date, time, duration, anesthesia, ICU and blood reserve, notes). The text is
de-identified first; only templates and suppliers that exist in the catalog are accepted,
dates must fall within the next two years and times are normalised to HH:MM. The page fills
the form and the physician confirms. Scheduling is rendered in the request as "Agendamento
cirúrgico".

## The physician's report model

"Meu modelo de relatório" (Modelos de cirurgia page; `jmoraIs/application/report_style.py`):
an uploaded model report is de-identified (identifiers found on its labelled lines are
removed everywhere, plus the generic patterns) and shown for review without being stored.
Only after the physician confirms it has no patient data is it saved (0600 JSON, generic
patterns applied again). The report writer receives it as the `MODELO` field: it follows
its section order, titles and tone; sentences citing `MODELO` are discarded and its numbers
cannot pass the grounding check.

## Final medical report

"Relatório final com dados do paciente" assembles the edited report in the browser with
name, birth date, CPF, card number and insurer from the identification card, plus date and
signature line. The request document also carries birth date and CPF placeholders filled
locally. None of these values reach the server's AI calls.

## Pedido rápido (one click)

The "Pedido rápido" page chains: dictated request -> catalog template, laterality and
scheduling; identifiers read locally from the files; de-identified upload; fact extraction;
all quote-grounded facts and the AI's ICD-10 suggestions accepted (the review screen says so
and lets the physician edit); report drafted in the physician's saved model format;
`POST /api/case/{id}/check` (SBOT findings and ANS deadline). The review screen assembles,
in the browser, the combined "Relatório médico e solicitação de procedimento cirúrgico":
physician header from the profile, patient identification, report sections, request table
(procedure and side, ICD-10, character, regime and stay, hospital and date, anesthesia),
TUSS codes, OPME kit, suppliers per CFM 1.956/2010, SBOT reference, deadline, signature.
The report model limit is 14,000 characters.
