# ADR 003 — Text layer primary, OCR only as a fallback

**Status:** Accepted · **Date:** 2026-09-19 (recorded; decided during Phase 3+4)

## Context

A ZATCA Phase 2 invoice that arrives as PDF/A-3 was produced by a billing
system, not a scanner. It carries a real text layer: exact characters with exact
coordinates. Running OCR over it would convert a perfect signal into a lossy
one, then charge for the privilege.

Some documents genuinely are scans, and those need OCR. The engine that loads on
this machine under its WDAC code-integrity policy is RapidOCR, whose bundled
recogniser contains Chinese and English characters and **zero Arabic**.

## Decision

Per page: use the text layer when it exists; fall back to OCR only where there
is none; and when the fallback cannot do the job, say so loudly in the data.

* `extract_page_text` reads words with boxes from the PDF text layer via
  PyMuPDF and records `text_source='text_layer'`.
* A page with no text layer goes to OCR, recorded as `text_source='ocr'`.
* A page with no text layer whose content is Arabic is recorded as
  `text_source='ocr_unsupported_script'`, and a `validation_results` row is
  written against the annotation. It is an error-severity finding, so it is
  visible in the review UI rather than looking like a blank page.
* Grounding matches extracted values against text-layer words to produce
  normalized 0.0–1.0 bounding boxes (never pixels), which is what lets the
  review overlay point at a value on the page.

## Consequences

**Good.** The common ZATCA case is exact and cheap. Coordinates come free with
the text, so grounding is a string-match problem rather than a vision one.

**Bad / limits.**

* **Image-only Arabic scans cannot be read.** This is a real hole, not a
  rounding error, and it is the reason the failure is recorded per page rather
  than swallowed: a reviewer sees "this page's script is not supported", not an
  empty result that looks like an empty page.
* Text-layer quality varies. Some generators emit soft hyphens (U+00AD) or
  ligatures that break naive matching; normalization handles the cases seen so
  far, and each new one is a bug fix, not a redesign.
* OCR confidence is not comparable to text-layer certainty; the two share a
  `confidence` column, and only provenance distinguishes them.

## Alternatives considered

* **OCR everything for uniformity.** Rejected: it throws away exact characters
  and exact coordinates, and would make the Arabic gap universal instead of
  confined to scans.
* **A vision-language model over page images.** The seam exists
  (`EXTRACTION_USE_VISION`, page images passed to the runner) and is off by
  default: on this hardware it is slower and no better on documents that
  already carry their text.
* **A different OCR engine with Arabic.** The right fix for the gap. Blocked
  here by the local code-integrity policy, not by the design — see
  `docs/ingestion.md` for what closing it involves.

## See also

`app/services/pagetext.py`, `app/services/ocr.py`,
`app/services/extraction/grounding.py`, `docs/ingestion.md`.
