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
`document_parts` stays in the Phase 2 schema even though nothing populates it —
two lines now, no migration later.

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

## Hard rules
- Multi-tenant. EVERY table has org_id. Postgres RLS enforces isolation.
- NEVER read tenant identity from a request body or query param. Only from the verified JWT.
- All money is Decimal, never float. All timestamps are TIMESTAMPTZ, stored UTC.
- Bounding boxes are normalized floats 0.0-1.0, never pixels.
- Model output is untrusted. Validate every field against JSON Schema + deterministic rules.
- The UI is bilingual ar/en with full RTL. Use CSS logical properties, never left/right.
- No secrets in code. Everything through pydantic-settings / .env.

## Deprecated paths — do not extend or imitate
- `frontend/src/app/api/extract` and `frontend/src/app/api/invoices/*` call
  Ollama directly from Next.js route handlers. Legacy prototype.
  Keep working, do not delete, do not extend.
- `src/data_pipeline/` is the legacy Ollama -> pandas -> Excel path.
  Same status.
- HARD RULE: no NEW frontend code calls a model endpoint directly.
  All inference goes through the FastAPI backend.
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
- Do not commit real invoices. samples/*.pdf and samples/*.xml are git-ignored
  because they carry live TRNs, IBANs and supplier names.
