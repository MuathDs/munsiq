#!/usr/bin/env node
/**
 * Fail the build on physical CSS direction utilities in new code.
 *
 * RTL is structural here, not a theme. `ml-4` pins a margin to the left in both
 * directions; `ms-4` follows `dir`. One of those mirrors correctly for an Arabic
 * reviewer and the other silently does not, and the bug is invisible to anyone
 * testing in English.
 *
 * NO EXCLUSIONS. The prototype dashboard used to be listed here as frozen legacy.
 * It is now the app shell and is held to the same rule as everything else; a rule
 * with a carve-out for the oldest code is a rule that quietly stops applying.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

// fileURLToPath, not URL.pathname: this repo lives under a directory with a
// space in its name, which pathname returns percent-encoded.
const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SRC = join(ROOT, "src");

/**
 * `border-s-*` / `border-e-*` are logical and must not be caught by the
 * `border-...-left` style patterns, so the physical list is explicit.
 */
const PATTERNS = [
  { re: /\bm[lr]-[\w.[\]/-]+/g, hint: "use ms-/me-" },
  { re: /\bp[lr]-[\w.[\]/-]+/g, hint: "use ps-/pe-" },
  { re: /\b(?:left|right)-[\w.[\]/-]+/g, hint: "use start-/end-" },
  { re: /\btext-(?:left|right)\b/g, hint: "use text-start/text-end" },
  { re: /\bborder-[lr](?:-[\w.[\]/-]+)?(?![\w-])/g, hint: "use border-s-/border-e-" },
  { re: /\brounded-[tb]?[lr](?:-[\w.[\]/-]+)?(?![\w-])/g, hint: "use rounded-*s-/rounded-*e-" },
];

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) yield* walk(full);
    else if (/\.(tsx?|css)$/.test(full)) yield full;
  }
}

let failures = 0;
for (const file of walk(SRC)) {
  const rel = relative(ROOT, file);
  const lines = readFileSync(file, "utf8").split("\n");
  lines.forEach((line, index) => {
    // A rule that flags its own documentation is a rule people delete.
    if (line.trimStart().startsWith("*") || line.trimStart().startsWith("//")) return;
    for (const { re, hint } of PATTERNS) {
      re.lastIndex = 0;
      for (const match of line.matchAll(re)) {
        failures += 1;
        console.error(
          `${rel}:${index + 1}  physical property "${match[0]}" — ${hint}`,
        );
      }
    }
  });
}

if (failures > 0) {
  console.error(
    `\n${failures} physical direction ${failures === 1 ? "utility" : "utilities"} found. ` +
      `RTL must mirror without per-locale branches.`,
  );
  process.exit(1);
}

console.log("logical properties: clean");
