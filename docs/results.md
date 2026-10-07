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
## Dev · baseline · prompt v1 (the original) · qwen3.5:9b, Colab T4

- Date: 2026-10-06 · commit: `17ef42b + uncommitted changes`
- Dataset: CORU `QA/test`, the DEV sample (seed 1, no receipt shared with the test sample), 50 receipts (`scripts/coru_sample.py`)
- Model: `qwen3.5:9b` on page images at 100 DPI (num_ctx 4096), REMOTE inference endpoint; temperature 0, seed 0, thinking off
- Mode: `vision` · prompt v1 · few-shot examples: none · QR reading: on

| Field | With ground truth | Correct | Wrong | Missing | Exact match |
| --- | ---: | ---: | ---: | ---: | ---: |
| seller_name | 50 | 9 | 4 | 37 | 18% |
| seller_name, fuzzy (token-set ≥ 85) | 50 | 11 | | | 22% |
| issue_date | 50 | 13 | 0 | 37 | 26% |
| invoice_number | 46 | 7 | 2 | 37 | 15% |
| subtotal | 23 | 3 | 0 | 20 | 13% |
| vat_amount | 19 | 5 | 0 | 14 | 26% |
| total_amount | 50 | 13 | 0 | 37 | 26% |
| seller_trn | 25 | 2 | 0 | 23 | 8% |
| **All fields** | 263 | 52 | 6 | 205 | **20%** |

- Catch rate (a rule flagged the wrong field): 205 of 211 (97%); without seller_trn: 182 of 188 (97%)
- Wrong fields not shown green (flagged or amber for any reason): 207 of 211 (98%); without seller_trn: 184 of 188 (98%)
- False alarms (a rule flagged a correct field): 9 of 52 (17%); without seller_trn: 7 of 50 (14%)
- Time: 14.4 s per document (50 documents, 0 failed)

## Dev · iteration 1 · image instruction moved outside the data fence, no empty fence, null only when not printed · qwen3.5:9b, Colab T4

- Date: 2026-10-06 · commit: `17ef42b + uncommitted changes`
- Dataset: CORU `QA/test`, the DEV sample (seed 1, no receipt shared with the test sample), 50 receipts (`scripts/coru_sample.py`)
- Model: `qwen3.5:9b` on page images at 100 DPI (num_ctx 4096), REMOTE inference endpoint; temperature 0, seed 0, thinking off
- Mode: `vision` · prompt v2 · few-shot examples: none · QR reading: on

| Field | With ground truth | Correct | Wrong | Missing | Exact match |
| --- | ---: | ---: | ---: | ---: | ---: |
| seller_name | 50 | 34 | 14 | 2 | 68% |
| seller_name, fuzzy (token-set ≥ 85) | 50 | 42 | | | 84% |
| issue_date | 50 | 47 | 3 | 0 | 94% |
| invoice_number | 46 | 24 | 19 | 3 | 52% |
| subtotal | 23 | 21 | 2 | 0 | 91% |
| vat_amount | 19 | 17 | 2 | 0 | 89% |
| total_amount | 50 | 48 | 2 | 0 | 96% |
| seller_trn | 25 | 20 | 3 | 2 | 80% |
| **All fields** | 263 | 211 | 45 | 7 | **80%** |

- Catch rate (a rule flagged the wrong field): 14 of 52 (27%); without seller_trn: 9 of 47 (19%)
- Wrong fields not shown green (flagged or amber for any reason): 41 of 52 (79%); without seller_trn: 36 of 47 (77%)
- False alarms (a rule flagged a correct field): 45 of 211 (21%); without seller_trn: 25 of 191 (13%)
- Time: 16.0 s per document (50 documents, 0 failed)

## Test · prompt v2 · Vision — Colab T4, qwen3.5:9b

- Date: 2026-10-06 · commit: `8fc0da6`
- Dataset: CORU `QA/test`, the held-out TEST sample (seed 0), 100 receipts (`scripts/coru_sample.py`)
- Model: `qwen3.5:9b` on page images at 100 DPI (num_ctx 4096), REMOTE inference endpoint; temperature 0, seed 0, thinking off
- Mode: `vision` · prompt v2 · few-shot examples: none · QR reading: on

| Field | With ground truth | Correct | Wrong | Missing | Exact match |
| --- | ---: | ---: | ---: | ---: | ---: |
| seller_name | 100 | 74 | 25 | 1 | 74% |
| seller_name, fuzzy (token-set ≥ 85) | 100 | 90 | | | 90% |
| issue_date | 100 | 96 | 4 | 0 | 96% |
| invoice_number | 82 | 36 | 34 | 12 | 44% |
| subtotal | 52 | 49 | 3 | 0 | 94% |
| vat_amount | 33 | 27 | 6 | 0 | 82% |
| total_amount | 100 | 93 | 7 | 0 | 93% |
| seller_trn | 50 | 35 | 4 | 11 | 70% |
| **All fields** | 517 | 410 | 83 | 24 | **79%** |

- Catch rate (a rule flagged the wrong field): 44 of 107 (41%); without seller_trn: 29 of 92 (32%)
- Wrong fields not shown green (flagged or amber for any reason): 92 of 107 (86%); without seller_trn: 77 of 92 (84%)
- False alarms (a rule flagged a correct field): 80 of 410 (20%); without seller_trn: 45 of 375 (12%)
- Time: 16.1 s per document (100 documents, 0 failed)

## Test · prompt v2 · Vision — local, qwen3.5:4b

- Date: 2026-10-06 · commit: `5ad331b`
- Dataset: CORU `QA/test`, the held-out TEST sample (seed 0), 100 receipts (`scripts/coru_sample.py`)
- Model: `qwen3.5:4b` on page images at 100 DPI (num_ctx 4096), local Ollama; temperature 0, seed 0, thinking off
- Mode: `vision` · prompt v2 · few-shot examples: none · QR reading: on

| Field | With ground truth | Correct | Wrong | Missing | Exact match |
| --- | ---: | ---: | ---: | ---: | ---: |
| seller_name | 100 | 58 | 42 | 0 | 58% |
| seller_name, fuzzy (token-set ≥ 85) | 100 | 76 | | | 76% |
| issue_date | 100 | 96 | 4 | 0 | 96% |
| invoice_number | 82 | 51 | 30 | 1 | 62% |
| subtotal | 52 | 47 | 5 | 0 | 90% |
| vat_amount | 33 | 25 | 8 | 0 | 76% |
| total_amount | 100 | 91 | 9 | 0 | 91% |
| seller_trn | 50 | 35 | 2 | 13 | 70% |
| **All fields** | 517 | 403 | 100 | 14 | **78%** |

- Catch rate (a rule flagged the wrong field): 37 of 114 (32%); without seller_trn: 22 of 99 (22%)
- Wrong fields not shown green (flagged or amber for any reason): 92 of 114 (81%); without seller_trn: 77 of 99 (78%)
- False alarms (a rule flagged a correct field): 81 of 403 (20%); without seller_trn: 46 of 368 (12%)
- Time: 22.4 s per document (100 documents, 0 failed)

## Old prompt vs new prompt — both models, the 100-receipt test sample

Written by hand on 2026-10-06 from the runs above; the runs themselves are
untouched. Prompt version 2 was calibrated on the DEV sample only (50 receipts,
seed 1, no receipt shared with the test sample): baseline 52/263 (20%) under
version 1, 211/263 (80%) after one iteration, both with `qwen3.5:9b`. One
iteration of the four allowed — what remained on the dev sample was misread
digits and naming style, not instruction-following, and more wording changes
would have fitted the prompt to this dataset's labelling habits. The test
sample was then scored once per model, from a clean commit.

| Field | 4B laptop · v1 | 4B laptop · v2 | 9B Colab · v1 | 9B Colab · v2 |
| --- | :---: | :---: | :---: | :---: |
| seller_name, exact | 62/100 | 58/100 | 17/100 | 74/100 |
| seller_name, fuzzy | 80/100 | 76/100 | 22/100 | 90/100 |
| issue_date | 95/100 | 96/100 | 24/100 | 96/100 |
| invoice_number | 47/82 | 51/82 | 7/82 | 36/82 |
| subtotal | 48/52 | 47/52 | 9/52 | 49/52 |
| vat_amount | 25/33 | 25/33 | 5/33 | 27/33 |
| total_amount | 94/100 | 91/100 | 22/100 | 93/100 |
| seller_trn | 34/50 | 35/50 | 4/50 | 35/50 |
| **All fields, exact** | **405/517 (78.3%)** | **403/517 (77.9%)** | **88/517 (17.0%)** | **410/517 (79.3%)** |
| Receipts with every field null | 0 | 0 | 76 | 0 |
| Wrong fields (wrong value + missing) | 112 (91 + 21) | 114 (100 + 14) | 429 (15 + 414) | 107 (83 + 24) |
| …that a rule flagged | 39 (35%) | 37 (32%) | 418 (97%) | 44 (41%) |
| …that LOOKED SETTLED (not flagged, shown green) | **20** | **22** | **7** | **15** |
| Seconds per receipt | 17.2 | 22.4 | 13.7 | 16.1 |

What it says:

- **The larger model's 17% was the prompt.** Under version 2 it scores 79.3%,
  and returns an empty receipt 0 times instead of 76.
- **The small model did not gain, and lost two fields.** 405 → 403 of 517. Not
  hidden: version 2 is not better for the 4B model on this sample, it is the
  same within two fields, and it is the version both models can follow.
- **Fewer empty answers means more wrong-but-settled ones.** The 9B model's
  count rises from 7 to 15, because under version 1 nearly all of its errors
  were missing values, which the required-field rule always catches. Every
  settled-looking wrong field, in all four runs, is a store name or a receipt
  number; no amount and no date among them.
- **Seconds per receipt are not a prompt comparison.** The two 4B runs were a
  day apart on a laptop with other load; the two 9B runs were on different
  Colab sessions.

Regression on the eight synthetic invoices (`scripts/benchmark.py`, QR off,
88 fields; `false` is a value invented where none is printed):

| | v1 | v2 | invented values, v1 → v2 |
| --- | :---: | :---: | :---: |
| `qwen2.5:7b-instruct`, text path, laptop | 86/88 | 85/88 | 0 → 0 |
| `qwen3.5:4b`, vision path, laptop | 76/88 | 80/88 | 1 → 1 |
| `qwen3.5:9b`, vision path, Colab | 80/88 | 88/88 | 0 → 0 |

The text path's one lost field is `currency`, on one invoice — a field already
recorded as sensitive to prompt and cache state. The vision gains are the
subtotal and total on the two receipts. Version 2 invented nothing that
version 1 did not.

`EXTRACTION_PROMPT_VERSION` defaults to 2 from this point; 1 stays selectable,
so every earlier number can be reproduced under the prompt it was measured
with.
## Dev · ceiling check · qwen3.5:4b local, 100 DPI, 4096 context

- Date: 2026-10-07 · commit: `28c4f81 + uncommitted changes`
- Dataset: CORU `QA/test`, the DEV sample (seed 1, no receipt shared with the test sample), 50 receipts (`scripts/coru_sample.py`)
- Model: `qwen3.5:4b` on page images at 100 DPI (num_ctx 4096), local Ollama; temperature 0, seed 0, thinking off
- Mode: `vision` · prompt v2 · few-shot examples: none · QR reading: on

| Field | With ground truth | Correct | Wrong | Missing | Exact match |
| --- | ---: | ---: | ---: | ---: | ---: |
| seller_name | 50 | 32 | 18 | 0 | 64% |
| seller_name, fuzzy (token-set ≥ 85) | 50 | 42 | | | 84% |
| issue_date | 50 | 46 | 4 | 0 | 92% |
| invoice_number | 46 | 23 | 22 | 1 | 50% |
| subtotal | 23 | 21 | 2 | 0 | 91% |
| vat_amount | 19 | 16 | 2 | 1 | 84% |
| total_amount | 50 | 49 | 1 | 0 | 98% |
| seller_trn | 25 | 20 | 3 | 2 | 80% |
| **All fields** | 263 | 207 | 52 | 4 | **79%** |

- Catch rate (a rule flagged the wrong field): 11 of 56 (20%); without seller_trn: 7 of 51 (14%)
- Wrong fields not shown green (flagged or amber for any reason): 42 of 56 (75%); without seller_trn: 37 of 51 (73%)
- False alarms (a rule flagged a correct field): 45 of 207 (22%); without seller_trn: 25 of 187 (13%)
- Time: 22.0 s per document (50 documents, 0 failed)

## Dev · ceiling check · qwen3.5:4b local, 200 DPI, 8192 context

- Date: 2026-10-07 · commit: `28c4f81 + uncommitted changes`
- Dataset: CORU `QA/test`, the DEV sample (seed 1, no receipt shared with the test sample), 50 receipts (`scripts/coru_sample.py`)
- Model: `qwen3.5:4b` on page images at 200 DPI (num_ctx 8192), local Ollama; temperature 0, seed 0, thinking off
- Mode: `vision` · prompt v2 · few-shot examples: none · QR reading: on

| Field | With ground truth | Correct | Wrong | Missing | Exact match |
| --- | ---: | ---: | ---: | ---: | ---: |
| seller_name | 50 | 35 | 15 | 0 | 70% |
| seller_name, fuzzy (token-set ≥ 85) | 50 | 42 | | | 84% |
| issue_date | 50 | 48 | 2 | 0 | 96% |
| invoice_number | 46 | 24 | 20 | 2 | 52% |
| subtotal | 23 | 22 | 1 | 0 | 96% |
| vat_amount | 19 | 16 | 2 | 1 | 84% |
| total_amount | 50 | 49 | 1 | 0 | 98% |
| seller_trn | 25 | 19 | 3 | 3 | 76% |
| **All fields** | 263 | 213 | 44 | 6 | **81%** |

- Catch rate (a rule flagged the wrong field): 13 of 50 (26%); without seller_trn: 7 of 44 (16%)
- Wrong fields not shown green (flagged or amber for any reason): 37 of 50 (74%); without seller_trn: 31 of 44 (70%)
- False alarms (a rule flagged a correct field): 41 of 213 (19%); without seller_trn: 22 of 194 (11%)
- Time: 28.0 s per document (50 documents, 0 failed)

## 4B vs 9B on the test sample — is the comparison fair, and where do they differ?

Written by hand on 2026-10-07 from the saved records of the two final test
runs (`local-b-vision-v2`, `colab-b-vision-v2`). No model was run for this
section, and the test sample was not scored again.

**The two runs used the same settings.** Read from each run's own header above
and from its per-receipt records:

| | `qwen3.5:4b`, laptop | `qwen3.5:9b`, Colab T4 |
| --- | --- | --- |
| Prompt version | 2 | 2 |
| Mode | vision, 100 of 100 receipts | vision, 100 of 100 receipts |
| Page image | 100 DPI, WebP quality 85 | 100 DPI, WebP quality 85 |
| Preprocessing | photo turned upright (EXIF), fitted to an A4-long-side page | the same code |
| Context, sampling | 4,096 tokens · temperature 0 · seed 0 · thinking off | the same |
| Few-shot · QR reading | none · on | none · on |
| Receipts · scored fields | the same 100 · the same 517 | |
| Commit | `5ad331b` | `8fc0da6` |

The two commits differ by one file, `docs/results.md`; no code changed between
them. What is NOT identical: the Ollama build (0.35.0 on the laptop, 0.35.1 on
Colab) and where the layers run (the laptop keeps about half of the 4B model on
the CPU). Neither is a setting of the comparison, but they are not controlled.

**Per field.**

| Field | Scored | 4B correct | 9B correct | 9B − 4B | Wrong in both | Only 4B wrong | Only 9B wrong |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| seller_name | 100 | 58 (58%) | 74 (74%) | +16 | 24 | 18 | 2 |
| issue_date | 100 | 96 (96%) | 96 (96%) | 0 | 4 | 0 | 0 |
| invoice_number | 82 | 51 (62%) | 36 (44%) | −15 | 28 | 3 | 18 |
| subtotal | 52 | 47 (90%) | 49 (94%) | +2 | 3 | 2 | 0 |
| vat_amount | 33 | 25 (76%) | 27 (82%) | +2 | 6 | 2 | 0 |
| total_amount | 100 | 91 (91%) | 93 (93%) | +2 | 4 | 5 | 3 |
| seller_trn | 50 | 35 (70%) | 35 (70%) | 0 | 12 | 3 | 3 |
| **All** | **517** | **403 (77.9%)** | **410 (79.3%)** | **+7** | **81** | **33** | **26** |

CORU's QA split has no ground truth for line items, so none is scored.

- **On this dataset and evaluation setup, 4B to 9B gave only a marginal
  change:** +7 fields of 517, 1.4 points.
- **The total hides a trade.** The 9B is 16 fields better on the store name and
  15 worse on the receipt number (12 of those it returned empty). On dates,
  amounts and VAT numbers the two are within two fields of each other.
- **Most errors are shared.** 81 fields are wrong in both models — 71% of the
  4B's errors and 76% of the 9B's — and on 39 of them the two models returned
  the identical wrong value. A field either model got right: 436 of 517
  (84.3%).
- By receipt: the 9B did better on 23, the 4B on 18, and they tied on 59.

**Why the wrong fields were wrong** (`scripts/coru_errors.py`, rules with
tests, same two runs):

| Cause | 4B (114 wrong) | 9B (107 wrong) |
| --- | ---: | ---: |
| Misread characters or digits | 33 | 38 |
| Label-style mismatch (the label's convention, not the page's) | 34 | 27 |
| Wrong field picked | 12 | 6 |
| Empty | 14 | 24 |
| Unclassified (near neither the label nor any other annotated value) | 21 | 12 |

Label style is the shop named with its branch or legal name, another of the
numbers the receipt prints, and — four fields per model — an amount the scorer
marks wrong only because the label uses a decimal comma (`*24,44` against a
correct `24.44`). The scorer was left as it is, so no earlier number moves; the
four are counted here instead. Misreads are mostly long receipt numbers: 20 of
the 4B's 33 and 22 of the 9B's 38.

**Resolution, on the dev sample only** (50 receipts, 263 fields, prompt v2):

| | 100 DPI, 4,096 context | 200 DPI, 8,192 context |
| --- | ---: | ---: |
| `qwen3.5:4b`, laptop | 207 (78.7%), 22.0 s/receipt | 213 (81.0%), 28.0 s/receipt |
| `qwen3.5:9b`, Colab | 211 (80.2%) | not run |

The 4B does run at 200 DPI on the 4 GB laptop (about half of it on the CPU, as
at 100 DPI); the image costs roughly twice the prompt tokens. It gained six
fields, and its misreads fell from 26 to 22. The 9B at 200 DPI was planned and
then not run, by decision, so the question "would the larger model pull ahead
with more pixels?" is NOT answered here. What is measured is that at the same
settings the two sizes are 1.4 points apart on the test sample and 1.5 on the
dev sample.

**What this supports, and what it does not.** On these receipts, at 100 DPI,
with this prompt and this scorer, doubling the model changed the total
marginally, because most of what is left is not something a larger model of the
same family fixes at this resolution: labels in another convention than the
page (a quarter of the errors), and digits too small to read (a third). It does
not show that model size never matters — a different dataset, a higher
resolution, or a harder task could separate them, and the store-name column
already does.
