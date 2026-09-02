# samples/

Real invoices used by the Phase 1 test suite.

## Nothing here is committed

`samples/*.pdf` and `samples/*.xml` are git-ignored. Real Saudi invoices carry
live TRNs, IBANs, supplier names and buyer addresses; they must never enter git
history, where they cannot be removed. Only this README is tracked.

## Naming convention

The tests classify samples by filename, so the name is load-bearing:

| Filename contains | Expected `extract_embedded_xml()` result |
| --- | --- |
| `ubl` or `compliant` | non-None — a PDF/A-3 with UBL 2.1 XML embedded |
| `scan` or `plain` | `None` — no embedded attachment |

Anything else is parsed on a best-effort basis and only asserted not to crash.

Examples:

    samples/invoice-compliant-ubl-001.pdf     -> must yield embedded XML
    samples/invoice-arabic-scan-001.pdf       -> must yield None

## Why the tests still pass with this directory empty

The suite has two layers.

1. **Synthetic fixtures**, built in-process by `backend/tests/fixtures.py`. These
   always run and always pass. Understand exactly what they prove: a round trip
   against *our own writer*. `fixtures.py` embeds an attachment with pypdf and
   `extract_embedded_xml` reads it back with pypdf. That confirms our name-tree
   walking and our UBL parsing are self-consistent. It does **not** confirm that
   we can read a PDF produced by ZATCA-certified e-invoicing software, which is
   the only thing that actually matters in production. Real generators differ in
   name-tree layout, use `/UF` over `/F`, attach via page-level
   `/Annots` `/FileAttachment` rather than the catalog, compress differently, and
   wrap the UBL in signed PDF/A-3 containers.

2. **Real samples**, parametrized over this directory. These fail loudly on a
   misclassification rather than skipping.

Until a real sample lands here, `test_a_real_zatca_sample_exists` is marked
`xfail`, so the gap shows up in every test run as an expected failure instead of
disappearing into a green bar.

## Getting a real sample

Generate a compliant UBL 2.1 invoice from the ZATCA Fatoora SDK sandbox, or take
a genuine Phase 2 invoice from a supplier and drop it in. Ideally add three to
five: at least one compliant PDF/A-3 with embedded UBL, and at least one plain
Arabic scan with no XML at all.
