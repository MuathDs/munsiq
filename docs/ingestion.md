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

## Reading order

A text layer is a content stream, not a picture. What comes out is only as ordered
as the producer wrote it, and two things went wrong on the first real invoice (a
marketplace B2C receipt):

**Arabic words in visual order.** A producer that draws a right-to-left line from
its left end writes the words to the stream leftmost-first. MuPDF puts each on a
line of its own, so a printed "شركة حلول نور" was extracted as "نور حلول شركة" —
and grounding scored it low, because the words of a window no longer read as the
value. Grouping by MuPDF's own lines cannot fix this, so `_reading_order` in
`app/services/pagetext.py` works from position:

1. Fragments (MuPDF's lines) that contain Arabic are cut at wide gaps and fused
   with their neighbours where the gap is at most **half a line height**. A word
   space is about a quarter of one; the padding between two table cells is more.
2. Each row containing Arabic is ordered by x: an Arabic run right to left, and —
   in a right-to-left page — the runs themselves right to left.
3. Left-to-right runs (numbers, dates, Latin words) keep the stream's order.

The direction of a mixed row comes from the **page**, by which script has more
words. "Seller:" at the left of an Arabic name is a label followed by its value on
an English invoice and a value followed by its label on an Arabic one; the pixels
are the same. It matters because `pages.text` is flat, and a value that precedes
its label reads as the previous field's.

An English page is untouched: rows are only fused where Arabic is involved, and the
six generated invoices read identically before and after. Ordering by position
rather than reversing whatever came out is what keeps a producer that already
wrote logical order from being reversed twice.

**A value wrapped after a hyphen.** "SA7KXWTPB-" over "LQP3081947" is one invoice
number. `join_words` joins them without a space, and grounding uses the same
function, so the value still finds its box (each half keeps its own rectangle).
The rule is narrow on purpose, because a wrong join glues two fields together: the
hyphen must follow a letter or digit, the next word must start with one and must
not be a label ending in a colon, and it must sit directly below.

Tests: `tests/test_pagetext_order.py`. The fixtures reproduce the mechanism
(per-glyph positioned Arabic words in either stream order); the real PDF is
personal data and is not in the repository.

## Word segmentation is ours, not MuPDF's

The reading-order fix above reorders whatever "words" `page.get_text("words")`
handed back. That tool turned out to be unreliable independent of any one
document: it can under-segment (a real inter-word gap with no explicit space
glyph comes back as a single "word" — reproduced with correctly measured
glyph widths and no artificial padding) and, separately, it can over-segment
Arabic disproportionately right after a letter that does not join forward. It
even showed up in `page.get_text()` itself, on one of our OWN generated
invoices: a ~300pt gap between two table cells lost its separator.

So `_words_from_text_layer` builds words itself from raw glyph positions
(`page.get_text("rawdict")`) instead. A gap is a word break when it exceeds a
factor of the average width of the two glyphs either side of it — **relative
to the glyphs on that page, never a fixed point size**, so the same ratio
segments identically at 8pt and at 80pt. An explicit space character always
wins over the measurement, regardless of what the gap says. The threshold is
looser specifically right after a letter that never joins forward (the alef
family, دذ, ر ز, و — `NON_JOINING_LETTERS`), because a renderer that shapes
Arabic in separate runs can leave a small positioning seam exactly where a run
ends; the allowance is bounded, so a real word boundary in that position still
splits.

None of the four thresholds were tuned against the deleted real invoice — only
against measured font metrics and the general shape of each failure mode, on
purpose: fitting a threshold to one document is the mistake this project
exists to fix in the model, and doing the same thing in the extraction code
would not be better. Whether our own row-fusion/column-split code contributed
to the original over-fragmentation was checked directly rather than assumed:
it only reorders already-built words into rows and cuts a fragment at a real
column gap, and cannot turn one word into several letters
(`test_reading_order_never_changes_the_word_count`).

Tests: `tests/test_word_segmentation.py`.

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

### Text vs. vision routing

`EXTRACTION_MODE` (`text` | `vision` | `auto`, default `auto`) decides, **per
page**, whether that page is sent as inline text or rasterized and attached as
an image. Step Zero (signed UBL) always wins regardless of this setting — the
model is not called at all when the invoice already told us the answer.

`app/services/extraction/routing.py` makes the per-page call: a page with no
usable text at all (`PageText.is_degraded`) or whose text layer LOOKS cut
apart — the same signature `TEXT_LAYER_FRAGMENTED` already warns about, see
below — needs vision; everything else stays on the cheap, exact text path.
`resolve_mode()` returns both the whole-call decision (`text` or `vision` — a
text-only model cannot see images at all, so ONE bad page forces the WHOLE
call through the vision-capable model) and the set of page numbers that
actually needed it, which is what gets recorded on each `pages` row
(`extraction_path`) and shown in the review UI next to the page number.

The vision model is deliberately a SEPARATE model, base URL and context budget
from the text settings (`VISION_MODEL`, `VISION_INFERENCE_BASE_URL`,
`VISION_NUM_CTX`) — `qwen2.5vl:3b` locally, small enough for 4 GB; a heavier VL
model belongs on a machine with more VRAM, reached through
`VISION_INFERENCE_BASE_URL` (a Colab notebook tunnelled through ngrok, say).
Falls back to the text endpoint when unset. Pages routed to vision are
rasterized separately from the review UI's own page image, at `VISION_RASTER_DPI`
(100, lower than `RASTER_DPI`'s 150) — a vision model's prompt cost scales with
pixel count, and 100 DPI measured at ~1,300 prompt tokens per page on this
model versus 2.8x that at 150 DPI, for the same accuracy on the pages tested.
At most `MAX_VISION_PAGES` pages are actually rasterized and attached per
document; the rest stay on the text path (their own text layer, however
unreliable) rather than being marked "see the attached image" with nothing to
back it.

A mixed prompt inlines each text page under its own `--- page N ---` marker and
replaces an unreliable page's text with `--- page N: no reliable text layer;
read this page from its attached image instead ---`, in the same order the
images themselves are attached, so the model can match each marker to the
image that follows it.

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

## The upload path

1. **Authorize.** The BFF holds the tenant identity, so it calls
   `POST /documents/authorize`, which returns a signed, five-minute upload URL.
   The browser never sees a tenant id, and — per CLAUDE.md — document bytes never
   stream through Next.js.
2. **Post.** The browser sends the PDF straight to `POST /documents?upload_token=…`
   (which also still accepts the trusted-BFF headers, for API clients and tests).
   A page-image token cannot authorize an upload, nor an upload token a read: the
   token carries a `kind`.
3. **Validate, then hash — before storing anything.** Empty is 400, over
   `MAX_UPLOAD_BYTES` is 413, and anything without a `%PDF-` header in its first
   KiB is 415. The SHA-256 is computed next.
4. **Resends are idempotent.** A file this tenant already holds returns the
   existing document with **200**, never a 500 and never a second pipeline run.
   `UNIQUE(org_id, sha256)` is the backstop for two identical concurrent uploads;
   the loser resolves to the winner's row through a savepoint.
5. **Except a failed or stalled attempt**, which is *retried*: uploading the same
   file again clears the failed annotation and processes the stored bytes again.
   Without this, deduplication would make a failure permanent.
6. **Commit, then start the pipeline.** The handler owns its transaction and
   schedules `process_document` only after it commits. FastAPI (≥ 0.118) runs a
   yield-dependency's teardown — where a request session commits — *after* the
   response and its background tasks, so a handler that wrote through such a
   session and then queued the pipeline raced its own commit and lost: the
   pipeline found no document. Do not reintroduce that shape.

A document with no annotation is `processing`; past `STALLED_AFTER_S` (15 min) it
is reported as `stalled`, because a process that died mid-document would otherwise
look busy forever. A pipeline failure creates a `failed` annotation with a
`PIPELINE_FAILED` finding in both languages, so the reason is visible.

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
