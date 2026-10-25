// Regenerate src/commands.js from the firmware header, the one source of truth:
//   node scripts/gen-commands.mjs          (test/commands.test.js fails when stale)
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = new URL("../../", import.meta.url);
const HEADER = fileURLToPath(new URL("src/esplink/commands.h", root));
export const OUT = fileURLToPath(new URL("js/src/commands.js", root));

export function generate(text = readFileSync(HEADER, "utf8")) {
  const ints = new Map();
  const resolve = (e) => {
    let m;
    if (/^(0x[0-9a-f]+|\d+)$/i.test(e)) return Number(e);
    if ((m = e.match(/^CMD\((\w+),\s*(0x[0-9a-f]+|\d+)\)$/i)) && ints.has(m[1]))
      return (ints.get(m[1]) << 8) | Number(m[2]);
    if ((m = e.match(/^\(1U?L?\s*<<\s*(\d+)\)$/))) return 2 ** Number(m[1]);
    if ((m = e.match(/^\((\w+)\s*([-+])\s*(\d+)\)$/)) && ints.has(m[1]))
      return ints.get(m[1]) + (m[2] === "-" ? -1 : 1) * Number(m[3]);
    return undefined;
  };
  const defines = [...text.matchAll(/^#define\s+(\w+)\s+(.+?)\s*(?:\/\/.*)?$/gm)];
  for (let pass = 0; pass < 3; pass++)  // forward refs (CMD -> MOD_*) settle in passes
    for (const [, name, raw] of defines)
      if (!ints.has(name)) {
        const v = resolve(raw.trim());
        if (v !== undefined) ints.set(name, v);
      }
  const status = [...text.match(/enum\s+Status\s*:\s*uint8_t\s*\{([\s\S]+?)\}/)[1]
    .matchAll(/ST_(\w+)\s*=\s*(0x[0-9a-f]+|\d+)/gi)].map(([, n, v]) => [Number(v), n]);

  const chips = [...text.match(/enum\s+ChipModel\s*:\s*uint8_t\s*\{([\s\S]+?)\}/)[1]
    .matchAll(/CHIP_(\w+)\s*=\s*(0x[0-9a-f]+|\d+)/gi)].map(([, n, v]) => [Number(v), n]);
  const hex = (v) => (v > 9 ? "0x" + v.toString(16).toUpperCase() : String(v));
  return [
    "// GENERATED from src/esplink/commands.h by scripts/gen-commands.mjs — do not edit.",
    ...[...ints].map(([n, v]) => `export const ${n} = ${hex(v)};`),
    `export const STATUS = { ${status.map(([v, n]) => `${v}: "${n}"`).join(", ")} };`,
    `export const CHIP = { ${chips.map(([v, n]) => `${v}: "${n}"`).join(", ")} };`,
    "",
  ].join("\n");
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  writeFileSync(OUT, generate());
  console.log("wrote", OUT);
}
