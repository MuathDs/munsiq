# The 90-second demo

Two documents, one point: **the system knows the difference between reading and
guessing, and it shows you which one it did.**

Seed them first (see the [quickstart](../README.md#quickstart)); the script
prints both URLs, in both languages.

```bash
cd backend && .venv/Scripts/python.exe -m scripts.seed_demo_documents
```

Everything below is what these two documents actually do — screenshots of both,
in both languages, are in [`screenshots/`](screenshots/).

---

## 0:00 — Open document A, the compliant invoice

`http://localhost:3000/en/annotations/<A>`

The header says it before anything else: **ZATCA 4/4** and **Signed XML · no
AI**. This invoice carried its own UBL attachment, so no model ran on it.

The field pane summary reads **18 Verified (XML), 1 Not extracted** out of 19.
Every green badge is a value read from the signed attachment. Then say the line
that matters —

> These values were not extracted. They were read out of the XML the supplier
> cryptographically signed and filed with ZATCA. The extraction model was never
> called for this document.

The one field that is not green is the **purchase order number**, badged *Not
extracted* rather than guessed: it is not in the XML, and nobody has verified
whether it is on the page.

## 0:15 — Click a field

Click **Total (incl. VAT)**. The matching region on the page outlines in green.

The box does not mean "we trust this" — provenance does. The box means "here is
where that value is printed", so a reviewer can check the claim against the
document in one glance instead of hunting.

Scroll to the **line items**: description, quantity, unit price and amount, per
line, also from the XML — 8 cells across 2 lines. Their boxes are on the page
too: *Centrifugal pump*, `20,000.00`, `40,000.00`.

Two things deliberately have no box. The **seller name** is Arabic in the XML
(`شركة الجزيرة للصيانة الصناعية`) while the page prints the English trading
name, and the second line's description is Arabic on an English-printed page.
The value is still authoritative — it was signed — but it is not printed there,
so it gets no box rather than a wrong one.

## 0:30 — Switch to Arabic

Click **العربية**. The whole interface mirrors: the field pane moves to the
left, the document to the right, labels become Arabic — *رقم الفاتورة*, *اسم
البائع*, *الرقم الضريبي للبائع* — and the invoice number stays left-to-right,
because an identifier is not a sentence.

The page image does **not** mirror. A scanned invoice's top-left is its top-left
in either language; page geometry is the one thing in this UI that must not
follow direction.

> The labels come from the database, not the code. The same schema row that
> tells the model what to extract tells the UI what to call it, in both
> languages.

## 0:50 — Open document B, the broken one

`http://localhost:3000/en/annotations/<B>`

Invoice `EPS-2026-1187`. Different story, visible immediately:

* **Signed XML · no AI** is gone. This one says **AI · qwen2.5:7b-instruct** —
  no attachment, so the model ran (165s on this machine, CPU inference).
* All 11 badges are amber, *Extracted (AI)*, each with a **confidence bar**.
* The compliance chip reads **ZATCA 1/1**, not 4/4. Only the VAT-number checksum
  had anything to check: with no attachment there is no embedded UBL and no QR
  to decode. A check that never ran is not reported as passed.
* A red card sits at the top of the field pane: **1 finding blocks
  confirmation** — `GRAND_TOTAL_MISMATCH`, *"Subtotal (18400.00) plus VAT
  (2760.00) is 21160.00, but the stated total is 21610.00."*
* **Total (incl. VAT)** is pinned into its own *Blocking* section above
  everything else, its box on the page is red, and **Confirm** turns red with a
  count of 1.

Two digits transposed. A human eye slides over it; arithmetic does not.

Worth pointing at: the model returned `21610.0`, not the `21,610.00` printed on
the page. It normalised the number — which is exactly why its output is treated
as untrusted and checked, and why `original_value` is kept in the export.

## 1:10 — Try to confirm

Click **Confirm**. It refuses, and a banner says why, with the rule code.

> Validation here is not advisory. A document that does not add up cannot be
> signed off and pushed downstream. Fix the value and the rules re-run —
> correcting the data is what clears the block, not dismissing a warning.

Correct the total to `21160.00`. The blocker clears, the badge turns to
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
