# The 90-second demo

Two documents, one point: **the system knows the difference between reading and
guessing, and it shows you which one it did.**

Seed them first (see the [quickstart](../README.md#quickstart)); the second script
prints both URLs, in both languages.

```bash
cd backend
.venv/Scripts/python.exe -m scripts.seed_demo
.venv/Scripts/python.exe -m scripts.seed_demo_documents
```

Everything below is what these two documents actually do. Screenshots are in
[`screenshots/`](screenshots/); every one shows synthetic invoices.

---

## 0:00 — Start on the dashboard

`http://localhost:3000` redirects to `/ar/dashboard` (or to the language you last
used). Switch with the link at the bottom of the sidebar.

Every number on it is computed from the data, and a card the data cannot support is
not shown at all. With the two seed documents plus two of the generated test
invoices uploaded (the Arabic invoice and the QR receipt, as in the screenshot)
it reads **4 processed**, **4 awaiting review (1 blocked by validation)** and
**1 of 4 read from signed XML**. There is no *extraction accuracy* card: it only
appears once an invoice has been confirmed, rather than showing a dash.

> The sidebar shows the real organization, its VAT number included. The prototype
> this shell came from said "Jordan Diaz · Finance Ops".

Point at the table: each row says where its values came from — *Signed XML* or
*AI ·* and the model's name — and what state it is in. Click the row for document A.

## 0:15 — Document A, the compliant invoice

The header says it before anything else: **ZATCA 4/4** and one chip per source
with the fields it filled — **ZATCA XML · 18**, with *QR code*, *AI* and
*Derived* dimmed at 0. This invoice carried its own UBL attachment, so no model
ran on it.

The field pane summary reads **18 Verified (XML), 1 Not extracted** out of 19.
Every green badge is a value read from the signed attachment:

> These values were not extracted. They were read out of the XML the supplier
> cryptographically signed and filed with ZATCA. The extraction model was never
> called for this document.

The one field that is not green is the **purchase order number**, badged *Not
extracted* rather than guessed: it is not in the XML, and nobody has verified
whether it is on the page.

Click **Total (incl. VAT)**. The matching region on the page outlines in green.
The box does not mean "we trust this" — provenance does. The box means "here is
where that value is printed". Scroll to the **line items** (8 cells across 2
lines, also from the XML); their boxes are on the page too.

Two things deliberately have no box. The **seller name** is Arabic in the XML while
the page prints the English trading name, and the second line's description is
Arabic on an English page. The value is still authoritative — it was signed — but
it is not printed there, so it gets no box rather than a wrong one.

## 0:40 — Switch to Arabic

Click **العربية**. The whole interface mirrors: the field pane moves to the left,
the document to the right, labels become Arabic — *رقم الفاتورة*, *اسم البائع*,
*الرقم الضريبي للبائع* — and the invoice number stays left-to-right, because an
identifier is not a sentence. The page image does **not** mirror: an invoice's
top-left is its top-left in either language.

> The labels come from the database, not the code. The same schema row that tells
> the model what to extract tells the UI what to call it, in both languages.

## 0:55 — Document B, the broken one

Back on the dashboard, click the *Blocked* row: invoice `EPS-2026-1187`.

* The chips have flipped: **AI · 11**, and *ZATCA XML* dimmed at 0. No
  attachment, so the model ran.
* All 11 badges are amber, *Extracted (AI)*, each with a **confidence bar**.
* The compliance chip reads **ZATCA 1/1**, not 4/4. Only the VAT-number format
  check had anything to check: with no attachment there is no embedded UBL and
  no QR to decode. A check that never ran is not reported as passed.
* A red card sits at the top of the field pane: **1 finding blocks
  confirmation** — `GRAND_TOTAL_MISMATCH`, *"Subtotal (18400.00) plus VAT
  (2760.00) is 21160.00, but the stated total is 21610.00."*
* **Total (incl. VAT)** is pinned into its own *Blocking* section above everything
  else, its box on the page is red, and **Confirm** turns red with a count of 1.

Two digits transposed. A human eye slides over it; arithmetic does not.

Worth pointing at: the model returned `21610.0`, not the `21,610.00` printed on the
page. It normalised the number — which is exactly why its output is treated as
untrusted and checked, and why `original_value` is kept in the export.

## 1:10 — Try to confirm

Click **Confirm**. It refuses, and a banner says why, with the rule code.

> Validation here is not advisory. A document that does not add up cannot be signed
> off and pushed downstream. Fix the value and the rules re-run — correcting the
> data is what clears the block, not dismissing a warning.

Correct the total to `21160.00`. The blocker clears, the badge turns to
*Corrected*, and **Confirm** goes through.

## 1:25 — Export

In the workspace, **Export** sits next to **Confirm**. Before confirmation it is
disabled and its tooltip says why; once the invoice is confirmed it offers Excel,
CSV and JSON, and after a download the badge turns to **Exported**.

Open **History**. The confirmed and exported rows carry **JSON · XLSX · CSV** links
and a checkbox; the others do not, because only a confirmed annotation leaves the
system. Tick both and **Export 2 to Excel** downloads one workbook (an Invoices
sheet and a Line Items sheet). Every field of a single export comes
back with `value`, `source`, `confidence`, `bbox`, `reviewed_by` and
`original_value` — so a downstream system can see that the total was a model
reading that a human overrode, and what it said before.

All three formats are rendered from one contract, `MunsiqInvoiceV1`, so they
cannot disagree. Asking the API for an unconfirmed document is a 409, in Arabic
and English.

---

## Optional: upload your own

Generate eight varied invoices and drop them on **Batch Upload**:

```bash
cd backend && .venv/Scripts/python.exe -m scripts.make_test_invoices
```

The script prints what each should trigger. The two with a signed UBL are read
without the model; the other six need Ollama running, and the two receipts
among them get five fields from the ZATCA QR printed on the page. Progress while a
file uploads is measured from the browser; after that a row shows an elapsed timer
(the pipeline reports no percentages). Drop the same file twice and the second
answers "Already uploaded — this is the existing document" instead of crashing.

---

## The three sentences to close on

1. A compliant Saudi invoice already contains its own answer — signed — and this
   system reads it instead of guessing at a picture of it.
2. Every value says where it came from and how much that origin is worth trusting,
   all the way through to the export.
3. The database enforces tenant isolation, and there is a negative control proving
   the test that says so is not vacuous.
