/* xlsx-lite: read the sheets of an .xlsx file in the browser, with no library (M1 d, 18 Nov 2026).
 *
 * An .xlsx file is a zip of XML parts. This reads the zip's central directory, inflates each part with the
 * browser's own DecompressionStream("deflate-raw"), and pulls rows out of the worksheet XML. It covers what
 * Google Sheets and Excel export: shared strings, inline strings, formula results, booleans, numbers, and
 * dates (numbers whose cell style is a date format, turned into YYYY-MM-DD or YYYY-MM-DD HH:MM).
 *
 *   const book = await XlsxLite.read(arrayBuffer);
 *   book.sheets → [{ name, rows: [[cell, ...], ...] }]   cells are strings ("" when empty)
 *   XlsxLite.table(rows) → { headers, records: [{ row, cells: {header: value} }] }
 *
 * Used by the hub's /studio/import page and by studio/tests/xlsx-lite.test.mjs.
 */
(function (root) {
  const dec = new TextDecoder();

  async function inflate(bytes) {
    const s = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
    return new Uint8Array(await new Response(s).arrayBuffer());
  }

  async function unzip(buf) {
    const b = new Uint8Array(buf), v = new DataView(b.buffer, b.byteOffset, b.byteLength);
    let eocd = -1;
    for (let i = b.length - 22; i >= Math.max(0, b.length - 65557); i--) if (v.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    if (eocd < 0) throw new Error("not an .xlsx file (no zip directory found)");
    const count = v.getUint16(eocd + 10, true);
    let p = v.getUint32(eocd + 16, true);
    const files = {};
    for (let n = 0; n < count; n++) {
      if (v.getUint32(p, true) !== 0x02014b50) throw new Error("damaged .xlsx file (zip directory)");
      const method = v.getUint16(p + 10, true), size = v.getUint32(p + 20, true);
      const nameLen = v.getUint16(p + 28, true), extraLen = v.getUint16(p + 30, true), commentLen = v.getUint16(p + 32, true);
      const local = v.getUint32(p + 42, true);
      const name = dec.decode(b.subarray(p + 46, p + 46 + nameLen));
      files[name] = { method, size, local };
      p += 46 + nameLen + extraLen + commentLen;
    }
    return async (name) => {
      const f = files[name];
      if (!f) return null;
      const start = f.local + 30 + v.getUint16(f.local + 26, true) + v.getUint16(f.local + 28, true);
      const raw = b.subarray(start, start + f.size);
      if (f.method === 0) return dec.decode(raw);
      if (f.method === 8) return dec.decode(await inflate(raw));
      throw new Error(`unsupported compression in ${name}`);
    };
  }

  const ENT = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };
  const unesc = (s) => s.replace(/&(#x[0-9a-f]+|#\d+|\w+);/gi, (m, e) =>
    e[0] === "#" ? String.fromCodePoint(e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10)) : (ENT[e] ?? m));
  const attr = (tag, name) => { const m = tag.match(new RegExp(`\\s${name}="([^"]*)"`)); return m ? unesc(m[1]) : null; };
  const texts = (xml) => { let out = ""; for (const m of xml.matchAll(/<t(?:\s[^>]*)?>([\s\S]*?)<\/t>/g)) out += unesc(m[1]); return out; };
  // phonetic runs (<rPh>) are hints, not text
  const strip = (xml) => xml.replace(/<rPh[\s\S]*?<\/rPh>/g, "");

  const colIndex = (ref) => { let n = 0; for (const ch of ref.replace(/\d+$/, "")) n = n * 26 + (ch.charCodeAt(0) - 64); return n - 1; };

  const DATE_IDS = new Set([14, 15, 16, 17, 18, 19, 20, 21, 22, 45, 46, 47]);
  function dateStyles(stylesXml) {
    const custom = {};
    for (const m of (stylesXml || "").matchAll(/<numFmt\s[^>]*>/g)) {
      const id = Number(attr(m[0], "numFmtId")), code = (attr(m[0], "formatCode") || "").replace(/"[^"]*"|\[[^\]]*\]|\\./g, "");
      custom[id] = /[dmyhs]/i.test(code) && !/^[#0.,%\s]+$/.test(code);
    }
    const xfs = ((stylesXml || "").match(/<cellXfs[\s\S]*?<\/cellXfs>/) || [""])[0];
    return [...xfs.matchAll(/<xf\s[^>]*?(?:\/>|>)/g)].map((m) => {
      const id = Number(attr(m[0], "numFmtId") || 0);
      return DATE_IDS.has(id) || !!custom[id];
    });
  }
  function serialToDate(x) {
    const ms = Math.round((x - 25569) * 86400000);
    const iso = new Date(ms).toISOString();
    return iso.endsWith("T00:00:00.000Z") ? iso.slice(0, 10) : iso.slice(0, 16).replace("T", " ");
  }

  async function read(buf) {
    const get = await unzip(buf);
    const wb = await get("xl/workbook.xml");
    if (!wb) throw new Error("not an .xlsx file (no workbook)");
    const rels = (await get("xl/_rels/workbook.xml.rels")) || "";
    const target = {};
    for (const m of rels.matchAll(/<Relationship\s[^>]*>/g)) target[attr(m[0], "Id")] = attr(m[0], "Target");
    const ssXml = (await get("xl/sharedStrings.xml")) || "";
    const shared = [...ssXml.matchAll(/<si>([\s\S]*?)<\/si>/g)].map((m) => texts(strip(m[1])));
    const isDate = dateStyles(await get("xl/styles.xml"));
    const sheets = [];
    for (const m of wb.matchAll(/<sheet\s[^>]*>/g)) {
      const name = attr(m[0], "name"), rid = attr(m[0], "r:id");
      let t = target[rid] || "";
      t = t.startsWith("/") ? t.slice(1) : "xl/" + t.replace(/^\.\//, "");
      const xml = (await get(t)) || "";
      const rows = [];
      for (const r of xml.matchAll(/<row\s([^>]*?)(?:\/>|>([\s\S]*?)<\/row>)/g)) {
        const rn = Number(attr("<row " + r[1], "r")) || rows.length + 1;
        const cells = [];
        for (const c of (r[2] || "").matchAll(/<c\s([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g)) {
          const tag = "<c " + c[1], body = c[2] || "";
          const ref = attr(tag, "r"), type = attr(tag, "t"), style = Number(attr(tag, "s") || 0);
          const vm = body.match(/<v>([\s\S]*?)<\/v>/), v = vm ? unesc(vm[1]) : "";
          let val;
          if (type === "s") val = shared[Number(v)] ?? "";
          else if (type === "inlineStr") val = texts(strip(body));
          else if (type === "b") val = v === "1" ? "TRUE" : v === "0" ? "FALSE" : v;
          else if (type === "str" || type === "e") val = v;
          else if (v !== "" && isDate[style] && isFinite(Number(v))) val = serialToDate(Number(v));
          else val = v;
          const i = ref ? colIndex(ref) : cells.length;
          while (cells.length < i) cells.push("");
          cells[i] = val;
        }
        while (rows.length < rn - 1) rows.push([]);
        rows[rn - 1] = cells;
      }
      sheets.push({ name, rows });
    }
    return { sheets };
  }

  const letter = (i) => { let s = ""; for (i++; i > 0; i = Math.floor((i - 1) / 26)) s = String.fromCharCode(65 + ((i - 1) % 26)) + s; return s; };
  const blank = (row) => !row || row.every((c) => String(c ?? "").trim() === "");

  // The first non-empty row is the header row; empty headers get their column letter; repeats get " (2)".
  function table(rows) {
    const h = rows.findIndex((r) => !blank(r));
    if (h < 0) return { headers: [], records: [] };
    const width = Math.max(...rows.map((r) => (r || []).length));
    const used = {};
    const headers = [];
    for (let i = 0; i < width; i++) {
      let name = String(rows[h][i] ?? "").trim() || letter(i);
      if (used[name]) name = `${name} (${++used[name]})`; else used[name] = 1;
      headers.push(name);
    }
    const records = [];
    for (let r = h + 1; r < rows.length; r++) {
      if (blank(rows[r])) continue;
      const cells = {};
      headers.forEach((name, i) => { const v = String(rows[r][i] ?? ""); if (v !== "") cells[name] = v; });
      records.push({ row: r + 1, cells });
    }
    return { headers, records };
  }

  root.XlsxLite = { read, table };
})(typeof globalThis !== "undefined" ? globalThis : window);
