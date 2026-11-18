// M1 d: the import page's .xlsx reader, checked against a file openpyxl wrote (fixtures/make_sample_xlsx.py).
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
await import(new URL("../xlsx-lite.js", import.meta.url));
const { read, table } = globalThis.XlsxLite;

const buf = readFileSync(new URL("./fixtures/sample.xlsx", import.meta.url));
const book = await read(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
assert.deepEqual(book.sheets.map(s => s.name), ["Roles", "People", "Empty"]);

const t = table(book.sheets[0].rows);
assert.deepEqual(t.headers, ["Role", "Company", "Submit by", "Remote", "Score", "Score (2)", "G"]);
assert.equal(t.records.length, 2, "blank rows are skipped");
assert.deepEqual(t.records[0], { row: 2, cells: { Role: "Analyst & <Ops>", Company: "Acme — Ltd", "Submit by": "2026-11-30",
  Remote: "TRUE", Score: "7.5", "Score (2)": "3", G: "extra" } });
assert.equal(t.records[1].row, 4, "row numbers match the sheet");
assert.equal(t.records[1].cells["Submit by"], "2026-12-01 09:30");
assert.equal(t.records[1].cells.Remote, "FALSE");
assert.equal(t.records[1].cells.Company, "Café Nodach");
assert.ok(!("Score" in t.records[1].cells), "empty cells are left out");
assert.deepEqual(table(book.sheets[2].rows), { headers: [], records: [] });
await assert.rejects(read(new Uint8Array([1, 2, 3]).buffer), /not an .xlsx/);
console.log("xlsx-lite: all checks passed");
