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
