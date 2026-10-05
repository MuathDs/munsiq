# Measured results

Every run of `scripts/coru_eval.py` appends itself here: date, commit,
configuration, per-field exact match, catch rate and seconds per document.
Nothing in this file is estimated or edited after the fact.

**Dataset.** CORU / ReceiptSense — Abdallah et al., "ReceiptSense: Beyond
Traditional OCR - A Dataset for Receipt Understanding", arXiv:2406.04493;
Hugging Face `abdoelsayed/CORU`, MIT licence. Arabic/English retail receipt
photos. Ground truth is the Receipt-QA split's answers, mapped to the fields of
ours they correspond to (`scripts/coru_sample.py` has the mapping and why each
lookalike question was left out). 100 receipts, fixed sample, seed 0.

**How to read it.**

- *Exact match* is after normalization: amounts as Decimals, dates as dates
  (an ambiguous `6/11/2022` is accepted under either reading), names with case,
  spacing and punctuation folded.
- *seller_name, fuzzy* sits next to the strict row because every annotated
  store name is in Latin script, including on Arabic receipts: an exactly-read
  Arabic name cannot match its English annotation.
- *subtotal* is loose ground truth: ours means "excluding VAT", a receipt's
  printed "subtotal" may not.
- *seller_trn* is not a Saudi VAT number on these receipts, so the format rule
  flags it even when it was read correctly. Catch rate and false alarms are
  therefore given with and without it.
- These receipts are not what the product is built for (Saudi tax invoices with
  signed XML or a ZATCA QR). They are a public, checkable stand-in for the hard
  case: a photographed page with no text layer.

## (a) OCR text path (no Arabic OCR on this machine) — local

- Date: 2026-10-05 · commit: `f5913a5`
- Dataset: CORU `QA/test`, 100 receipts, seed 0 (`scripts/coru_sample.py`)
- Model: `qwen2.5:7b-instruct` on OCR text (num_ctx 4096), local Ollama; temperature 0, seed 0, thinking off
- Mode: `text` · few-shot examples: none · QR reading: on

| Field | With ground truth | Correct | Wrong | Missing | Exact match |
| --- | ---: | ---: | ---: | ---: | ---: |
| seller_name | 100 | 5 | 43 | 52 | 5% |
| seller_name, fuzzy (token-set ≥ 85) | 100 | 22 | | | 22% |
| issue_date | 100 | 79 | 6 | 15 | 79% |
| invoice_number | 82 | 2 | 1 | 79 | 2% |
| subtotal | 52 | 26 | 1 | 25 | 50% |
| vat_amount | 33 | 17 | 3 | 13 | 52% |
| total_amount | 100 | 81 | 9 | 10 | 81% |
| seller_trn | 50 | 1 | 0 | 49 | 2% |
| **All fields** | 517 | 211 | 63 | 243 | **41%** |

- Catch rate (a rule flagged the wrong field): 236 of 306 (77%); without seller_trn: 188 of 257 (73%)
- Wrong fields not shown green (flagged or amber for any reason): 265 of 306 (87%); without seller_trn: 216 of 257 (84%)
- False alarms (a rule flagged a correct field): 13 of 211 (6%); without seller_trn: 12 of 210 (6%)
- Time: 29.2 s per document (100 documents, 1 failed)

## (b) Vision — local

- Date: 2026-10-05 · commit: `f5913a5`
- Dataset: CORU `QA/test`, 100 receipts, seed 0 (`scripts/coru_sample.py`)
- Model: `qwen3.5:4b` on page images at 100 DPI (num_ctx 4096), local Ollama; temperature 0, seed 0, thinking off
- Mode: `vision` · few-shot examples: none · QR reading: on

| Field | With ground truth | Correct | Wrong | Missing | Exact match |
| --- | ---: | ---: | ---: | ---: | ---: |
| seller_name | 100 | 62 | 38 | 0 | 62% |
| seller_name, fuzzy (token-set ≥ 85) | 100 | 80 | | | 80% |
| issue_date | 100 | 95 | 5 | 0 | 95% |
| invoice_number | 82 | 47 | 27 | 8 | 57% |
| subtotal | 52 | 48 | 4 | 0 | 92% |
| vat_amount | 33 | 25 | 8 | 0 | 76% |
| total_amount | 100 | 94 | 6 | 0 | 94% |
| seller_trn | 50 | 34 | 3 | 13 | 68% |
| **All fields** | 517 | 405 | 91 | 21 | **78%** |

- Catch rate (a rule flagged the wrong field): 39 of 112 (35%); without seller_trn: 23 of 96 (24%)
- Wrong fields not shown green (flagged or amber for any reason): 92 of 112 (82%); without seller_trn: 76 of 96 (79%)
- False alarms (a rule flagged a correct field): 77 of 405 (19%); without seller_trn: 43 of 371 (12%)
- Time: 17.2 s per document (100 documents, 0 failed)

## (c) Vision + 2 synthetic few-shot examples — local

- Date: 2026-10-05 · commit: `f5913a5`
- Dataset: CORU `QA/test`, 100 receipts, seed 0 (`scripts/coru_sample.py`)
- Model: `qwen3.5:4b` on page images at 100 DPI (num_ctx 4096), local Ollama; temperature 0, seed 0, thinking off
- Mode: `vision` · few-shot examples: 2 synthetic · QR reading: on

| Field | With ground truth | Correct | Wrong | Missing | Exact match |
| --- | ---: | ---: | ---: | ---: | ---: |
| seller_name | 100 | 34 | 23 | 43 | 34% |
| seller_name, fuzzy (token-set ≥ 85) | 100 | 45 | | | 45% |
| issue_date | 100 | 56 | 1 | 43 | 56% |
| invoice_number | 82 | 21 | 21 | 40 | 26% |
| subtotal | 52 | 26 | 1 | 25 | 50% |
| vat_amount | 33 | 11 | 4 | 18 | 33% |
| total_amount | 100 | 53 | 4 | 43 | 53% |
| seller_trn | 50 | 23 | 2 | 25 | 46% |
| **All fields** | 517 | 224 | 56 | 237 | **43%** |

- Catch rate (a rule flagged the wrong field): 245 of 293 (84%); without seller_trn: 218 of 266 (82%)
- Wrong fields not shown green (flagged or amber for any reason): 280 of 293 (96%); without seller_trn: 253 of 266 (95%)
- False alarms (a rule flagged a correct field): 42 of 224 (19%); without seller_trn: 19 of 201 (9%)
- Time: 19.9 s per document (100 documents, 0 failed)

