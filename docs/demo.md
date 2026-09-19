# The 90-second demo

Two documents, one point: **the system knows the difference between reading and
guessing, and it shows you which one it did.**

Seed them first (see the [quickstart](../README.md#quickstart)); the script
prints both URLs, in both languages.

```bash
cd backend && .venv/Scripts/python.exe -m scripts.seed_demo_documents
```

---

## 0:00 — Open document A, the compliant invoice

`http://localhost:3000/en/annotations/<A>`

The header says it before anything else: **ZATCA 4/4** and **Signed XML · no
AI**. This invoice carried its own UBL attachment, so no model ran on it.

Point at the field list: every badge is green, *Verified (XML)*. Then say the
line that matters —

> These values were not extracted. They were read out of the XML the supplier
> cryptographically signed and filed with ZATCA. The extraction model was never
> called for this document.

## 0:15 — Click a field

Click **Total (incl. VAT)**. The matching region on the page outlines in green.

The box does not mean "we trust this" — provenance does. The box means "here is
where that value is printed", so a reviewer can check the claim against the
document in one glance instead of hunting.

Scroll the field list to the **line items**: description, quantity, unit price
and amount, per line, also from the XML. One is Arabic (`صمام كروي 6 انش`) in a
document whose page is printed in English.

## 0:30 — Switch to Arabic

Click **العربية**. The whole interface mirrors: the field pane moves to the
left, the document to the right, labels become Arabic — *رقم الفاتورة*, *اسم
البائع* — and the invoice number stays left-to-right, because an identifier is
not a sentence.

The page image does **not** mirror. A scanned invoice's top-left is its top-left
in either language; page geometry is the one thing in this UI that must not
follow direction.

> The labels come from the database, not the code. The same schema row that
> tells the model what to extract tells the UI what to call it, in both
> languages.

## 0:50 — Open document B, the broken one

`http://localhost:3000/en/annotations/<B>`

Different story, visible immediately:

* **Signed XML · no AI** is gone — this one says **AI · qwen2.5:7b-instruct**.
  No attachment, so the model ran.
* Badges are amber, *Extracted (AI)*, each with a **confidence bar**.
* A red card sits at the top of the field pane: **GRAND_TOTAL_MISMATCH** —
  *Subtotal (18,400.00) plus VAT (2,760.00) is 21,160.00, but the stated total
  is 21,610.00.*
* The offending field is pinned above everything else, its box on the page is
  red, and the ZATCA chip is no longer 4/4.

Two digits transposed. A human eye slides over it; arithmetic does not.

## 1:10 — Try to confirm

Click **Confirm**. It refuses, and says why in a banner with the rule codes.

> Validation here is not advisory. A document that does not add up cannot be
> signed off and pushed downstream. Fix the value and the rules re-run —
> correcting the data is what clears the block, not dismissing a warning.

Correct the total to `21,160.00`. The blocker clears, the badge turns to
*Corrected*, and **Confirm** goes through.

## 1:25 — Export

```bash
curl "http://localhost:8000/api/v1/annotations/<B>/export?format=json"
```

Every field comes back with `value`, `source`, `confidence`, `bbox`,
`reviewed_by` and `original_value` — so a downstream system can see that the
total was a model reading that a human overrode, and what it said before.

`format=xlsx` gives the same data as two sheets, Invoice and Line Items;
`format=csv` the same rows again. All three are rendered from one contract,
`MunsiqInvoiceV1`, so they cannot disagree.

Try it against document A before confirming it and the API refuses, in Arabic
and English: only a confirmed annotation leaves the system.

---

## The three sentences to close on

1. A compliant Saudi invoice already contains its own answer — signed — and this
   system reads it instead of guessing at a picture of it.
2. Every value says where it came from and how much that origin is worth
   trusting, all the way through to the export.
3. The database enforces tenant isolation, and there is a negative control
   proving the test that says so is not vacuous.
