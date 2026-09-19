# ADR 005 — Two-stage synthetic generation: records first, text second

**Status:** Accepted for the dataset prototype · Superseded in the product by
[ADR 001](001-xml-first-extraction.md) and [ADR 002](002-schema-conditioned-prompting.md)
· **Date:** 2026-09-19 (recorded; decided in the pre-Munsiq prototype)

## Context

No corpus of Saudi B2B invoices can be used for development. Real ones carry
live VAT registrations, IBANs, prices and supplier relationships; they cannot go
in a repository, and they cannot be pasted into a model prompt.

So the training and test material had to be generated. The obvious approach —
ask a model for "an invoice" and keep the prose — produces documents that read
plausibly and do not add up: a VAT line that is not 15% of the subtotal, a total
that matches neither, a VAT number of the wrong length. Data like that is worse
than useless for a system whose entire job is arithmetic and structural
validation, because it teaches the model that incoherent documents are normal
and it gives the rules nothing honest to check against.

## Decision

Generate in two stages, and never let the language model invent a number that
another number depends on.

1. **Stage one — structured records.** Generate the *facts* as structured data:
   quantities, unit prices, line amounts, subtotal, VAT, total, dates,
   identifiers. Arithmetic is computed, not generated, so every record is
   internally consistent by construction. The same stage decides the parallel
   Arabic and English field values.
2. **Stage two — rendering.** Derive the human-facing artefacts from the
   record: the bilingual instruction/response pairs in the prototype, and in
   this repository's test fixtures the printed PDF page and the UBL XML, both
   rendered from one set of numbers.

The test fixtures follow the same rule today: `build_ubl_xml` and the
text-layer PDF are two renderings of one consistent invoice — two lines totalling
45,320.00, 15% VAT of 6,798.00, payable 52,118.00. A fixture that is *wrong* is
wrong deliberately, like the demo invoice whose printed total is 21,610.00 when
the arithmetic says 21,160.00.

## Consequences

**Good.** The validation rules can be tested against documents that genuinely
add up, and against documents that genuinely do not, with the difference under
our control rather than at the mercy of a sampler. Bilingual pairs describe the
same facts instead of drifting apart. Nothing real is ever committed.

**Bad / limits.**

* Synthetic documents are cleaner than reality: real invoices have stamps,
  skewed scans, mixed scripts and creative layouts. Good numbers do not buy
  good layout diversity.
* The generator encodes an assumption of what an invoice looks like, so it
  cannot surprise us the way a real corpus would.
* Stage one's realism is bounded by what was specified — invented names and VAT
  numbers are structurally valid, not real.

## Alternatives considered

* **One-shot generation of finished documents.** Rejected: incoherent
  arithmetic, as above.
* **Anonymising real invoices.** Rejected for this project: redaction that is
  actually safe is hard, and the raw documents would still have to exist
  somewhere in the working set.

## See also

`src/data_pipeline/generate_data.py` (legacy prototype),
`docs/legacy-data-pipeline.md`, `backend/tests/fixtures.py`,
`backend/scripts/seed_demo_documents.py`.
