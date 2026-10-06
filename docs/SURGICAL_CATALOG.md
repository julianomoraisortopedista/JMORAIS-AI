# Surgical templates, official TUSS and OPME

## Official TUSS index

`make tuss-index` downloads the latest ANS package "Padrão TISS - Representação de Conceitos
em Saúde" (https://www.ans.gov.br/arquivos/extras/tiss/) and builds
`~/.local/share/jmorais-local-pilot/reference/tuss.sqlite` (public data; SQLite FTS5) with
TUSS 22 (procedures) and TUSS 19 (materials/OPME: term, model, manufacturer, Anvisa
registration, risk class, technical name). `ZIP=path` reuses a downloaded package. Version
202609: 5,969 procedures and 892,468 materials. Expired terms are flagged and cannot be saved.
Spreadsheets are read with the standard library (`jmoraIs/reference/tuss.py`).

## Templates (Modelos de cirurgia)

`jmoraIs/application/surgical_catalog.py`, stored at
`~/.local/share/jmorais-local-pilot/catalog/procedures.json` (0600, atomic writes). A template has
TUSS procedure codes (validated against TUSS 22; official term copied), a physician
confirmation flag, regime, an OPME kit (items and quantities), suppliers mapping each kit item
to an official TUSS 19 material (term, manufacturer and Anvisa copied from the table), hospital
network packages (network, code, description, OPME included, notes) and notes.

Warnings: fewer than three suppliers, suppliers not from three different manufacturers
(CFM Res. 1.956/2010 art. 5), kit items without an official material, codes not confirmed. A
template can be used in a request only after its codes are confirmed. No technical
equivalence between suppliers is inferred; the physician chooses each material.

Knee starter templates (codes are candidates from TUSS 22 v202609, to be confirmed): total
knee arthroplasty 30726034 (kit: femoral, tibial, polyethylene insert, pulse lavage;
suppliers Johnson & Johnson, Zimmer Biomet, Amplitude without materials yet), flexion
contracture 30726280 (alt. 30726301), total arthroscopic synovectomy 30733014, distal femoral
osteotomy 30725151 (alt. 30726220), proximal tibial osteotomy 30726220 (alt. 30727162),
genicular nerve block 31403026 (alt. 31602118).

## In the request document

With a template, the request lists the official TUSS codes and terms, the kit, a table of the
three brands with TUSS 19 code, manufacturer and Anvisa, and the legal section quotes CFM
Res. 1.956/2010 arts. 1, 3, 4 and 5 (verbatim from the CFM PDF).
