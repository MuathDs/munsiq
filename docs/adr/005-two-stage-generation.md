# ADR 005 — Two-stage generation of synthetic training data

**Status:** Reconstructed, not authoritative · superseded in the product by
[ADR 001](001-xml-first-extraction.md) and [ADR 002](002-schema-conditioned-prompting.md)
· **Date:** 2026-09-20

> **Read this first.** The generator this ADR is about, `generate_data.py`, was
> never committed and is not on disk — only its compiled bytecode survived, and
> that has since been cleaned up. An earlier version of this page described its
> internals in detail (that arithmetic was "computed, not generated", for
> instance). None of that could be verified, so it has been removed. What follows
> separates what the surviving artefacts **show** from what is **inferred**. If
> you wrote the generator, please correct the inferred parts.

## Context

Real Saudi B2B documents cannot be used for development: they carry live VAT
registrations, IBANs, prices and supplier relationships, and cannot go in a
repository or a model prompt. So the fine-tuning data for the original
`munsiq-extractor` model had to be generated.

## What the surviving evidence shows

Verified on 2026-09-20 against `legacy/data/procurement_finetune.jsonl`:

* 500 records. Every one is `{"text": ..., "extracted_json": {...}}`.
* Every `extracted_json` has **exactly the same five keys** — `document_type`,
  `company_name`, `equipment_mentioned`, `total_value_sar`, `critical_dates`. One
  key set across all 500.
* `document_type` takes 10 values, **exactly 50 records each** — Purchase Order,
  Maintenance Log, Work Order, LPO, Delivery Note, RFQ, Invoice, Warranty Claim,
  Inspection Report, Service Report.
* All 500 `text` fields contain Arabic; the first is colloquial Saudi Arabic
  mixed with English terms ("centrifugal pump", "delivery date").
* The original README describes records with "parallel English and Saudi-Arabic
  fields plus a bilingual instruction/response pair".

## What is inferred

A perfectly even 10 × 50 split does not happen by sampling. It happens when the
label is **chosen first** and the text is written **from** it. So the likeliest
shape of the pipeline is two stages:

1. **Decide the structured record** — the label, including which of the ten
   document types this record is.
2. **Render the record as text** — a document in the voice of a Saudi
   procurement or maintenance user, so the JSON is ground truth for the text
   rather than a guess extracted from it.

I have not seen the code, so I do not know what stage one computed itself and
what it delegated to a model, or whether any consistency (totals that add up,
well-formed identifiers) was enforced. Treat both as unknown.

## Why that design is sound (the rationale, not a description of the code)

Generating text and then asking a model to label it makes the label only as
reliable as the labeller. Generating the label first and rendering text from it
makes the label correct by construction, which is what a supervised extraction
model needs. It also gives a balanced dataset for free.

## Consequences that ARE observable

* **Five fixed columns were baked into the weights.** This is the property that
  ended the approach: a sixth field meant regenerating data and retraining. See
  [ADR 002](002-schema-conditioned-prompting.md).
* The data is synthetic and, by these measurements, uniform: one schema, balanced
  types, always Arabic-bearing. It cannot exercise real-world layout diversity,
  scans, stamps or mixed scripts.
* Nothing in it is real, which was the point.

## The same idea, where it still lives

The product's test fixtures follow the label-first principle at small scale:
`backend/tests/fixtures.py` and `backend/scripts/make_test_invoices.py` build a
UBL attachment and the printed page from **one** set of numbers, so they agree by
construction. The deliberate errors are constructed too — the arithmetic-error
invoice is built so its total is added up from the wrong VAT, and a test pins that
exactly one rule fires. That is verified: `backend/tests/test_make_test_invoices.py`.

## See also

`legacy/README.md`, `docs/legacy-data-pipeline.md`,
`backend/tests/fixtures.py`, `backend/scripts/make_test_invoices.py`.
