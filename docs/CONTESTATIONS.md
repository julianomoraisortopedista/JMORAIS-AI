# Contestations (negativa, glosa, junta médica)

## Library (`jmoraIs/application/appeal_library.py`)

The physician's past contestations, kept on this computer (`catalog/appeals.json`, 0600,
never in the repository). Upload (`POST /api/appeals/preview`) de-identifies the file without
AI and without storing it; the physician reviews, removes anything still identifying, and
saves (`POST /api/appeals`, `confirmed: true`) with kind, procedure and outcome. Saving applies
the generic patterns again and refuses text in which labelled identifiers remain. The outcome
is updated later (`PATCH /api/appeals/{id}`). `examples()` returns up to two references for a
new draft: granted first, then partial and pending, same kind, closest procedure; refused
contestations are never used.

## Drafting (`jmoraIs/application/appeal_drafting.py`)

`POST /api/appeal/draft` (background job, polled at `GET /api/appeal/draft/{id}`): the denial
text or file is de-identified with the case identifiers and split into sentences N1..; the
model may cite only those, the confirmed facts F1.. of the open case, the procedure context
(CTX), the SBOT manual entry (SBOT) and fixed legal texts (verbatim official excerpts, plus RN
503/2022 art. 5º VI, RN 424/2017 ementa and RN 566/2022 art. 3º XIII as transcribed in the SBOT
practical guide, labelled as such). A sentence survives only if it cites valid ids and every
digit run it contains appears in the cited sources, so norm numbers, dates and scores cannot be
invented. Library examples are passed as EXEMPLO fields: format and argument only, never a
source. The page builds the contestation in the browser with the letterhead, the patient's
identification and the signature; a draft can be saved back to the library as pending.
