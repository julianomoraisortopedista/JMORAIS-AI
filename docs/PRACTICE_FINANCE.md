# Practice finance: surgeries, invoices and payments

Separate domain (`jmoraIs/practice_finance/`), separate local store (`catalog/finance.sqlite`,
0600, never in the repository), routes in `jmoraIs/workbench/finance_api.py`. Nothing here is
sent to an AI model. Amounts are integer cents.

- **Surgeries**: imported from the physician's spreadsheet (.xlsx/.csv; header row found
  automatically, columns mapped by synonyms, preview before import, duplicates by date +
  patient + procedure skipped) or added by hand.
- **Invoices (NFS-e)**: ABRASF and São Paulo XML (number, issue date, value, tomador name and
  CNPJ, discriminação); PDF read best-effort. Same number + CNPJ is not imported twice.
- **Payments**: `.eml` e-mails dragged from Mail (body lines with R$ amounts, invoice numbers
  cited, and .xlsx/.csv/.pdf attachments) or statements (.xlsx/.csv by column synonyms, .pdf by
  lines). Fingerprint (date, value, payer, reference) prevents duplicates.
- **Reconciliation** (`reconcile.py`): surgery -> invoice when the patient is named in the
  invoice description (automatic) or same hospital and value (suggestion); payment -> invoice
  when the invoice number is cited (automatic) or same payer and value (suggestion).
- **Panel**: totals (performed, invoiced, received, to invoice, to receive), month x hospital
  table, alerts: surgery without invoice after 30 days, invoice unpaid after 45 days, paid less
  than invoiced (possible glosa), payment without invoice.

Next steps: mailbox reading (IMAP with an app password the physician registers), and AI reading
of free-form statements with patient names pseudonymised against the local registry.
