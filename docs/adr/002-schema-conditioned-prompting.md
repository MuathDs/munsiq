# ADR 002 — Schema-conditioned prompting, not a fine-tune

**Status:** Accepted · **Date:** 2026-09-19 (recorded; decided during Phase 3+4)

## Context

This repository began with `munsiq-extractor`, a LoRA fine-tune of a small model
on synthetic bilingual procurement data. It worked, in the narrow sense: it
emitted five fixed columns.

That is also its defect. The field list lived in the weights. A tenant who
wanted a sixth field — a cost centre, a project code, an LPO reference — needed
a retraining run, a new adapter and a redeploy. Different customers want
different fields on the same document type, and an AP department's schema
changes on a Tuesday because Finance asked for something.

## Decision

The field list is **input**, read from the database at request time, and the
model is a general instruct model.

* `extraction_schemas.definition` holds the fields: key, type, `label_ar`,
  `label_en`, `required`, a confidence threshold, and a natural-language
  `guideline` saying what counts and what does not.
* `build_user_prompt` renders that list into the prompt on every call. Nothing
  in the codebase hardcodes a field key.
* Inference goes to Ollama's native API (`INFERENCE_BASE_URL`, Ollama locally)
  running a general model — `qwen2.5:7b-instruct` by default, explicitly
  **not** the old fine-tune. Native, not the OpenAI-compatible endpoint this
  used before 2026-09-24: that endpoint silently ignores both `num_ctx` and
  `think`, the latter discovered when a hybrid-reasoning vision model
  (`qwen3.5:4b`) kept a chain-of-thought running no matter what was sent —
  see `extraction/client.py`.
* The same rows drive the review UI's labels and the export's labels, so a
  schema edit changes the prompt, the screen and the export together.
* Model output is untrusted: coerced to a known shape, grounded against page
  text, then judged by the deterministic rules ([ADR 004](004-rls-force-and-negative-control.md)
  covers isolation; validation is `docs/validation.md`).
* Correct nulls are persisted. A model answering "not present" is a negative
  example worth keeping, and a corpus of only positives cannot teach absence.

## Consequences

**Good.** Adding a field is an `UPDATE` on one row — no retrain, no redeploy.
Multi-tenant schemas cost nothing extra. The prompt is inspectable: you can read
exactly what the model was asked.

**Bad / limits.**

* Prompt length grows with the schema. `select_relevant_fields` exists as the
  seam for retrieving a subset on large schemas and deliberately does not
  implement retrieval yet — it returns the full list.
* A 7B general model is weaker per-field than a well-trained extractor on the
  exact fields it was trained for. The system compensates with grounding,
  confidence and deterministic validation rather than with model quality.
* Variable-length arrays (line items) from a 7B model are a different problem;
  the model path does not attempt them.

## Alternatives considered

* **Keep fine-tuning, one adapter per tenant.** Rejected: per-tenant training
  and hosting costs to solve a problem a prompt solves.
* **Constrained decoding against a JSON Schema.** Attractive and compatible
  with this decision — the schema row could generate the grammar. Not built;
  the current guard is coercion plus validation.

## See also

`app/services/extraction/prompts.py`, `app/services/extraction/runner.py`,
`backend/scripts/seed_demo.py`, [ADR 001](001-xml-first-extraction.md).
