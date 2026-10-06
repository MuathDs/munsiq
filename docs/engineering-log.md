# Engineering log

Problems that were real, what caused them, what fixed them, and the evidence.
Every entry is taken from the commit history, `CLAUDE.md`, the tests and
`docs/results.md`; nothing here is reconstructed from memory or estimated.
Real documents are described by kind ("a marketplace receipt", "a contractor's
tax invoice"), never by supplier.

Commits are cited by date and subject rather than by hash, so the references
survive a history rewrite.

| # | Problem | Root cause | Fix | Evidence |
| --- | --- | --- | --- | --- |
| 1 | Tenant-isolation tests could pass for the wrong reason | "no leak" and "no data" look identical | A negative control | `test_postgres_role_bypasses_rls_control` |
| 2 | Arabic words reached the model in reverse order | Text layers store RTL lines in visual order | Reading order rebuilt from positions | `tests/test_pagetext_order.py` |
| 3 | Arabic words merged or cut mid-word | MuPDF's word tokenizer, in both directions | Words built from raw glyph gaps | `tests/test_word_segmentation.py` |
| 4 | A reasoning model invented values | Server default temperature 1; `think` ignored | Native API, every sampling control explicit | 3/9 → 8/9, same prompt |
| 5 | A consistent receipt was blocked | The model copied the total into the subtotal | Subtotal derived deterministically | `tests/test_totals.py` |
| 6 | The QR on the page was not used | Nothing read it | Decode it; the model never overrides it | 7/9 → 9/9 on a real invoice |
| 7 | Half the public receipts would have been read sideways | EXIF rotation ignored when wrapping a photo | Pixels turned upright first | `test_a_photo_stored_sideways_is_turned_upright` |
| 8 | Few-shot examples hurt | The small model answered "null" | Left off; measured, not assumed | 78% → 43% |
| 9 | A larger model scored 17% | The prompt, not the model | Not re-tuned on the test set | 27/30 with a bare prompt |

---

## 1. An isolation test that could not fail

**Problem.** Tests asserted that one tenant cannot see another's rows. A test
like that passes when isolation works, and also when its own setup silently
stopped inserting rows.

**Root cause.** Two different states — "the policy hid the rows" and "there were
no rows" — produce the same assertion result. Separately, the database's default
role carries `BYPASSRLS`, which `FORCE ROW LEVEL SECURITY` does not override, so
the application path was beside the policies rather than subject to them.

**Fix.** `session_scope()` issues `SET LOCAL ROLE` to a non-bypassing role in the
same transaction as the tenant setting. The API layer has no `org_id` filter at
all, so the tests measure the policies and nothing else. And a negative control
asserts that the bypassing role *does* see both tenants: if that ever stops
being true, the setup has stopped inserting data and the green suite means
nothing.

**Evidence.** `tests/test_api_tenancy.py`, over HTTP against the real app;
`test_postgres_role_bypasses_rls_control`; 17 of 17 org-scoped tables `ENABLE` +
`FORCE`, 18 policies (live query, 2026-09-20). ADR 004. Commit of 2026-09-07,
"subject the application path to RLS, not merely adjacent to it".

## 2. Arabic words in reverse order

**Problem.** On the first real document, a marketplace receipt, a vendor name
printed as three Arabic words reached the model with the words reversed. A
value wrapped after a hyphen was also rejoined with a space in the middle.

**Root cause.** A PDF text layer is a content stream. A producer that draws a
right-to-left line from its left end writes the words in visual order, and
MuPDF then puts each on a line of its own, so grouping by its lines cannot
repair it.

**Fix.** `pagetext._reading_order` regroups words into rows by position and
orders each Arabic row from the x coordinates. Three deliberate limits: a row is
only fused where Arabic is involved (an English page is byte-identical to
before), the fusing gap is half a line height, and left-to-right runs keep the
stream's order. `join_words` joins a hyphen-wrapped value without a space, and
grounding uses the same function so the value still finds its box.

**Evidence.** `tests/test_pagetext_order.py`. The fixtures reproduce the
mechanism with an invented vendor, because the real PDF is personal data and is
not in the repository. Commit of 2026-09-21, "Arabic reading order and
hyphen-wrapped values".

## 3. Arabic words merged, and cut apart

**Problem.** Arabic tokens came out as single letters on one document and as
three words fused into one on another.

**Root cause.** Not one producer's quirk: MuPDF's `get_text("words")` itself.
It under-segments (three correctly spaced words returned as one) and
over-segments (splits right after a letter that does not join forward). Plain
`get_text()` also dropped the separator across a 300 pt gap between two table
cells on one of this project's own generated invoices. The project's own
row-fusion code was checked and ruled out: it reorders finished words and never
looks inside one.

**Fix.** `pagetext._words_from_text_layer` no longer calls the word tokenizer.
It builds words from raw glyph positions, comparing each gap with the width of
the glyphs either side of it — never a fixed point size, so 8 pt and 80 pt
segment identically. An explicit space always wins. The threshold is looser,
by a bounded amount, after a letter that never joins forward.

**Evidence.** `tests/test_word_segmentation.py`, including
`test_mupdf_words_tool_merges_real_gaps_into_one_word`,
`test_the_same_ratio_is_judged_the_same_at_any_font_size` and
`test_reading_order_never_changes_the_word_count`. Commit of 2026-09-22,
"producer-agnostic word segmentation, not MuPDF's tokenizer".

## 4. A model that invented a VAT amount

**Problem.** On a real contractor's tax invoice, the same bare prompt scored 7/9
with one small vision model and 3/9 with a newer one, which invented computed
values: a VAT amount with seven decimal places, a wrong digit in a VAT number.

**Root cause.** Two server defaults. Ollama serves that model at temperature 1,
and the client sent no `think` control. Sending `think: false` to the
OpenAI-compatible endpoint changes nothing — byte-identical reasoning output
with the field present or absent — and that endpoint ignores `num_ctx` too.

**Fix.** The client speaks Ollama's native `/api/chat`, which honours both, and
sends temperature 0, a seed, `think: false` and `num_ctx` on every call, never
relying on a server default.

**Evidence.** Same model, same prompt: 3/9 at the defaults, 8/9 with the three
controls set. `tests/test_inference_client.py` asserts all four are present on
every call. Commit of 2026-09-24, "explicit sampling on every call".

## 5. A consistent receipt, blocked

**Problem.** A real simplified receipt prints a total and the VAT inside it, and
no subtotal. The model copied the total into `subtotal`, and two arithmetic
rules then blocked a receipt whose numbers were consistent.

**Root cause.** The schema asks for a subtotal and the page does not have one.
A prompt line asking the model not to copy the total is a request, not a
guarantee.

**Fix.** After extraction, deterministically: when subtotal equals total, VAT is
positive and total − VAT is positive, the subtotal becomes total − VAT (Decimal,
two places), with its own provenance, `computed`, shown as "Derived". Its box
is dropped, since the old one was the total's, and it is sent for review rather
than marked settled. Amounts are compared as Decimals everywhere, so `2.30` and
`2.3` are one number.

**Evidence.** `tests/test_totals.py`;
`test_a_copied_receipt_total_is_stored_as_a_computed_subtotal`. Commit of
2026-09-30, "derive a receipt's copied subtotal".

## 6. The answer was printed on the page as a QR code

**Problem.** A receipt with no signed XML was read entirely by the model,
although ZATCA requires it to print a QR carrying the seller, VAT number,
timestamp, total and VAT.

**Root cause.** Nothing decoded it. The TLV parser existed; getting the payload
out of the page image did not.

**Fix.** `services/qr.py` rasterizes each page and decodes with OpenCV, which
was already installed and loads under this machine's code-integrity policy. The
five fields get provenance `qr`; the model's reading is kept beside them and a
warning fires when they differ; the subtotal follows from the QR's own total and
VAT. Signed XML still outranks the QR.

**Evidence.** The real contractor invoice, auto mode: 7/9 with QR reading off,
9/9 with it on, the QR read on 1 of 1 document, repeated twice. Synthetic set,
88 fields: text path 86 → 88, vision path 76 → 81. `tests/test_qr.py`. Commit
of 2026-09-30, "read the ZATCA QR off the page as a trusted source".

**Still open.** On one real receipt the QR's timestamp decoded as `0001-01-01`
and became the issue date. QR values are not sanity-checked; the mismatch
warning flagged it.

## 7. Half the receipts, sideways

**Problem.** Building the public-receipt evaluation, photos had to be wrapped
as scanned PDF pages. 48 of the 100 sampled photos are stored as landscape
pixels with an EXIF "rotate" flag.

**Root cause.** Embedding the raw JPEG in a PDF ignores the flag. A first test
checked only the page's shape and passed, because the page was portrait — with
the picture letterboxed sideways inside it.

**Fix.** The pixels are turned upright before wrapping. The test was
strengthened to check where a marked corner is drawn, watched failing, then
fixed.

**Evidence.** `test_a_photo_stored_sideways_is_turned_upright` in
`tests/test_coru_eval.py`. Commit of 2026-10-05, "score the local models on a
public receipt set". Found before any number was published; no run in
`docs/results.md` used the unrotated images.

## 8. Few-shot examples made the small model worse

**Problem.** Would two worked examples in the prompt improve the vision path?

**Root cause of the result.** With two invented receipts and their expected
output in the prompt, `qwen3.5:4b` returned every field null on 43 of 100
receipts; without them, on none.

**Fix.** None applied: `EXTRACTION_FEW_SHOT` exists and stays off. The examples
were not adjusted against the evaluation set, because that would tune the
prompt on the data it is scored on.

**Evidence.** `docs/results.md`, runs (b) and (c): 405/517 (78%) without,
224/517 (43%) with. Same model, images, context and seed.

## 9. "The bigger model scored 17%"

**Problem.** `qwen3.5:9b` on a Colab T4 scored 88/517 (17%) on the receipts
where the 4B model on a laptop scored 405/517 (78%).

**Root cause.** The prompt, not the model. It returned every field null on 76
of 100 receipts. Three explanations were tested rather than assumed:

* *The image does not arrive.* It does: the request costs 2,006 prompt tokens
  with the image and 1,005 without, on both models, and the 9B model answers a
  plain question about the picture.
* *The context is too small.* The same receipts come back empty at 8,192
  tokens.
* *The model cannot read these receipts.* Ten of the empty receipts, sent again
  with a bare three-field request: 30 of 30 fields filled, 27 of 30 correct.

The extraction prompt was written and adjusted against small models. It says
that returning null is correct, and the larger model over-obeys it.

**Fix.** Deliberately none. Re-tuning the prompt against the set it is scored
on would make the next number meaningless; the calibration needs a separate
development set (see Future work in the README).

**Evidence.** `docs/results.md`, "Laptop vs Colab". What the run does show is
the safety net: of the fields that were wrong, 97% were flagged by a rule and
98% were not shown green.

---

## Also fixed, briefly

* **Upload had never worked end to end.** The handler queued the pipeline
  before its own transaction committed, so the pipeline could not find the
  document. No test went through HTTP; driving a real upload did. Rule since: a
  handler that schedules background work commits first. `tests/test_upload.py`.
* **A byte-identical re-upload crashed the pipeline** on a unique constraint.
  The bytes are now hashed before anything is stored, and a resend returns the
  existing document.
* **The VAT-number rule rejected most real companies.** It required a digit
  that is in fact a branch digit, 0 for every head office. It now checks only
  what is public and stable, and was renamed from "checksum" to "format"
  because no checksum was ever verified.
* **A null required field showed green.** `REQUIRED_FIELD_MISSING` now makes it
  amber. `test_a_null_required_field_is_never_left_green`.
* **A correction erased page-level blockers.** Revalidation deleted every
  finding and re-created only rule results; a document blocked by an unreadable
  page became confirmable after any edit. Page findings now come from one
  function that both paths call. `tests/test_page_findings.py`.
* **A degraded blank page blocked a fully readable invoice.** It now blocks
  only when nothing is readable or a required field is still missing.
