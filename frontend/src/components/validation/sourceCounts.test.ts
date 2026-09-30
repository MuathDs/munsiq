/**
 * Who read the invoice: the header's source chips count the fields each
 * reader filled. Run with `npm test` (Node's own runner, which strips the
 * types itself — no test framework to install).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { countSources, SOURCE_ORDER } from "./sourceCounts.ts";

type Field = Parameters<typeof countSources>[0][number];

function field(source: Field["source"], value: string | null = "x"): Field {
  return { source, value_extracted: value };
}

test("each reader is counted by the fields it filled", () => {
  const counts = countSources([
    field("ubl_xml"),
    field("ubl_xml"),
    field("qr"),
    field("qr"),
    field("qr"),
    field("vlm"),
    field("computed"),
  ]);
  assert.deepEqual(counts, { xml: 2, qr: 3, model: 1, computed: 1 });
});

test("a field the reader returned empty was not filled by it", () => {
  const counts = countSources([field("vlm", null), field("vlm", "  "), field("vlm", "INV-1")]);
  assert.equal(counts.model, 1);
});

test("a reader that filled nothing counts zero, so its chip can be dimmed", () => {
  assert.deepEqual(countSources([]), { xml: 0, qr: 0, model: 0, computed: 0 });
});

test("a reviewer's value and an unextracted field belong to no reader", () => {
  const counts = countSources([field("human"), field("ocr_rule"), field(null)]);
  assert.deepEqual(counts, { xml: 0, qr: 0, model: 0, computed: 0 });
});

test("chips read in order of authority: signed XML, QR, model, derived", () => {
  assert.deepEqual(SOURCE_ORDER, ["xml", "qr", "model", "computed"]);
});
