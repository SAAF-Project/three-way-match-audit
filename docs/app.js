// Three-way match — client-side port of webapp/app/services/{parsers,matcher}.py
// Runs entirely in the browser; no data leaves the machine.

// ---------------------------------------------------------------------------
// Parsers
// ---------------------------------------------------------------------------
class ParseError extends Error {}

const LINE_QTY_KEYS = ["quantity", "qty", "quantity_received", "quantity_billed"];
const LINE_PRICE_KEYS = ["unit_price", "price", "unitprice"];
const LINE_TOTAL_KEYS = ["line_total", "total", "amount", "line_amount"];
const LINE_SKU_KEYS = ["sku", "item", "item_code", "article", "material"];
const LINE_DESC_KEYS = ["description", "desc", "text", "item_description"];
const LINE_NUM_KEYS = ["line_number", "line", "line_no", "position", "pos"];

function parseDocument(text, filename, docType) {
  const lower = (filename || "").toLowerCase();
  let raw;
  if (lower.endsWith(".json")) {
    try { raw = JSON.parse(text); }
    catch (e) { throw new ParseError(`Ongeldige JSON: ${e.message}`); }
  } else if (lower.endsWith(".csv")) {
    raw = parseCsv(text);
  } else {
    throw new ParseError(`Bestandstype niet ondersteund voor '${filename}'. Gebruik .csv of .json.`);
  }
  return normalise(raw, docType);
}

// Simple CSV parser: state machine, supports quoted fields with "" escapes.
function parseCsv(text) {
  // Strip UTF-8 BOM.
  if (text.charCodeAt(0) === 0xFEFF) text = text.slice(1);

  // Sniff delimiter from first non-empty line.
  const firstLine = text.split(/\r?\n/).find(l => l.trim()) || "";
  const counts = { ",": 0, ";": 0, "\t": 0, "|": 0 };
  let inQ = false;
  for (const c of firstLine) {
    if (c === '"') inQ = !inQ;
    else if (!inQ && counts[c] !== undefined) counts[c]++;
  }
  const delimiter = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0] || ",";

  const rows = tokenizeCsv(text, delimiter);

  // Split on blank rows.
  const blocks = [];
  let current = [];
  for (const row of rows) {
    const nonEmpty = row.some(c => c.trim() !== "");
    if (!nonEmpty) {
      if (current.length) { blocks.push(current); current = []; }
      continue;
    }
    current.push(row);
  }
  if (current.length) blocks.push(current);

  if (!blocks.length) throw new ParseError("Leeg CSV-bestand.");

  let headerMeta = {};
  let linesBlock;
  if (blocks.length >= 2 && looksLikeKeyValueBlock(blocks[0])) {
    headerMeta = rowsToDict(blocks[0]);
    linesBlock = blocks[1];
  } else {
    linesBlock = blocks[0];
  }

  const [header, ...dataRows] = linesBlock;
  const headerNorm = header.map(h => h.trim().toLowerCase());
  const lineDicts = dataRows.map(r => {
    const o = {};
    headerNorm.forEach((k, i) => { o[k] = (i < r.length ? r[i] : "").trim(); });
    return o;
  });

  // Hoist header fields from first data row for flat-CSV case.
  const hoisted = {};
  if (lineDicts.length) {
    for (const k of ["document_number", "po_number", "supplier", "date", "invoice_number", "grn_number"]) {
      if (lineDicts[0][k]) hoisted[k] = lineDicts[0][k];
    }
  }

  return { ...hoisted, ...headerMeta, lines: lineDicts };
}

function tokenizeCsv(text, delimiter) {
  const rows = [];
  let cur = [];
  let field = "";
  let inQ = false;
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (inQ) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i += 2; continue; }
        inQ = false; i++; continue;
      }
      field += c; i++; continue;
    }
    if (c === '"') { inQ = true; i++; continue; }
    if (c === delimiter) { cur.push(field); field = ""; i++; continue; }
    if (c === "\r") { i++; continue; }
    if (c === "\n") { cur.push(field); rows.push(cur); cur = []; field = ""; i++; continue; }
    field += c; i++;
  }
  // trailing field / row
  if (field !== "" || cur.length) { cur.push(field); rows.push(cur); }
  return rows;
}

function looksLikeKeyValueBlock(block) {
  if (!block.length) return false;
  const h = block[0].map(c => c.trim().toLowerCase());
  return h.length === 2 && h[0] === "field" && h[1] === "value";
}

function rowsToDict(block) {
  const out = {};
  for (const row of block.slice(1)) {
    if (row.length >= 2) {
      const k = row[0].trim().toLowerCase();
      if (k) out[k] = row[1].trim();
    }
  }
  return out;
}

function first(d, keys) {
  for (const k of keys) if (d[k] !== undefined && d[k] !== "") return d[k];
  return null;
}

function toFloat(v) {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return v;
  let s = String(v).trim().replace(/€/g, "").replace(/\s/g, "");
  const commas = (s.match(/,/g) || []).length;
  const dots = (s.match(/\./g) || []).length;
  if (commas === 1 && dots === 0) s = s.replace(",", ".");
  else if (commas >= 1 && dots >= 1) s = s.replace(/\./g, "").replace(",", ".");
  const n = parseFloat(s);
  if (isNaN(n)) throw new ParseError(`Getal onleesbaar: '${v}'`);
  return n;
}

function asStr(v) {
  return v === null || v === undefined ? "" : String(v).trim();
}

function normalise(raw, docType) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw))
    throw new ParseError("Verwacht een JSON-object of CSV met kolommen.");

  const linesRaw = raw.lines || raw.items || [];
  if (!Array.isArray(linesRaw))
    throw new ParseError("Veld 'lines' moet een lijst zijn.");

  const lines = linesRaw.map((line, idx) => {
    if (!line || typeof line !== "object")
      throw new ParseError(`Regel ${idx + 1}: verwacht een object.`);
    const ln = first(line, LINE_NUM_KEYS);
    const lnv = ln !== null && ln !== "" ? parseInt(ln, 10) : idx + 1;
    return {
      line_number: isNaN(lnv) ? idx + 1 : lnv,
      sku: asStr(first(line, LINE_SKU_KEYS)),
      description: asStr(first(line, LINE_DESC_KEYS)),
      quantity: toFloat(first(line, LINE_QTY_KEYS)),
      unit_price: toFloat(first(line, LINE_PRICE_KEYS)),
      line_total: toFloat(first(line, LINE_TOTAL_KEYS)),
    };
  });

  let total = toFloat(raw.total || raw.grand_total);
  if (total === null && lines.some(l => l.line_total !== null))
    total = Math.round(lines.reduce((s, l) => s + (l.line_total || 0), 0) * 100) / 100;

  const document_number = asStr(raw.document_number || raw.invoice_number || raw.grn_number || raw.po_number);
  const po_number = asStr(raw.po_number || raw.document_number);

  return {
    document_type: docType,
    document_number,
    po_number,
    supplier: asStr(raw.supplier || raw.vendor),
    date: asStr(raw.date || raw.document_date),
    lines,
    total,
  };
}

// ---------------------------------------------------------------------------
// Matcher
// ---------------------------------------------------------------------------
function threeWayMatch(po, grn, inv, { price_tolerance = 0.01, qty_tolerance = 0.0, total_tolerance = 0.05, line_total_tolerance = 0.01 } = {}) {
  const header_issues = checkHeader(po, grn, inv);
  const poLines = indexLines(po.lines || []);
  const grnLines = indexLines(grn.lines || []);
  const invLines = indexLines(inv.lines || []);

  const allKeys = [...new Set([...Object.keys(poLines), ...Object.keys(grnLines), ...Object.keys(invLines)])];
  const line_results = [];

  for (const key of allKeys) {
    const po_l = poLines[key];
    const grn_l = grnLines[key];
    const inv_l = invLines[key];
    const anchor = po_l || inv_l || grn_l || {};
    const lr = {
      line_number: parseInt(anchor.line_number || 0, 10) || 0,
      sku: anchor.sku || "",
      description: anchor.description || "",
      po_qty: po_l ? po_l.quantity : null,
      grn_qty: grn_l ? grn_l.quantity : null,
      inv_qty: inv_l ? inv_l.quantity : null,
      po_price: po_l ? po_l.unit_price : null,
      inv_price: inv_l ? inv_l.unit_price : null,
      po_total: po_l ? po_l.line_total : null,
      inv_total: inv_l ? inv_l.line_total : null,
      result: "MATCH",
      issues: [],
    };
    gradeLine(lr, po_l, grn_l, inv_l, qty_tolerance, price_tolerance, line_total_tolerance);
    line_results.push(lr);
  }

  const po_total = Number(po.total) || 0;
  const grn_total = grn.total !== null && grn.total !== undefined ? Number(grn.total) : null;
  const inv_total = Number(inv.total) || 0;
  const disc = Math.round((inv_total - po_total) * 100) / 100;

  if (Math.abs(disc) > total_tolerance) {
    header_issues.push(
      `Totale afwijking PO ↔ factuur: ${eur(disc)} (PO ${eur(po_total)} → factuur ${eur(inv_total)}).`
    );
  }

  const result = rollup(header_issues, line_results, disc, total_tolerance);

  return {
    result,
    header_issues,
    line_results,
    po_total,
    grn_total,
    inv_total,
    totals_discrepancy: disc,
    summary: line_results.reduce(
      (s, l) => { s[l.result]++; return s; },
      { MATCH: 0, WARNING: 0, FAIL: 0 }
    ),
    po: docMeta(po),
    grn: docMeta(grn),
    inv: docMeta(inv),
  };
}

function checkHeader(po, grn, inv) {
  const issues = [];
  const po_num = po.po_number || po.document_number || "";
  const grn_po = grn.po_number || "";
  const inv_po = inv.po_number || "";

  if (!po_num) issues.push("PO bevat geen inkoopordernummer.");
  if (grn_po && po_num && grn_po !== po_num)
    issues.push(`PO-referentie op goederenontvangst wijkt af: '${grn_po}' vs PO '${po_num}'.`);
  if (inv_po && po_num && inv_po !== po_num)
    issues.push(`PO-referentie op factuur wijkt af: '${inv_po}' vs PO '${po_num}'.`);

  const suppliers = new Set(
    [po, grn, inv].filter(d => d.supplier).map(d => d.supplier.trim().toLowerCase())
  );
  if (suppliers.size > 1) {
    const names = [po, grn, inv].filter(d => d.supplier).map(d => d.supplier).sort();
    issues.push(`Leveranciernaam is niet consistent tussen documenten: ${names.join(" / ")}.`);
  }
  return issues;
}

function indexLines(lines) {
  const out = {};
  for (const line of lines) {
    const key = lineKey(line);
    if (out[key]) {
      const existing = out[key];
      for (const fld of ["quantity", "line_total"]) {
        const a = existing[fld], b = line[fld];
        if (a !== null && b !== null) existing[fld] = Math.round((a + b) * 10000) / 10000;
        else if (b !== null) existing[fld] = b;
      }
    } else {
      out[key] = { ...line };
    }
  }
  return out;
}

function lineKey(line) {
  const sku = (line.sku || "").trim().toUpperCase();
  if (sku) return `SKU:${sku}`;
  if (line.line_number !== null && line.line_number !== undefined) return `LINE:${line.line_number}`;
  return `DESC:${(line.description || "").trim().toLowerCase()}`;
}

function gradeLine(lr, po_l, grn_l, inv_l, qtyTol, priceTol, lineTotalTol) {
  if (!po_l) { lr.issues.push("Regel ontbreekt op de inkooporder."); lr.result = "FAIL"; }
  if (!inv_l) { lr.issues.push("Regel ontbreekt op de factuur."); lr.result = "FAIL"; }
  if (!grn_l) {
    lr.issues.push("Regel ontbreekt op de goederenontvangst.");
    if (lr.result !== "FAIL") lr.result = "WARNING";
  }

  const po_qty = po_l ? po_l.quantity : null;
  const grn_qty = grn_l ? grn_l.quantity : null;
  const inv_qty = inv_l ? inv_l.quantity : null;

  if (po_qty !== null && inv_qty !== null && Math.abs(inv_qty - po_qty) > qtyTol) {
    lr.issues.push(`Gefactureerd aantal wijkt af van PO: ${numStr(inv_qty)} vs ${numStr(po_qty)}.`);
    lr.result = "FAIL";
  }
  if (po_qty !== null && grn_qty !== null && Math.abs(grn_qty - po_qty) > qtyTol) {
    if (grn_qty > po_qty) {
      lr.issues.push(`Ontvangen aantal groter dan besteld: ${numStr(grn_qty)} vs ${numStr(po_qty)}.`);
      lr.result = "FAIL";
    } else {
      lr.issues.push(`Ontvangen aantal minder dan besteld: ${numStr(grn_qty)} vs ${numStr(po_qty)}.`);
      if (lr.result !== "FAIL") lr.result = "WARNING";
    }
  }
  if (grn_qty !== null && inv_qty !== null && Math.abs(inv_qty - grn_qty) > qtyTol && inv_qty > grn_qty) {
    lr.issues.push(`Gefactureerd aantal groter dan ontvangen: ${numStr(inv_qty)} vs ${numStr(grn_qty)}.`);
    lr.result = "FAIL";
  }

  const po_price = po_l ? po_l.unit_price : null;
  const inv_price = inv_l ? inv_l.unit_price : null;
  if (po_price !== null && inv_price !== null && Math.abs(inv_price - po_price) > priceTol) {
    lr.issues.push(`Stukprijs wijkt af: PO ${eur(po_price)} → factuur ${eur(inv_price)}.`);
    lr.result = "FAIL";
  }

  const po_tot = po_l ? po_l.line_total : null;
  const inv_tot = inv_l ? inv_l.line_total : null;
  if (po_tot !== null && inv_tot !== null && Math.abs(inv_tot - po_tot) > lineTotalTol) {
    const already = lr.issues.some(i => i.includes("aantal") || i.includes("prijs"));
    if (!already) {
      lr.issues.push(`Regeltotaal wijkt af: PO ${eur(po_tot)} → factuur ${eur(inv_tot)}.`);
      lr.result = "FAIL";
    }
  }
}

function rollup(header_issues, lines, disc, tol) {
  if (lines.some(l => l.result === "FAIL")) return "FAIL";
  if (header_issues.some(h => h.includes("wijkt af"))) return "FAIL";
  if (Math.abs(disc) > tol) return "FAIL";
  if (lines.some(l => l.result === "WARNING") || header_issues.length) return "WARNING";
  return "MATCH";
}

function docMeta(d) {
  return {
    document_type: d.document_type,
    document_number: d.document_number,
    po_number: d.po_number,
    supplier: d.supplier,
    date: d.date,
    total: d.total,
    line_count: (d.lines || []).length,
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function numStr(v) { return Number(v).toString(); }
function eur(v) { return `€${Number(v).toLocaleString("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }
function eurPlain(v) { return `€${(Math.round(v * 100) / 100).toFixed(2)}`; }
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

// ---------------------------------------------------------------------------
// UI
// ---------------------------------------------------------------------------
const form = document.getElementById("match-form");
const uploadView = document.getElementById("upload-view");
const resultView = document.getElementById("result-view");
const errorBox = document.getElementById("error-box");

function showError(msg) {
  errorBox.innerHTML = `<strong>Fout bij inlezen:</strong> ${esc(msg)}`;
  errorBox.hidden = false;
  errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
}
function clearError() { errorBox.hidden = true; errorBox.innerHTML = ""; }

function readFile(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => reject(new Error(`Kan '${file.name}' niet lezen.`));
    fr.readAsText(file, "utf-8");
  });
}

async function readFileBoth(file) {
  const buf = await file.arrayBuffer();
  const text = new TextDecoder("utf-8").decode(buf);
  const digest = await crypto.subtle.digest("SHA-256", buf);
  const sha256 = Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, "0")).join("");
  return { text, sha256, size: buf.byteLength };
}

const SCHEMA_VERSION = "1.0";
const TOOL_NAME = "SAAF Three-way Match";
const TOOL_VERSION = "0.1.0";

function buildWorkpaper({ sources, parsed, report, parameters }) {
  return {
    audit_workpaper: {
      schema_version: SCHEMA_VERSION,
      generated_at: new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00"),
      tool: { name: TOOL_NAME, version: TOOL_VERSION },
      match_parameters: parameters,
    },
    source_data: {
      purchase_order:   { ...sources.po,  parsed: parsed.po },
      goods_receipt:    { ...sources.grn, parsed: parsed.grn },
      purchase_invoice: { ...sources.inv, parsed: parsed.inv },
    },
    match_result: {
      verdict: report.result,
      summary: report.summary,
      header_issues: report.header_issues,
      line_results: report.line_results,
      totals: {
        po_total: report.po_total,
        grn_total: report.grn_total,
        inv_total: report.inv_total,
        discrepancy: report.totals_discrepancy,
      },
    },
    attestation: { reviewed_by: "", reviewed_at: "", notes: "" },
  };
}

function workpaperFilename(report) {
  const po = report.po || {};
  const poNum = (po.po_number || po.document_number || "unknown").replace(/\//g, "_");
  const verdict = report.result || "UNKNOWN";
  const now = new Date();
  const stamp = `${now.getUTCFullYear()}${String(now.getUTCMonth() + 1).padStart(2, "0")}${String(now.getUTCDate()).padStart(2, "0")}`;
  return `audit_workpaper_${poNum}_${verdict}_${stamp}.json`;
}

// Tolerance presets ---------------------------------------------------------
const TOLERANCE_PRESETS = {
  strict:   { price_tolerance: 0,    qty_tolerance: 0, line_total_tolerance: 0,    total_tolerance: 0    },
  standard: { price_tolerance: 0.01, qty_tolerance: 0, line_total_tolerance: 0.01, total_tolerance: 0.05 },
  relaxed:  { price_tolerance: 0.10, qty_tolerance: 1, line_total_tolerance: 1.00, total_tolerance: 5.00 },
};
document.querySelectorAll(".preset").forEach(btn => {
  btn.addEventListener("click", () => {
    const vals = TOLERANCE_PRESETS[btn.dataset.preset];
    for (const [k, v] of Object.entries(vals)) {
      const input = document.querySelector(`[name="${k}"]`);
      if (input) input.value = v;
    }
    document.querySelectorAll(".preset").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
  });
});

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  clearError();
  const fd = new FormData(form);
  const po_file = fd.get("po_file");
  const grn_file = fd.get("grn_file");
  const inv_file = fd.get("invoice_file");
  if (!po_file?.name || !grn_file?.name || !inv_file?.name) {
    showError("Selecteer alle drie de bestanden.");
    return;
  }
  const tol = {
    price_tolerance: parseFloat(fd.get("price_tolerance")) || 0,
    qty_tolerance: parseFloat(fd.get("qty_tolerance")) || 0,
    line_total_tolerance: parseFloat(fd.get("line_total_tolerance")) || 0,
    total_tolerance: parseFloat(fd.get("total_tolerance")) || 0,
  };
  try {
    const [poR, grnR, invR] = await Promise.all([readFileBoth(po_file), readFileBoth(grn_file), readFileBoth(inv_file)]);
    const parsed = {
      po:  parseDocument(poR.text,  po_file.name,  "PO"),
      grn: parseDocument(grnR.text, grn_file.name, "GRN"),
      inv: parseDocument(invR.text, inv_file.name, "INVOICE"),
    };
    const sources = {
      po:  { filename: po_file.name,  size_bytes: poR.size,  sha256: poR.sha256 },
      grn: { filename: grn_file.name, size_bytes: grnR.size, sha256: grnR.sha256 },
      inv: { filename: inv_file.name, size_bytes: invR.size, sha256: invR.sha256 },
    };
    const report = threeWayMatch(parsed.po, parsed.grn, parsed.inv, tol);
    const workpaper = buildWorkpaper({ sources, parsed, report, parameters: tol });
    renderResult(report, { po: po_file.name, grn: grn_file.name, invoice: inv_file.name }, workpaper);
  } catch (e) {
    showError(e.message || String(e));
  }
});

function renderResult(r, filenames, workpaper) {
  const verdictText = {
    MATCH: "Match — alles komt overeen",
    WARNING: "Waarschuwing — non-materiële verschillen",
    FAIL: "Fail — materiële afwijking gedetecteerd",
  }[r.result];

  const docsHtml = [
    ["po", "Inkooporder"],
    ["grn", "Goederenontvangst"],
    ["inv", "Factuur"],
  ].map(([k, label]) => {
    const d = r[k];
    return `
      <div class="doc">
        <h4>${label}</h4>
        <dl>
          <dt>Nummer</dt><dd>${esc(d.document_number || "—")}</dd>
          <dt>PO-ref</dt><dd>${esc(d.po_number || "—")}</dd>
          <dt>Leverancier</dt><dd>${esc(d.supplier || "—")}</dd>
          <dt>Datum</dt><dd>${esc(d.date || "—")}</dd>
          <dt>Regels</dt><dd>${d.line_count}</dd>
          <dt>Totaal</dt><dd>${d.total !== null && d.total !== undefined ? eurPlain(d.total) : "—"}</dd>
        </dl>
      </div>`;
  }).join("");

  const headerIssuesHtml = r.header_issues.length
    ? `<div class="header-issues"><h4>Header-issues</h4><ul>${r.header_issues.map(i => `<li>${esc(i)}</li>`).join("")}</ul></div>`
    : "";

  const linesHtml = r.line_results.map(l => {
    const cls = l.result === "FAIL" ? "diff-fail" : l.result === "WARNING" ? "diff-warn" : "";
    const issues = l.issues.length
      ? `<ul class="issues-list">${l.issues.map(i => `<li class="${cls}">${esc(i)}</li>`).join("")}</ul>`
      : "";
    const numCell = v => v !== null && v !== undefined ? esc(numStr(v)) : "—";
    const eurCell = v => v !== null && v !== undefined ? eurPlain(v) : "—";
    return `
      <tr>
        <td>${l.line_number}</td>
        <td>
          <strong>${esc(l.sku || "—")}</strong><br>
          <span style="color: var(--text-sec); font-size: 11px;">${esc(l.description)}</span>
          ${issues}
        </td>
        <td class="num">${numCell(l.po_qty)}</td>
        <td class="num">${numCell(l.grn_qty)}</td>
        <td class="num">${numCell(l.inv_qty)}</td>
        <td class="num">${eurCell(l.po_price)}</td>
        <td class="num">${eurCell(l.inv_price)}</td>
        <td class="num">${eurCell(l.po_total)}</td>
        <td class="num">${eurCell(l.inv_total)}</td>
        <td><span class="badge ${l.result}">${l.result}</span></td>
      </tr>`;
  }).join("");

  resultView.innerHTML = `
    <h1>Match-resultaat</h1>
    <p class="subtitle">Vergelijking van ${esc(filenames.po)} · ${esc(filenames.grn)} · ${esc(filenames.invoice)}</p>

    <div class="verdict-card ${r.result}">
      <p class="verdict-label">Overall</p>
      <p class="verdict-value">${verdictText}</p>
    </div>

    <div class="summary-grid">
      <div class="summary-tile match"><div class="n">${r.summary.MATCH}</div><div class="lbl">Match</div></div>
      <div class="summary-tile warning"><div class="n">${r.summary.WARNING}</div><div class="lbl">Warning</div></div>
      <div class="summary-tile fail"><div class="n">${r.summary.FAIL}</div><div class="lbl">Fail</div></div>
      <div class="summary-tile total"><div class="n">${eurPlain(r.totals_discrepancy)}</div><div class="lbl">Afwijking totaal</div></div>
    </div>

    <div class="doc-meta">${docsHtml}</div>
    ${headerIssuesHtml}

    <div class="section-label">Regelvergelijking</div>
    <table class="lines">
      <thead>
        <tr>
          <th>Regel</th><th>SKU / Omschrijving</th>
          <th class="num">PO qty</th><th class="num">GRN qty</th><th class="num">Fact. qty</th>
          <th class="num">PO prijs</th><th class="num">Fact. prijs</th>
          <th class="num">PO totaal</th><th class="num">Fact. totaal</th>
          <th>Result</th>
        </tr>
      </thead>
      <tbody>${linesHtml}</tbody>
    </table>

    <div class="section-label">Auditbestand</div>
    <div class="workpaper-panel">
      <div class="workpaper-copy">
        <strong>Reproduceerbaar auditbestand</strong>
        <p>
          Één JSON-document met SHA-256 van elk bronbestand, de gebruikte toleranties, de
          geparste brondata en het volledige matchresultaat. Bedoeld om als bewijs bij het
          auditdossier te voegen — een reviewer kan hetzelfde bestand door de matcher halen
          en moet exact hetzelfde resultaat krijgen.
        </p>
      </div>
      <button type="button" class="primary" id="download-workpaper">
        Download auditbestand (.json)
      </button>
    </div>

    <a href="#" class="back-link" id="back-link">← Nieuwe match uitvoeren</a>
  `;

  uploadView.hidden = true;
  resultView.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });

  document.getElementById("back-link").addEventListener("click", (e) => {
    e.preventDefault();
    resultView.hidden = true;
    uploadView.hidden = false;
    form.reset();
  });

  document.getElementById("download-workpaper").addEventListener("click", () => {
    const body = JSON.stringify(workpaper, null, 2);
    const blob = new Blob([body], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = workpaperFilename(r);
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  });
}
