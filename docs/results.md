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

- Date: 2026-10-05 · commit: `8d93153`
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

- Date: 2026-10-05 · commit: `8d93153`
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

- Date: 2026-10-05 · commit: `8d93153`
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

## (b) Vision — Colab T4, qwen3.5:9b

- Date: 2026-10-05 · commit: `8104db2`
- Dataset: CORU `QA/test`, 100 receipts, seed 0 (`scripts/coru_sample.py`)
- Model: `qwen3.5:9b` on page images at 100 DPI (num_ctx 4096), REMOTE inference endpoint; temperature 0, seed 0, thinking off
- Mode: `vision` · few-shot examples: none · QR reading: on

| Field | With ground truth | Correct | Wrong | Missing | Exact match |
| --- | ---: | ---: | ---: | ---: | ---: |
| seller_name | 100 | 17 | 7 | 76 | 17% |
| seller_name, fuzzy (token-set ≥ 85) | 100 | 22 | | | 22% |
| issue_date | 100 | 24 | 0 | 76 | 24% |
| invoice_number | 82 | 7 | 4 | 71 | 9% |
| subtotal | 52 | 9 | 0 | 43 | 17% |
| vat_amount | 33 | 5 | 2 | 26 | 15% |
| total_amount | 100 | 22 | 2 | 76 | 22% |
| seller_trn | 50 | 4 | 0 | 46 | 8% |
| **All fields** | 517 | 88 | 15 | 414 | **17%** |

- Catch rate (a rule flagged the wrong field): 418 of 429 (97%); without seller_trn: 372 of 383 (97%)
- Wrong fields not shown green (flagged or amber for any reason): 422 of 429 (98%); without seller_trn: 376 of 383 (98%)
- False alarms (a rule flagged a correct field): 17 of 88 (19%); without seller_trn: 13 of 84 (15%)
- Time: 13.7 s per document (100 documents, 0 failed)

## Laptop vs Colab — vision path, same 100 receipts

Written by hand on 2026-10-05 from the two vision runs above; the runs
themselves are untouched. Same prompt, same 4,096-token context, same 100 DPI
page images, temperature 0, seed 0, thinking off. Only the model and where it
ran differ.

| Field | Laptop · `qwen3.5:4b` (4 GB GPU, local) | Colab T4 · `qwen3.5:9b` (remote, through a tunnel) |
| --- | :---: | :---: |
| seller_name, exact | 62/100 (62%) | 17/100 (17%) |
| seller_name, fuzzy | 80/100 (80%) | 22/100 (22%) |
| issue_date | 95/100 (95%) | 24/100 (24%) |
| invoice_number | 47/82 (57%) | 7/82 (9%) |
| subtotal | 48/52 (92%) | 9/52 (17%) |
| vat_amount | 25/33 (76%) | 5/33 (15%) |
| total_amount | 94/100 (94%) | 22/100 (22%) |
| seller_trn | 34/50 (68%) | 4/50 (8%) |
| **All fields, exact** | **405/517 (78%)** | **88/517 (17%)** |
| Receipts returned with every field null | 0 | 76 |
| Wrong fields a rule flagged (catch rate) | 39/112 (35%) | 418/429 (97%) |
| Wrong fields not shown green | 92/112 (82%) | 422/429 (98%) |
| False alarms on correct fields | 77/405 (19%) | 17/88 (19%) |
| Seconds per receipt | 17.2 | 13.7 |

**The larger model did not read worse; it answered "null" to this prompt.** On
76 of 100 receipts `qwen3.5:9b` returned every field null. Checked, not
assumed:

- The image arrives. The same request costs 2,006 prompt tokens with the image
  and 1,005 without it on both models (1,001 tokens for the image either way),
  and asked a plain question about the picture the 9B model answers it.
- It is not the context size. The same receipts come back empty at 8,192.
- It is the prompt. Ten of the receipts the extraction prompt left empty were
  sent again with a bare three-field request ("return seller_name, issue_date,
  total_amount as JSON"): 30 of 30 fields filled, 27 of 30 correct.

So the extraction prompt — written and adjusted against the small models, with
"returning null is CORRECT" and a text fence that says to read the page from
its image — is over-obeyed by the 9B model. The prompt was NOT changed in
response: tuning it against the set it is scored on would make the next number
meaningless. What this run does show is the safety net working: when the model
returns nothing, 97% of those fields are flagged by a rule and 98% are not
shown green, so a reviewer is not handed an empty document that looks finished.

Sending these images to Colab did not break the local-only rule for user
documents: CORU is a public dataset. `backend/.env` was not edited — the tunnel
URL and model were environment variables on that one command.
