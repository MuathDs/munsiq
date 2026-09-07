# Ingestion & extraction (Phase 3+4)

Upload → storage → text → extraction → database. Deliberately minimal: no
classification, no packet splitting, no vLLM, no evaluation harness.

## Order of operations

```
1. STEP ZERO   embedded UBL XML?  ── yes ──▶ fields from signed XML, model NEVER called
                     │ no
2. RASTERIZE   one WebP per page (PyMuPDF, 150 DPI)
3. TEXT        text layer per page; OCR only where there is none
4. EXTRACT     schema-conditioned prompt → Ollama → JSON
5. GROUND      each value → a bounding box
6. PERSIST     field rows (nulls included), page rows, validation findings
```

Step Zero is first because a ZATCA Phase 2 invoice already contains the answer,
cryptographically signed by the seller. Reading it costs no GPU and cannot
hallucinate. `test_embedded_ubl_populates_fields_without_calling_the_model`
asserts the model call count is exactly zero on that path.

## Text layer first, OCR second

**This is the most important design decision in this phase, and it deviates
from the original plan** — which specified OCR as the primary text source.

A digital PDF already contains the exact text of every word and the exact
rectangle it occupies. Running OCR over it is a lossy reconstruction of
information the file is already carrying. So:

| Page has… | Text comes from | Boxes are |
| --- | --- | --- |
| a text layer | the PDF itself | **exact**, straight from the PDF |
| no text layer | OCR | approximate, from OCR detection |

### What this means for grounding

When a page has a text layer, a field's bounding box is assembled from the real
word rectangles the PDF reported. Fuzzy matching still selects *which* words a
value corresponds to, but the coordinates are not guessed — they are the
document's own. **Fuzzy matching only produces approximate geometry on OCR
pages.** A value that matches nothing anywhere gets `bbox=null` and is
downgraded to `review_suggested`, because a value that appears nowhere on the
page is a hallucination signal.

Boxes are normalized floats 0.0–1.0 throughout, never pixels.

## The Arabic OCR gap — known, and made loud

The OCR engine is **RapidOCR** (ONNX Runtime). It was chosen because it is the
one that installs and loads under this machine's WDAC code-integrity policy.

**It cannot read Arabic.** Not "poorly" — at all. Its bundled recogniser is
`ch_PP-OCRv4_rec`, and its character dictionary, read directly out of the ONNX
metadata, is:

```
6623 entries: 6280 CJK · 77 Latin · 10 digits · 0 Arabic
```

A model cannot emit a character that is not in its dictionary.

Consequence: **an image-only Arabic scan cannot be processed today.** Rather
than returning empty text as though the read had succeeded, the pipeline:

1. records `pages.text_source = 'ocr_unsupported_script'` on the page row;
2. writes a `validation_results` row with rule code `OCR_SCRIPT_UNSUPPORTED`,
   severity `error`, and a bilingual message; and
3. surfaces `text_source` in the `GET /documents/{id}` response.

The wording is careful about what is actually known. When OCR returns nothing
we cannot tell an Arabic scan from a blank page, so the message says exactly
that rather than asserting the page is Arabic.

`pages.text_source` values:

| Value | Meaning |
| --- | --- |
| `text_layer` | Read from the PDF. Exact text, exact boxes. |
| `ocr` | OCR produced text. |
| `ocr_unsupported_script` | No text layer, OCR recognised nothing, and the engine cannot read Arabic. **Degraded.** |
| `ocr_unavailable` | The configured engine failed to load. **Degraded.** |
| `empty` | No text layer and nothing recognised. **Degraded.** |

### Closing the gap

Either install Tesseract with the `ara` traineddata and add a `TesseractEngine`
implementing the `OCREngine` protocol, or supply an Arabic recognition model to
RapidOCR (it accepts custom ONNX weights). Both are additive — no caller
changes, because the protocol already exists and `supports_arabic` is already
consulted.

## Arabic text normalization

Two problems, both verified against real PDF behaviour rather than assumed:

**Presentation forms.** PDF text layers store *shaped* glyphs. Extracting
Arabic gives `U+FE93 U+FEAD …` where the logical text is `U+0629 U+0631 …`.
Without NFKC folding, no Arabic value ever matches its UBL counterpart. This is
the same condition behind the ZATCA `ARABIC_ENCODING_SUSPECT` failure mode.

**Arabic-Indic numerals.** `٤٥,٣٢٠.٠٠` must fold to `45,320.00` before any
arithmetic or substring check.

Also folded: invisible format characters (zero-width joiners, BOMs), typographic
dashes and non-breaking spaces. One of these was found the hard way — PyMuPDF
returns `SA<U+00AD>2026<U+00AD>0334` for text drawn as `SA-2026-0334`, because
the font maps its hyphen glyph onto the soft hyphen. The page visibly shows
hyphens, so U+00AD folds to `-` rather than being deleted.

Normalized text is stored; the original is preserved alongside it, which is why
`ExtractedField` carries `original_value`.

## Schema-conditioned prompting

The field list is **input**, read from `extraction_schemas.definition` at
request time. It is never hardcoded and never baked into weights.

The prompt carries each field's key, type, both labels, and its
natural-language guideline. Adding a field is a database row, not a retrain.

`INFERENCE_MODEL` defaults to **`qwen2.5:7b-instruct`** — a general instruct
model. It is deliberately **not** `munsiq-extractor`, the earlier fine-tune,
whose fixed five-column schema is baked into its weights. Pointing this at that
model would defeat the entire design of this phase.

Vision is opt-in (`EXTRACTION_USE_VISION`, default false): a VL model does not
fit comfortably in 4 GB, so the default path sends text only.

### Prompt-injection guard

Document text is fenced between explicit delimiters and declared as data. The
system prompt states that instruction-like content inside that region must be
ignored and reported in a `_suspicious_content` field, which becomes a
`SUSPICIOUS_DOCUMENT_CONTENT` validation finding. Text inside a document can
never change the model's behaviour.

## Negative examples are persisted

When the model correctly returns null for a field genuinely absent from the
document, **that row is written** with `value_extracted = NULL`.

This is not an oversight to tidy up later. A corpus of only positive examples
cannot teach a future model that a field can be absent — it can only learn a
fixed key set, which is precisely how the previous fine-tune overfit. The cost
is one boolean decision now; the information is unrecoverable later.

Distinct case: when Step Zero answered and the model was skipped, fields not
present in the UBL are written as `NULL` but marked `review_suggested`, not
`auto_validated`. The model was never asked, so their absence is **unverified** —
claiming otherwise would be a lie in the data.

## Storage

Local filesystem under `backend/var/storage`, git-ignored. Keys are namespaced
per tenant from the first byte:

```
{org_id}/documents/{document_id}/original.pdf
{org_id}/documents/{document_id}/pages/{n}.webp
{org_id}/documents/{document_id}/embedded.xml
```

The `Storage` protocol exists so an S3/MinIO backend drops in later; that
implementation is deliberately not built (no Docker on this machine). Keys are
validated against a strict pattern and the resolved path is confirmed to be
inside the storage root — a traversal here would write outside the tenant tree.

## Processing is a BackgroundTask, not a worker

There is no Redis (no Docker), so `POST /documents` returns 202 and runs
`process_document` in a FastAPI `BackgroundTasks`. The entry point is a plain
coroutine, so moving to arq is a call-site change.

The trade-off is real and is recorded in CLAUDE.md: **no retries, and no
durability across a restart.** A process restart mid-document leaves that
document unprocessed with no automatic recovery.

## Running it

```bash
cd backend
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m scripts.seed_demo      # org + queue + schema
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

`scripts/seed_demo.py` creates the extraction schema — 11 bilingual invoice
fields with guidelines. Without it, uploads fail with a clear error rather than
silently falling back to a hardcoded field list.
