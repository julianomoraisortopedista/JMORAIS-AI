# Verified legal library and citation check

Drafters (contestation, coverage document) may cite only the legal sources in
`legal_basis.LEGAL_SOURCES` (official excerpts) and `appeal_drafting.SECONDARY_SOURCES`
(wording transcribed from a named secondary source, which the citation names). Added on
2026-10-10 from ANS Parecer Técnico nº 24/GEAS/GGRAS/DIPRO/2021 (OPME), as the ANS
published them: RN 424/2017 art. 7º, I and II (the physician defines type, material and
dimensions of the OPME; when asked, justifies it and offers at least three brands of
different manufacturers registered at ANVISA), RN 465/2021 art. 8º, III (materials needed
for Rol procedures are covered when registered and used per label/manufacturer) and the
ANS statement on the physician's prerogative over conduct and quantities. These are ANS
summaries, not the full official text of the resolutions.

`jmoraIs/application/legal_check.py` (`POST /api/legal/check`) finds norms cited in
physician-written or edited text (RN, Lei, Resolução CFM, RDC, ADI, Súmula) and marks each
VERIFIED when the same norm is in that library (showing its excerpt for comparison) or
NOT_VERIFIED. It checks the norm, not the wording. The panel "Citações normativas" appears in
the Pedido rápido readiness card and under each contestation draft.
