# Deterministic validation (Phase 5)

The module that makes extraction trustworthy. A language model produces a
plausible answer; these rules decide whether it is an arithmetically and legally
coherent one.

Nothing here calls a model, touches the network, or reads the database. Every
rule is a pure function over a `ValidationContext`, so the whole rule set runs
in about two seconds with no fixtures.

## The rule contract

```python
@rule(code, severity, message_ar, message_en)
def some_rule(ctx: ValidationContext) -> list[RuleResult] | None: ...
```

* returns `[]` — checked, and it passed
* returns `[RuleResult(...)]` — one finding per problem
* returns `None` — **not applicable**. A scan has no QR to compare against; a
  credit note has no positive-amount requirement.

"Not applicable" is deliberately distinct from "passed". Recording a scan as
having passed a QR check it was never subject to would be a lie in the data, and
the compliance panel would show a green tick for something never verified.

Passing results *are* persisted. The panel needs to distinguish "this check ran
and succeeded" from "this check never ran".

## The rules

### Arithmetic — `rules/arithmetic.py`

| Code | Severity | Check |
| --- | --- | --- |
| `LINE_TOTAL_MISMATCH` | error | Σ(quantity × unit price) = subtotal |
| `LINE_ITEM_PRICE_MISMATCH` | warning | each line's amount = its quantity × unit price |
| `VAT_CALC_MISMATCH` | error | subtotal × rate = VAT amount |
| `GRAND_TOTAL_MISMATCH` | error | subtotal + VAT = total |
| `NEGATIVE_AMOUNT` | error | no negative amounts unless it is a credit note |
| `SUBTOTAL_EQUALS_TOTAL` | warning | subtotal equals the total with no VAT stated — likely a tax-inclusive total copied into the wrong field |

All comparisons use `Decimal` with explicit `quantize` and a one-halala
tolerance. **Never float.** `0.1 + 0.2 != 0.3` in binary floating point, and a
validation engine that flickers between pass and fail on rounding is worse than
no engine at all.

Line-item rules return `None` when no line items were extracted — the Phase 3+4
schema does not request them, so these fire only for documents parsed from UBL.

### ZATCA — `rules/zatca.py`

| Code | Severity | Check |
| --- | --- | --- |
| `TRN_FORMAT` | error | seller and buyer VAT numbers pass `validate_trn` |
| `TRN_TAX_TYPE_UNEXPECTED` | warning | a well-formed VAT number whose last two digits are not '03' |
| `VAT_CATEGORY_VALID` | error | category is S, Z, E or O |
| `VAT_RATE_CONSISTENT` | error | S ⇒ 15%, Z and E ⇒ 0% |
| `INVOICE_TYPE_THRESHOLD` | warning | simplified invoice at or above SAR 1,000 |
| `QR_TOTAL_MATCH` | error | QR TLV tags 4 and 5 agree with the extracted totals |
| `SEQUENCE_FIELDS_PRESENT` | warning | standard invoices carry ICV and PIH |

`INVOICE_TYPE_THRESHOLD` is a warning, not an error: the threshold governs which
document the *supplier* should have issued. That is their compliance problem,
not a reason to stop the buyer booking the invoice.

`TRN_FORMAT` (renamed from `TRN_CHECKSUM`) checks only what is public and
stable — 15 digits, starting and ending with 3. An earlier version also
required the 11th digit (the first of three BRANCH digits, 0 for a head
office) to be '1', which rejected most real Saudi companies; there is no
published check-digit algorithm to verify beyond the shape. `validate_trn` in
`app/services/ubl.py` has the full reasoning.

### Provenance — `rules/provenance.py`

| Code | Severity | Check |
| --- | --- | --- |
| `XML_PDF_MISMATCH` | error | a field's signed XML value disagrees with the model's reading |
| `QR_MODEL_MISMATCH` | warning | a field decoded from the ZATCA QR on the page disagrees with the model's reading |
| `OCR_SUBSTRING_MISSING` | error | every numeric value appears in the page text |
| `ARABIC_ENCODING_SUSPECT` | warning | PDF renders Arabic but XML party names are empty or mojibake |
| `TEXT_LAYER_FRAGMENTED` | warning | the page's Arabic words look cut apart (many single letters, none starting with the definite article) |

**`OCR_SUBSTRING_MISSING` is the primary anti-hallucination guard.** A model will
happily produce a well-formed, plausible, wholly invented number. The one thing
it cannot do is make that number appear on the page.

Both sides are normalized before comparison, so Arabic-Indic digits, thousands
separators and invisible format characters do not raise false alarms. A second
pass compares digits only, so a page printing `52,118.00` against a model
returning `52118.00` is a formatting difference, not a fabrication. A third
compares numbers as Decimals, so `2.30` against a page printing `2.3` is the
same amount.

Four sources are exempt. Values from the signed UBL were read from an
attachment, not the rendered page, and a compliant invoice can legitimately
carry a value in its XML that is not printed on its face. Values decoded from
the ZATCA QR (`qr`) are the same kind of authority: the QR is data the supplier
encoded, and may format an amount differently from the printed text. A
reviewer's correction has authority the model does not. And a `computed`
value — a receipt's subtotal derived as total − VAT (`extraction/totals.py`,
or from the QR's own total and VAT in `extraction/qr_values.py`) — is printed
nowhere by construction; its two inputs are checked in its place.

**The QR and the model.** On a page with no embedded XML, the pipeline decodes
the ZATCA QR from the rendered page (`services/qr.py`, OpenCV, no model) and
its five fields — seller name, seller VAT number, date, total, VAT — replace
the model's reading, which is kept as `extracted_fields.model_value`.
`QR_MODEL_MISMATCH` compares the two. It is a warning, not an error like
`XML_PDF_MISMATCH`: the QR value is used either way, and a disagreement means
the model misread the page or the page and the QR disagree — worth a look,
not a reason to refuse confirmation. Dates compare as dates, so a model's
`10/02/2026` agrees with a QR timestamp of `2026-02-10T09:30:00Z`. Text in two
scripts is not compared at all: the QR carries the seller's Arabic legal name,
a bilingual page often prints an English trading name too, and the model
returning that one is a translation, not a misread.

Both mismatch rules read the stored `model_value`, so they are recomputed on
every revalidation like every other rule. (Before `model_value` was stored, a
correction to any field dropped an XML disagreement, because there was nothing
left to compare against.)

**Amounts are compared as Decimals throughout.** Arithmetic and QR checks
always were; `engine.same_value` now does the same for `XML_PDF_MISMATCH` and
for the extraction runner's own mismatch check, so `2.3` and `2.30` never
disagree. A non-amount field (an invoice number) is still compared as text:
`0012` and `12` are different invoices.

### Completeness — `rules/completeness.py`

| Code | Severity | Check |
| --- | --- | --- |
| `REQUIRED_FIELD_MISSING` | warning | every field the schema marks `required` has a non-blank value — one finding per missing field |

A null is a correct answer for an optional field and is kept as a negative
example. For a required field it is never settled, so this moves the field from
`auto_validated` to `review_suggested` (amber) wherever the rules run: the
pipeline and every revalidation. It reads `required` from the annotation's own
schema, the same way the pipeline does, and does not depend on the page — the
silent-miss check in `extraction/labels.py` only catches a null whose label is
printed and recognised, and a real invoice labelled its subtotal with a generic
word that no subtotal synonym can safely include. A warning, not an error: a
field that genuinely is not on the document can still be confirmed, after a
person has looked.

## Blocking and confirmation

A rule with `severity=error` that fails sets the related field's
`validation_state` to `blocking`, and its code lands in `annotations.blockers`
so the UI can explain *why* a document was not automated.

`POST /api/v1/annotations/{id}/confirm` refuses with **409** while any blocking
finding is unresolved, returning every blocker with both messages so a reviewer
fixes them in one pass rather than one at a time.

The blocker set is **recomputed from `validation_results` on every call**, never
read from the cached `annotations.blockers` list. Fixing the data and re-running
validation is what clears a block; editing the cached list does not.

**Page-level findings** (`OCR_SCRIPT_UNSUPPORTED`, `OCR_ENGINE_UNAVAILABLE`,
`PAGE_TEXT_EMPTY`) come from `validation/page_findings.py`, which the pipeline
and revalidation share. An unreadable-script page blocks only when nothing else
in the document is readable or a required field is still missing; otherwise it
warns. Revalidation (`services/revalidate.py`, run after every correction)
replaces every finding it can recompute from stored state — rules and page
findings, re-judged under today's logic — and keeps the two it cannot:
`SUSPICIOUS_DOCUMENT_CONTENT` and `PIPELINE_FAILED`, which need the model run's
own output.

## Bilingual messages

Every rule carries Arabic and English. The Arabic is written, not
machine-translated, and findings interpolate the actual values — "the totals do
not add up" is far less useful to a reviewer than naming both numbers:

> المجموع قبل الضريبة (45000.00) مضافاً إليه الضريبة (6750.00) يساوي 51750.00، بينما الإجمالي المذكور هو 99999.00.

> Subtotal (45000.00) plus VAT (6750.00) is 51750.00, but the stated total is 99999.00.

## Coverage

Measured 2026-09-30, `pytest --cov=app/services/validation --cov-branch` over
`test_validation_rules.py`, `test_validation_context.py`,
`test_page_findings.py` and `test_qr.py` (165 tests):

```
Name                                            Stmts   Miss Branch BrPart  Cover
---------------------------------------------------------------------------------
app/services/validation/__init__.py                 4      0      0      0   100%
app/services/validation/context.py                 33      0      4      0   100%
app/services/validation/engine.py                 196      0     28      0   100%
app/services/validation/page_findings.py           32      0      4      0   100%
app/services/validation/rules/__init__.py           3      0      0      0   100%
app/services/validation/rules/arithmetic.py        93      0     46      0   100%
app/services/validation/rules/completeness.py      13      0      6      0   100%
app/services/validation/rules/provenance.py       122      0     62      0   100%
app/services/validation/rules/zatca.py            105      0     54      0   100%
---------------------------------------------------------------------------------
TOTAL                                             601      0    204      0   100%
```

Statement *and* branch coverage, since a rule's value is entirely in its edge
cases. Plus 11 HTTP tests on the confirm endpoint, including that another
tenant cannot confirm your annotation.

## Known ambiguity: standard vs simplified

`InvoiceTypeCode/@name` is a seven-character string. We read the first two
characters as a subtype — `01` standard, `02` simplified — because that is what
ZATCA's own sample invoices carry.

A second reading is in circulation that treats all seven characters as
independent binary flags, making `1000000` standard and `0100000` simplified.
Under that reading, every value inverts.

This affects `INVOICE_TYPE_THRESHOLD` and `SEQUENCE_FIELDS_PRESENT` only — both
warnings, so a wrong reading cannot block a legitimate invoice. It is one of the
things a real certified sample would settle; see the outstanding `xfail` in
`tests/test_ubl.py`. The caveat is repeated in `engine.py` where the constants
live.
