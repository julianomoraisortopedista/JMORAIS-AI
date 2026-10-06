# SBOT coding manual, anti-denial check, ANS deadline and consent form

## SBOT coding manual index (`jmoraIs/reference/sbot.py`)

`make sbot-index PDF=Manual-SBOT.pdf` parses the SBOT "Manual de Diretrizes de Codificação em
Ortopedia e Traumatologia" on the physician's computer into
`~/.local/share/jmorais-local-pilot/reference/sbot.json` (mounted read-only in the pilot). The
manual's content is not part of the repository. For each entry the index keeps, as printed:
ICD-10, indication, character, contraindication, exams of the indication, CBHPM codes with porte
and the superscript groups marked mutually exclusive, OPME with quantities, ICU/ward days,
comments and page. Unreadable fields stay empty. The 27/11/2025 edition yields 426 entries.

`POST /api/catalog/from-sbot` creates a surgery template from an entry: the first CBHPM code
active in the official TUSS 22 becomes the requested code, the others go to the notes (with
the exclusive groups), the OPME kit and stay are copied, the description seeds the consent
definition. Codes are never confirmed automatically.

## Anti-denial check (`jmoraIs/application/request_check.py`)

When the request uses a template linked to an SBOT entry, `/api/document` returns `checks`:
codes outside the entry (ATENCAO), two codes of one exclusive group (BLOQUEIO), ICD-10 outside
the entry's list, urgency/emergency for an elective-only entry (BLOQUEIO, per the SBOT POP),
none of the listed exam reports found in the de-identified documents, OPME items outside the kit
or above its quantity. Findings advise the physician; the request is never changed.

## ANS deadline (`jmoraIs/application/ans_deadlines.py`)

RN ANS 566/2022 art. 3º: elective admission 21 business days (XIII), day hospital 10 (XIV),
ambulatory 10 (XI), urgency/emergency immediate (XVII). Text as transcribed in the SBOT
practical guide (2025); the official ANS page could not be fetched from this computer, and the
citation says so. Holidays are not counted.

## Practice data (`jmoraIs/application/practice_documents.py`)

Physician profile (name, CRM, UF, RQE, city, contacts) and the physician's blank consent-form
model (.docx/PDF/.txt with "(inserir ...)" placeholders). A model that contains a patient's
identifiers is refused. The consent form is filled in the browser with the patient's
identification, the profile, the procedure, laterality, anesthesia, the template's definition
and the physician-written complications; unfilled placeholders are highlighted.
