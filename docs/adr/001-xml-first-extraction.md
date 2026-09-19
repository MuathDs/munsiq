# ADR 001 — XML first, model second (Step Zero)

**Status:** Accepted · **Date:** 2026-09-19 (recorded; decided during Phase 3+4)

## Context

Under ZATCA's Phase 2 (Integration) e-invoicing rules, a Saudi standard tax
invoice is generated as UBL 2.1 XML, cleared by ZATCA, and commonly shared with
the buyer as a PDF/A-3 carrying that XML as an embedded attachment. The XML is
what the seller cryptographically signed and filed. The PDF page is a rendering
of it for humans.

Every generic invoice-OCR product treats such a file as an image to be read. On
a compliant Saudi invoice that is throwing away the answer: the document already
contains its own structured data, exactly, signed.

## Decision

Look for the embedded XML **before anything else**, and when it is there, take
the fields from it and never call the model.

* `extract_embedded_xml` walks both places the spec allows — the catalog's
  `/Names /EmbeddedFiles` tree and page-level `/FileAttachment` annotations —
  because real-world generators disagree about which to use.
* Parsed values are written with `source='ubl_xml'`, `confidence=1.0`,
  `validation_state='auto_validated'`. Header fields and invoice lines both.
* The model is not called at all on this path. Not called and discarded —
  not called.
* When the model *does* run (no attachment) and later disagrees with an XML
  value, the XML wins and the disagreement is recorded as `XML_PDF_MISMATCH`
  for a human to resolve. A model reading never overwrites a signed one.
* Grounding still runs over UBL values, but only to find **where** a value is
  printed so the review overlay can point at it. A box never changes
  provenance, and a value the page does not print simply gets no box.

## Consequences

**Good.** Zero GPU cost and zero hallucination risk on the compliant path; the
values are exact rather than probable. Measured on the demo invoice: 0 model
calls, and 9 of 11 header fields located on the page for the overlay.

**Bad / limits.**

* Only helps when the attachment is present. Scans and plain PDFs still need
  the model path, with everything that implies.
* We parse the XML; we do **not** verify its signature. We are on the receiving
  side — validating the seller's stamp is ZATCA's job, and claiming otherwise
  would be security theatre. "Signed" in this codebase means "came from the
  attachment the seller signed", not "we checked the cryptography".
* A UBL value that is not printed on the page (an Arabic legal name on an
  English-printed invoice) gets no bounding box. That is a real signal, left
  visible rather than faked.
* Line items come from the XML only. The model path yields no line items.

## Alternatives considered

* **Always run the model, then compare against the XML.** Rejected: it spends a
  GPU to produce a worse answer, and invites "the model said X" to compete with
  a signed value.
* **Read only the QR code.** The ZATCA QR carries seller name, VAT number,
  timestamp and totals — useful, and used as a cross-check — but it is a
  summary, not the invoice.

## See also

`app/services/ubl.py`, `app/services/pipeline.py`, `docs/ingestion.md`,
[ADR 002](002-schema-conditioned-prompting.md).
