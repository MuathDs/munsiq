# Munsiq — Project Context

Document Information Extraction SaaS for Arabic/English invoices, Saudi B2B (ZATCA).

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Pydantic v2, Alembic, PostgreSQL 16
- Frontend: Next.js 16 (App Router), TypeScript strict, Tailwind, TanStack Query
- Inference: Ollama, reached over its native API (`/api/chat` — not the
  OpenAI-compatible endpoint; see "Known issues"). Runs natively on Windows.
- Queue: Redis + arq. Storage: S3-compatible (MinIO locally).

## Platform
Windows, natively. Not WSL, not Docker-for-the-backend. Inference is Ollama, so
the Windows incompatibility that would have forced WSL does not apply.

Python is reached via the `py` launcher; the standalone `pip.exe` shim is blocked
by an Application Control policy. Install into the venv only:

    py -m venv backend/.venv
    backend/.venv/Scripts/python.exe -m pip install -e backend[dev]

## Scope
Portfolio project, not a product. Build phases 1, 2, a minimal 3+4, 5, and 7 of
the execution plan. Do NOT build 3.5, 5.5, 8, 9, 10 or 11 unless asked.
`document_parts` stays in the Phase 2 schema. Today the pipeline writes exactly one
part per document — index 0, `doc_type='invoice'`, spanning every page — so nothing
splits a file into documents (see "A PDF can hold more than one document", below).

## Deferred — not skipped
- **Dedicated low-privilege application role.** Still deferred, but the gap it
  left is now closed at the session layer.

  Supabase's `postgres` role has `rolbypassrls=true`, and `FORCE ROW LEVEL
  SECURITY` does not override that. So `session_scope()` in
  `app/db/session.py` issues `SET LOCAL ROLE` to `settings.DB_APP_ROLE`
  (default `authenticated` — no superuser, no BYPASSRLS) in the same
  transaction as the `app.current_org_id` GUC. Both are transaction-local.
  The application path is therefore subject to RLS, proven over HTTP by
  `tests/test_api_tenancy.py`.

  What remains: the connection still *authenticates* as a BYPASSRLS role, so a
  session opened outside `session_scope()` would run unconstrained. A dedicated
  LOGIN role makes the bypass unreachable rather than merely unused. See
  docs/db.md for the exact steps, including the sequence grants.

  HARD RULE: Alembic must never inherit the role switch — `authenticated`
  cannot run DDL. `alembic/env.py` builds its own engine on purpose.

- **Durable job queue (arq + Redis).** Deferred: no Docker on this machine, so
  no Redis. `POST /documents` returns 202 and runs the pipeline in a FastAPI
  BackgroundTask instead.

  The trade-off, stated plainly: **no retries and no durability across a
  restart.** If the process dies mid-document, that document stays unprocessed
  and nothing retries it. There is also no backpressure — concurrent uploads all
  run in-process.

  `process_document(org_id, document_id)` is a plain coroutine, so moving to arq
  is a call-site change rather than a rewrite. Revisit before anything resembling
  real volume.

- **Document classification.** Not built. Every document is read with the one
  tax-invoice schema, whatever it is, so the schema is applied to documents that
  cannot satisfy it. The real example: a marketplace *purchase summary*
  (ملخص المشتريات) carries no seller VAT number, no VAT amount and no tax-invoice
  structure at all, so its null seller TRN and null VAT are CORRECT, and its only
  amount is a tax-inclusive total that the schema's "subtotal" then invites the
  model to copy. `SUBTOTAL_EQUALS_TOTAL` and the tightened subtotal guideline
  contain the damage; they do not fix the cause, which is that nothing decides
  "what kind of document is this" before choosing what to ask for. With
  classification each kind would get its own schema, and a summary would not be
  asked for a TRN it cannot have.

- **ZATCA QR as a "Step Zero" for simplified (B2C) invoices.** Not built; recorded
  because it is the obvious next thing. A B2C simplified invoice has no UBL
  attachment, so Step Zero finds nothing and the model runs — but the invoice must
  still carry the mandatory ZATCA TLV QR, printed as an IMAGE. Decoding it gives
  seller name, TRN, timestamp, total and VAT total (tags 1-5) without the model,
  the same way the embedded UBL does for B2B. Seen on the first real invoice (a
  marketplace B2C receipt, 2026-09-21).

  What already exists: `decode_zatca_qr` in `app/services/ubl.py` parses the TLV,
  and `rules/zatca.py` already cross-checks tags 4 and 5 against the fields. What
  is missing is only getting the payload out of the page image, which needs a QR
  decoder that loads under this machine's WDAC policy (check before choosing one:
  it is the same constraint that shaped the OCR choice). Until then a simplified
  invoice is read by the model and the QR is not used as evidence.

- **Arabic OCR for image-only pages.** The OCR engine that loads under this
  machine's WDAC policy (RapidOCR) has zero Arabic characters in its recogniser,
  so image-only Arabic scans cannot be read. This is NOT silent: the page row
  records `text_source='ocr_unsupported_script'` and a validation_results row is
  written. Digital PDFs with a text layer — the common ZATCA case — are
  unaffected and handled exactly. See docs/ingestion.md to close it.

- **Real authentication (JWT).** Deferred. `get_current_org_id` in
  `app/api/deps.py` raises 501 rather than guessing, and never falls back to a
  header or query parameter — that value feeds the RLS GUC directly, so a
  caller-supplied one would let anyone pick a tenant.

  Until JWT lands, the frontend reaches the API through a **BFF layer**: Next.js
  route handlers and server components hold the org identity server-side and
  call FastAPI. The browser never sends a tenant id. This is a portfolio-scope
  decision — it keeps the hard rule intact without building an auth system.

  Replacing it is small and local: `get_current_org_id` starts verifying a
  bearer token and returning its org claim. Nothing downstream changes — not the
  session dependency, not the role switch, not a single policy. The BFF can then
  either forward the user's token or be removed entirely.

  EXCEPTION, by necessity: `GET /pages/image` is not behind the session
  dependency. An `<img src>` cannot carry a token, so that route authorizes
  itself with a short-lived HMAC signature covering tenant, document and page —
  the local-storage stand-in for an S3 presigned URL. The tenant there is
  *verified* against a signature only the server can produce, never *read* from
  the request. See `app/services/signed_urls.py`.

  SECOND EXCEPTION, same reasoning: `POST /documents` also accepts a signed
  `upload_token` (minted by `POST /documents/authorize`, which the BFF calls). It
  exists because document bytes must not stream through Next.js and a browser
  upload cannot carry the BFF secret. The token is bound to a *kind*, so an image
  token cannot write and an upload token cannot read; it expires in minutes; and
  a present-but-bad token is refused, never silently downgraded to the header path.

## Known issues — recorded

FIXED, and worth remembering why:

- **A byte-identical re-upload used to crash the pipeline** (IntegrityError on
  `UNIQUE(org_id, sha256)`, a 500 in the background task, an orphan row). Fixed
  2026-09-20: the bytes are hashed BEFORE anything is stored and a resend returns
  the existing document with 200. A failed or stalled earlier attempt is retried
  instead. See docs/ingestion.md, "The upload path".
- **`POST /documents` had never worked end to end.** The handler wrote through a
  yield-dependency session and then queued the pipeline; FastAPI >= 0.118 runs that
  dependency's teardown (the commit) after the response and background tasks, so
  the pipeline could not find the document. No test went through the HTTP path.
  RULE: a handler that schedules background work must own its transaction and
  commit before scheduling. `tests/test_upload.py::test_the_document_is_committed_
  before_the_pipeline_is_started` probes from the pipeline's side.
- **Arabic words came out in reverse order** (found on the first real invoice, a
  marketplace B2C receipt; fixed 2026-09-21). A vendor printed "شركة حلول نور للتسويق
  الإلكتروني" reached the model as "…نور حلول شركة". A text layer is a content
  stream, and a producer that draws an RTL line from its left end writes the words
  in visual order; MuPDF then puts each on a line of its own, so grouping by its
  lines cannot fix it. `pagetext._reading_order` regroups words into rows by
  position and orders each Arabic row from the x coordinates, so a producer that
  already wrote logical order is not reversed twice. Three limits, all on purpose:
  a row is only fused where Arabic is involved (an English page is byte-identical
  to before), the gap that fuses fragments is half a line height (a looser one
  fused adjacent table headers on the generated Arabic invoices), and left-to-right
  runs keep the stream's order. Whether a mixed row reads label-first or
  label-last follows the direction of the PAGE, not the row, because the text is
  flat and a value that precedes its label reads as the previous field's.
  `tests/test_pagetext_order.py`; the fixtures reproduce the mechanism because the
  real PDF is personal data and is not in the repository.
- **A value wrapped after a hyphen was rejoined with a space** ("SA7KXWTPB-" /
  "LQP3081947" read as "SA7KXWTPB- LQP3081947"; same invoice, fixed 2026-09-21).
  `pagetext.join_words` now joins without one, and grounding uses the same
  function so the joined value still finds its box. Deliberately narrow: the hyphen
  must follow a letter or digit, the next line must sit directly below and start
  with one, and must not be a label ending in a colon. Each half keeps its own
  word box.

- **A missed field looked green** (fixed 2026-09-21). A null for a field whose label
  is printed on the page was recorded as a correct null: `auto_validated`,
  confidence 1.0. Now `extraction/labels.py` checks the schema's labels and
  synonyms against the page with whitespace removed (the text layer can cut the
  words apart), and a hit makes the null `review_suggested`, confidence 0. A plural
  ("المشتريات" in a title) is not the label "المشتري". Synonyms are schema data.
- **A copied total became the subtotal** (fixed 2026-09-21). The guideline now says
  EXCLUDING VAT and that a lone tax-inclusive amount means the subtotal is null,
  and `SUBTOTAL_EQUALS_TOTAL` (warning) flags a subtotal equal to the total with
  no VAT stated. A stated VAT of 0.00 is a real zero-rated invoice and passes.
  A warning now also downgrades an `auto_validated` field to `review_suggested`.
- **The inference client could not have seen truncation** (2026-09-21). It sent no
  seed, discarded `usage`, and Ollama truncates an over-long prompt silently. It now
  sends `INFERENCE_SEED`, records token usage, and raises (without retrying) when
  prompt plus reply reaches `INFERENCE_NUM_CTX` or the reply stops at its length
  limit. Ollama's `/v1` endpoint IGNORES `num_ctx` (checked, 0.34.1): the context
  is set by Modelfile or `OLLAMA_CONTEXT_LENGTH`, and `INFERENCE_NUM_CTX` must be
  changed to match. It was not the cause of the misses that prompted this: those
  prompts were 1,142 and 1,460 tokens of 4,096.
- **Word segmentation was MuPDF's, and MuPDF's tokenizer is not reliable across
  producers** (2026-09-22). The Arabic-word-fragmentation entry below named the
  cause as "some text layers cut Arabic words apart" and left it open pending
  measured gaps from the (deleted, personal-data) real file. Building a diverse
  synthetic corpus instead of waiting on that file showed the real fault: not
  one producer's quirk, but `get_text("words")` itself, in both directions —

  * UNDER-segments: three Arabic words, correctly measured isolated-form
    glyphs, one real inter-word space, no artificial padding anywhere —
    `get_text("words")` returns **one** "word" for all three
    (`test_mupdf_words_tool_merges_real_gaps_into_one_word`).
  * OVER-segments: on the real invoice, Arabic tokens split disproportionately
    right after a letter that does not join forward.
  * Even plain `page.get_text()` (not the word tokenizer) drops the separator
    across a genuine ~300pt gap between two table cells on one of our OWN
    generated Arabic invoices — found by accident while fixing this, see
    `test_an_html_rendered_arabic_page_reads_correctly`.

  `pagetext._words_from_text_layer` no longer calls `get_text("words")` at
  all. It builds words itself from raw glyph positions
  (`page.get_text("rawdict")`), grouping characters by a gap compared against
  the width of the two glyphs either side of it — **never a fixed point
  size**, so the same ratio segments identically at 8pt and at 80pt
  (`test_the_same_ratio_is_judged_the_same_at_any_font_size`). An explicit
  space character always wins over the gap measurement. The threshold is
  looser right after a letter that never joins forward (`NON_JOINING_LETTERS`
  — the alef family, دذ, ر ز, و), because a shaping-unaware renderer can leave
  a positioning seam exactly there; the allowance is bounded, so a real word
  boundary in that position still splits
  (`test_a_true_inter_word_gap_after_a_non_joining_letter_still_splits`). None
  of the four constants involved were calibrated against the deleted file —
  only against measured font metrics and the general shape of the bug class.

  Checked directly, per CLAUDE.md's own hard rule about not repeating the
  fine-tune's mistake: our OWN row-fusion/column-split code
  (`_fuse_into_rows`, `_split_at_gaps`) was NOT the source. Those functions
  only reorder already-built words into rows and cut a fragment at a real
  column gap; they never look inside a word, so they cannot turn one word
  into several letters (`test_reading_order_never_changes_the_word_count`).
  `scripts/text_layer_report.py`'s numbers were always describing MuPDF's
  tokenizer output, not ours.
- **The TRN rule was wrong — my error in the original plan** (fixed
  2026-09-23). It required the 11th digit to be '1'. A Saudi TRN's 11th digit
  is the first of three BRANCH digits (000 = head office), '0' for every head
  office, so that rule rejected most real Saudi companies and blocked a real
  invoice's two otherwise-valid TRNs (both
  head offices). `validate_trn` now checks only what is public and stable: 15
  digits, starting and ending with 3. The check digit's algorithm (position
  10) is not published anywhere, so nothing here has ever verified a
  checksum — the rule is renamed `TRN_FORMAT` (from `TRN_CHECKSUM`)
  everywhere, messages included, because "checksum" claimed a verification
  this code cannot do. `TRN_TAX_TYPE_UNEXPECTED` (new, warning) flags a
  well-formed TRN whose last two digits are not '03' (VAT) — informational
  only, since ZATCA publishes no registry to check other tax types against.
  The Phase 1 fixture also dodged the old rule: `SELLER_TRN` in
  `tests/fixtures.py` was `310122393510003` where the official ZATCA sample is
  `310122393500003` — restored, and it is now a valid case everywhere it
  appears, including `samples/test/06_invalid_trn.pdf`'s companion (that one
  is still invalid, now because it does not end in 3, not because of a digit
  that was never really required).
- **A degraded filler page blocked confirmation on its own.** A page with no
  usable text (`OCR_SCRIPT_UNSUPPORTED`) was an unconditional blocking error —
  even a nearly blank trailing page on an otherwise fully-readable invoice.
  Fixed 2026-09-23: it blocks only when the document as a whole has nothing
  readable, or a REQUIRED field is still missing after extraction (a plausible
  sign the value this page was supposed to carry never arrived). A blank page
  next to a fully-readable invoice now warns instead of refusing confirmation.
  `tests/test_pipeline.py::test_a_degraded_filler_page_warns_instead_of_
  blocking`. On the real invoice that surfaced this, the fix does not fully
  clear the block — a required field (`subtotal`) is genuinely still missing,
  so `OCR_SCRIPT_UNSUPPORTED` correctly stays an error under the new rule too.
  That is the fix working as intended: it now blocks for the true remaining
  reason, not an unrelated blank page.
- **Duplicate React keys when a rule fires on two fields.** `rule_code` alone
  was the key for the blocker banner, the blocking-findings panel and each
  field's own findings list — the TRN rule firing on both `seller_trn` and
  `buyer_trn` on the same real invoice collided ("Encountered two children
  with the same key, TRN_CHECKSUM"). Not TRN-specific: any rule firing twice
  reproduces it. `validation_results` already has its own `id`; `ValidationFinding`
  now carries it end to end (`GET /annotations/{id}`, the PATCH corrections
  response, and the CONFIRM 409 body), and every list in the workspace keys on
  it — `BlockerList`, `FieldRow`'s per-field findings, and the confirm
  banner's blocker pills, which used to render bare rule-code strings and
  now render one pill per finding. `revalidate_annotation` returns the
  inserted ids alongside its report (`RevalidateOutcome`) since `RuleResult`
  itself is computed in memory before anything is persisted.
  `tests/test_confirm_endpoint.py::test_the_same_rule_firing_twice_gives_
  each_blocker_its_own_id`, `tests/test_workspace_api.py::test_two_findings_
  of_the_same_rule_have_distinct_ids`.
- **The OpenAI-compatible endpoint silently ignored `think`, and Ollama's
  hybrid-reasoning model defaults to temperature 1** (fixed 2026-09-24).
  Manual, same-bare-prompt tests on the contractor invoice: `qwen2.5vl:3b` scored
  7/9; `qwen3.5:4b` at ITS Ollama defaults scored 3/9, inventing computed
  values (a VAT of `527.8549999`, a wrong TRN digit) — because Ollama defaults
  `qwen3.5` to temperature 1, checked directly via `/api/show`
  (`temperature: 1, presence_penalty: 1.5, top_k: 20, top_p: 0.95`), and
  because the client sent no `think` control at all. The SAME model, SAME
  prompt, with temperature 0, a fixed seed and `think: false` sent explicitly,
  scored 8/9 — only one dropped word in a name. Sending `think: false` to
  `/v1/chat/completions` changes nothing: checked directly, byte-identical
  `reasoning` output and completion-token count with the field present or
  absent, and `chat_template_kwargs: {"enable_thinking": false}` (vLLM's own
  spelling of the same control) is silently accepted and ignored too. Ollama's
  NATIVE `/api/chat` honours `think` correctly (checked directly: no
  `reasoning` field at all, a fraction of the completion tokens) — so
  `extraction/client.py` no longer speaks the OpenAI wire format at all,
  ending the deliberate choice recorded in ADR 002. Found in the process: the
  native endpoint also honours `options.num_ctx`, which the OpenAI-compatible
  one never did either (checked directly: a small `num_ctx` measurably
  truncates `prompt_eval_count`) — so `INFERENCE_NUM_CTX`/`VISION_NUM_CTX` are
  now sent as a real request, not just a value hoped to match the server's own
  configuration, and the post-hoc overflow guard in `client.py` is a backstop
  rather than the only line of defense. Every call now sends temperature,
  seed, `think` and `num_ctx` explicitly, never relying on a server default —
  `tests/test_inference_client.py` asserts all four are present and correct on
  every call, images or not, json_mode or not. `qwen3.5:4b` is licensed Apache
  2.0 (checked via `ollama show qwen3.5:4b` before adopting it) and is now
  `VISION_MODEL`'s default, replacing `qwen2.5vl:3b` — it also has vision
  capability itself (`ollama show` lists `vision` alongside `thinking`),
  which is how the same bare-prompt comparison was possible on one model.
- **A null REQUIRED field showed green** (fixed 2026-09-25). On the contractor
  invoice the text path returned null for the required `subtotal` and wrote it
  `auto_validated`. The silent-miss check (`extraction/labels.py`) never fired:
  the page labels its subtotal "المجموع" ("sum"), a generic word no subtotal
  synonym can safely include because totals use it too. No rule looked at
  `required` at all, and the document stayed blocked only because its blank
  page 2 happened to trigger `OCR_SCRIPT_UNSUPPORTED` — a clean one-page invoice
  would have looked finished. `REQUIRED_FIELD_MISSING` (new, WARNING,
  `rules/completeness.py`) flags every required field with no non-blank value,
  one finding per field, so the engine's existing warning path moves it
  `auto_validated` → `review_suggested` in the pipeline and on every
  revalidation. It reads `required` from the schema — `ValidationContext.
  required_keys`, filled by `build_context` from `FieldSpec.required` and by
  `revalidate._schema_keys` from the annotation's own stored schema with the
  same `bool()` reading, so the two paths cannot disagree. A warning, not an
  error: a field genuinely absent from the document can still be confirmed
  after a person has looked. Rule count 18 (10 errors, 8 warnings).
  `tests/test_validation_rules.py` (the REQUIRED_FIELD_MISSING section),
  `test_pipeline.py::test_a_null_required_field_is_never_left_green`,
  `test_workspace_api.py::test_revalidation_turns_a_green_null_required_field_amber`.

  Found alongside, NOT fixed — both are pre-existing and recorded rather than
  fixed out of scope:

  * **Revalidation erases page-level findings, blocking ones included.**
    `revalidate_annotation` deletes EVERY `validation_results` row and
    re-inserts only what the rule registry produces. `OCR_SCRIPT_UNSUPPORTED`,
    `OCR_ENGINE_UNAVAILABLE`, `PAGE_TEXT_EMPTY` and `PAGE_TEXT_UNAVAILABLE` are
    written by `pipeline._record_findings`, not by rules, so they do not come
    back: a document blocked by an unreadable page becomes confirmable after a
    reviewer corrects any unrelated field. Seen directly: revalidating the
    contractor invoice (to confirm the fix above) removed its
    `OCR_SCRIPT_UNSUPPORTED` error, and its `blockers` went to `[]`. The fix is
    to delete only rows whose `rule_code` is in the registry, or to recompute
    the page findings on revalidation from the stored `pages.text_source`.
  * **A reviewer's `delete` never takes effect.** The corrections endpoint
    writes `value_final = NULL` for a delete, and NULL there means "never
    edited" to both `revalidate` and the UI's `currentValue()`, so the original
    extracted value comes back. Found by reading the code, not by a failing
    test. Needs a representation for "deliberately emptied" (an empty string,
    or a flag) — until then REQUIRED_FIELD_MISSING cannot see a reviewer's
    deletion, only an extracted null or a field cleared to an empty string.
- **The prompt cache changes results.** The same prompt gave `Riyal (SAR)` cold and
  `Riyal (R. s)` with the previous request's 1,141 tokens cached, five runs each,
  and a fixed seed changed nothing (greedy decoding). Consecutive documents share
  the system prompt and field list, so every second upload is a warm run.
  Not fixed: Ollama's `/v1` offers no way to bypass the cache.

- **A PDF can hold more than one document.** The first real invoice was one file
  with two: a marketplace purchase summary on page 1 and the marketplace tax invoice on
  page 2, with different totals. The pipeline treats a file as one document —
  `document_parts` gets a single part spanning every page — and the model is handed
  all pages as one prompt, so which total it returns is a matter of which page it
  weighs more. It happened to pick page 2 (the right one); nothing
  guarantees that, and nothing tells the reviewer a second document was there.
  This is real-world evidence for the deferred `document_parts` work (splitting a
  file into parts, one annotation each). NOT built — recorded, per the scope
  rules. Until it is, a multi-document file is a known way to get a confidently
  wrong total.

- **A stalled document is only detected by age.** A document with no annotation
  after `STALLED_AFTER_S` (15 min) is shown as `stalled`; nothing retries it
  automatically. Re-uploading the same file is the retry. This is the durable-queue
  trade-off above, made visible rather than fixed.
- **Arabic dates in an RTL PDF do not always ground.** MuPDF splits a date like
  `2026-04-09` into separate words (`2026`, `04`, `09`) inside an RTL run, so no
  word window matches the value and it gets no bounding box (seen on both
  generated Arabic invoices, 2026-09-20). The value itself is unaffected.
- **The UBL in generated test invoices is ZATCA-shaped, not certified.** Only a
  real sample proves the parser against certified output (see samples/README.md).
- **Text and vision disagree on 6 of 9 fields for the one real invoice with no
  usable ground truth yet.** 2026-09-23, the contractor invoice (behind annotation
  `995412b3`, no embedded UBL): both paths, run through the FULL
  schema-conditioned prompt with field guidelines (not the bare prompt used for
  the manual test that motivated building vision at all — see below), extracted
  a value for 8 of 9 header fields, but the two paths AGREED on only 3
  (`invoice_number`, `issue_date`, `seller_trn`); they disagreed on both names,
  `buyer_trn`, and all three totals-block fields. This is an AGREEMENT count,
  not a correctness count — no hand-entered ground truth exists for this
  document (`scripts/eval_set.py` exists to build one; none has been loaded
  yet) — so it does NOT show which path is right, only that schema-conditioned
  vision and schema-conditioned text read this real invoice quite differently
  from each other. That is itself evidence for the deferred **document
  classification** entry above: a marketplace-summary-shaped first page or a
  totals block the guidelines still under-specify could easily explain the
  totals-field disagreement on its own. Contrast with the user's own earlier
  manual test (a BARE prompt, no field list, sent straight to `qwen2.5vl:3b`):
  that got 7 of 9 right by eye, with both errors isolated to the totals block.
  Whether the schema-conditioned guidelines help or hurt the totals confusion
  the user's manual test already found is exactly the open question — this run
  does not answer it, because there is nothing to score either path against yet.
- **Ground truth now exists for the contractor invoice, and the schema-conditioned
  vision path scores 5/9 against it** (2026-09-24, `scripts/eval_set.py`,
  eval set `contractor-invoice`, `--mode vision`, `VISION_MODEL=qwen3.5:4b`,
  temperature/seed/think all explicit — see the fix above). The ENTIRE totals
  block is correct (subtotal, VAT, total all match), plus `invoice_number` and
  `issue_date` — this is the totals-block confusion from the user's bare-prompt
  manual test NOT reproducing here, which is itself informative: schema
  guidelines may be exactly what fixed it. Both wrong: `seller_name` and
  `buyer_name` (not fuzzy-close misses — checked directly with rapidfuzz
  against the ground truth, both under 50% similarity, so not a
  dropped-word case like the manual bare-prompt test's buyer name). And
  `seller_trn`/`buyer_trn` came back SWAPPED with each other — checked
  directly (`seller_trn`'s answer matched `buyer_trn`'s ground truth and vice
  versa) rather than assumed from the 0% scores alone. A swapped
  seller/buyer pair on a document with two similarly-formatted registration
  blocks is exactly the kind of error the deferred **document classification**
  entry above would not fix (it is not a wrong-schema problem) — this looks
  more like the prompt or guidelines not anchoring which registration block is
  the seller's own letterhead versus the "invoice to" block. Worth a targeted
  guideline tightening, not built here — this is one document, deterministic
  and reproduced identically on a second run, but one document is one
  document, not a pattern.

## Hard rules
- Multi-tenant. EVERY table has org_id. Postgres RLS enforces isolation.
- NEVER read tenant identity from a request body or query param. Only from the verified JWT.
- All money is Decimal, never float. All timestamps are TIMESTAMPTZ, stored UTC.
- Bounding boxes are normalized floats 0.0-1.0, never pixels.
- Model output is untrusted. Validate every field against JSON Schema + deterministic rules.
- The UI is bilingual ar/en with full RTL. Use CSS logical properties, never left/right.
- No secrets in code. Everything through pydantic-settings / .env.

## Legacy — and the one rule that survives it
- The prototype (pandas -> Excel batch reporter, the LoRA fine-tune notebook,
  generated datasets) lives in `legacy/`. Not maintained; nothing in `backend/`
  or `frontend/` imports from it. See `legacy/README.md`.
- The prototype's dashboard UI shell (sidebar, stat cards, dropzone, table) was
  UNFROZEN on 2026-09-20 and is now the app shell, wired to the FastAPI backend
  through the BFF. Its direct-to-Ollama route handlers (`api/extract`,
  `api/invoices/*`) and their plumbing (`munsiqModel.ts`, `jobStore.ts`) are
  deleted. It follows every rule in this file, including the RTL rule.
- HARD RULE, unchanged: no frontend code calls a model endpoint. All inference
  goes through the FastAPI backend.
- Inference is reached ONLY via `settings.INFERENCE_BASE_URL`
  (default `http://localhost:11434`, Ollama's origin — no `/v1`). Never
  hardcode a model URL.

## Conventions
- Backend: ruff + mypy strict. Tests with pytest + pytest-asyncio.
- Frontend: eslint + prettier. Components in PascalCase files.
- Conventional commits.

## Do not
- Do not stream document bytes through Next.js. Use presigned URLs.
- Do not add dependencies without saying why in the commit message.
- Do not create files outside backend/, frontend/, infra/, docs/, samples/.
  (`legacy/` is a read-only archive; do not add to it.)
- Do not commit real invoices. samples/*.pdf and samples/*.xml are git-ignored
  because they carry live TRNs, IBANs and supplier names.
