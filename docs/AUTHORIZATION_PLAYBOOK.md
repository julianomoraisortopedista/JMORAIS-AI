# Authorization playbook (Convênios)

A per-installation knowledge base of what each insurer denies, why, and what worked
(`jmoraIs/application/authorization_playbook.py`, stored at `/catalog/playbook.json`, 0600,
atomic writes, never in the repository). Page **Convênios** in the platform.

- **Insurers**: route (auditing company, OPME program, second opinion, medical board),
  observed tactics, responses that worked, reviewers and arbiters with notes, and rules that
  become warnings for a request (`codes` that trigger them, or all requests).
- **Denial reasons**: prevention steps for the request, response arguments, legal source ids
  from the verified legal library and PubMed ids. Ids are references; they are re-verified
  where used (citation check, justification builder), not trusted from the playbook.
- **Cases**: insurer, date, stage, region, requested and authorized quantities per code or
  material, reasons and outcome (APROVADO, APROVADO_PARCIAL, NEGADO, REVERTIDO, MANTIDO,
  PENDENTE). No patient data: free text is refused when identifiers are detected; the
  physician updates outcomes on the page.

`GET /api/playbook/advice?insurer=&codes=` returns the matching insurer's warnings, track
record and most frequent reasons; the Pedido rápido readiness card shows them when the
insurer field is filled. The insurer name is not a patient identifier. The initial content
was built from 21 real cases (Bradesco, Amil, Mediservice, SulAmérica, Care Plus) analysed
on 2026-10-11; the seed script lives with the private data, not in the repository.

## Contestations from several files

The Contestações page accepts several files at once (insurer e-mails, letters, junta
decisions; PDF, Word, text or photo). Each file goes alone to `POST /api/appeal/extract`
(inside the 1 MB body limit; photos and scans read locally), is de-identified with the case
identifiers plus the generic rules, and is appended to the denial text for review.
`POST /api/appeal/analyze` recognises the insurer (aliases) and the denial reasons (reason
`keywords`) and shows the responses that worked, the verified norms and the PMIDs. When the
draft runs, the same analysis becomes an ESTRATEGIA field for the writer: argument lines only,
never a citable source, so every sentence still cites the denial, the case facts, the context,
SBOT or a verified legal text.

## Physician guidance and the OPME prescription

Contestações has a field "Como você quer a contestação": the physician's order and opinion
(what to concede, what to keep, tone). It is de-identified with the case identifiers and goes
to the writer as ORIENTACAO, shaping structure and emphasis but never citable.

"Receituário de OPME" (Receituário page, Pedido rápido review, Contestações) prints, on the
physician's letterhead with name, CRM and RQE, the patient's name (browser only), the
procedure and TUSS codes, the OPME items, the material specification and imaging guidance,
the justification, the equivalent brands and a table of the three suppliers (company,
product/brand, ANVISA, contact), with RN 424/2017 art. 7º I–II and CFM 2.318/2022 arts. 2º,
4º and 8º. It refuses a template without three suppliers with 11-digit ANVISA numbers.
