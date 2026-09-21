# Munsiq — Project Context

Document Information Extraction SaaS for Arabic/English invoices, Saudi B2B (ZATCA).

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Pydantic v2, Alembic, PostgreSQL 16
- Frontend: Next.js 16 (App Router), TypeScript strict, Tailwind, TanStack Query
- Inference: Ollama, reached over its OpenAI-compatible API. Runs natively on Windows.
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

STILL OPEN:

- **Some text layers cut Arabic words apart.** The cause of the missed buyer name on
  the second real invoice, a marketplace purchase summary. Its text layer split
  words after non-joining letters: 40% of the Arabic tokens were single letters and
  none began with the definite article, so the model lost its field labels. On a
  two-column layout (labels in one row, values in the next) it returned null for the
  buyer and put the buyer's text into the seller. Reproduced with invented text:
  the same page with whole words is read correctly, 3 runs of 3. Sampling and
  context were ruled out (temperature 0; cold runs identical; 1,142 of 4,096 tokens).
  NOT fixed: whether MuPDF or the producer cuts the words, and at what gap, needs
  measured gaps from the real file, and the file is personal data that was not
  opened. `TEXT_LAYER_FRAGMENTED` (warning) now says so on the page, and the
  silent-miss rule flags the resulting nulls. To close it: run
  `scripts/text_layer_report.py <pdf>` on such a file (numbers only, no text) and
  join fragments whose gap is below the measured word-gap floor.
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
  (default `http://localhost:11434/v1`). Never hardcode a model URL.

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
