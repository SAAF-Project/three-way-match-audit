"""Parsers for PO / GRN / Invoice files.

Supported: CSV and JSON. Every parser normalises the input to the same
in-memory shape so the matcher never has to care about the source format:

    {
      "document_type": "PO" | "GRN" | "INVOICE",
      "document_number": "...",
      "po_number": "...",
      "supplier": "...",
      "date": "YYYY-MM-DD" | None,
      "lines": [
          {
              "line_number": 1,
              "sku": "...",
              "description": "...",
              "quantity": 10.0,
              "unit_price": 25.00,   # may be None on GRN
              "line_total": 250.00,  # may be None on GRN
          },
          ...
      ],
      "total": 250.00,               # may be None on GRN
    }
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any


class ParseError(ValueError):
    """Raised when a file cannot be parsed into the canonical shape."""


DOC_TYPES = {"PO", "GRN", "INVOICE"}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def parse_document(raw: bytes, filename: str, doc_type: str) -> dict[str, Any]:
    doc_type = doc_type.upper()
    if doc_type not in DOC_TYPES:
        raise ParseError(f"Onbekend documenttype: {doc_type}")

    lower = filename.lower()
    if lower.endswith(".json"):
        parsed = _parse_json(raw)
    elif lower.endswith(".csv"):
        parsed = _parse_csv(raw)
    else:
        raise ParseError(
            f"Bestandstype niet ondersteund voor '{filename}'. Gebruik .csv of .json."
        )

    return _normalise(parsed, doc_type)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------
def _parse_json(raw: bytes) -> dict[str, Any]:
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ParseError(f"Ongeldige JSON: {e.msg} (regel {e.lineno})") from e
    except UnicodeDecodeError as e:
        raise ParseError("Bestand is geen geldige UTF-8 tekst.") from e


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
#
# A CSV either contains only line rows (header is derived from filename via
# metadata columns), or it is a "two-block" CSV where the first block is a
# header key/value section separated from the lines block by an empty row.
#
# Two-block example:
#
#     field,value
#     document_number,PO-2025-001
#     po_number,PO-2025-001
#     supplier,ACME BV
#     date,2025-01-15
#
#     line_number,sku,description,quantity,unit_price,line_total
#     1,SKU-A100,Widget A,10,25.00,250.00
#
# Flat example (header info repeated on every line):
#
#     po_number,supplier,line_number,sku,description,quantity,unit_price,line_total
#     PO-2025-001,ACME BV,1,SKU-A100,Widget A,10,25.00,250.00
def _parse_csv(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ParseError("Bestand is geen geldige UTF-8 tekst.") from e

    # Sniff dialect but fall back to comma on failure.
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(cell.strip() for cell in r)] if False else rows

    # Split on blank rows so we can spot the header/lines two-block form.
    blocks: list[list[list[str]]] = []
    current: list[list[str]] = []
    for row in rows:
        if not any(cell.strip() for cell in row):
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(row)
    if current:
        blocks.append(current)

    if not blocks:
        raise ParseError("Leeg CSV-bestand.")

    header_meta: dict[str, Any] = {}
    lines_block: list[list[str]]

    if len(blocks) >= 2 and _looks_like_key_value_block(blocks[0]):
        header_meta = _rows_to_dict(blocks[0])
        lines_block = blocks[1]
    else:
        lines_block = blocks[0]

    header, *data_rows = lines_block
    header_norm = [h.strip().lower() for h in header]
    line_dicts: list[dict[str, Any]] = []
    for r in data_rows:
        line_dicts.append({header_norm[i]: r[i].strip() if i < len(r) else ""
                           for i in range(len(header_norm))})

    # Pull header fields from the first line row if flat CSV, letting the
    # explicit header block override where present.
    hoisted: dict[str, Any] = {}
    if line_dicts:
        first = line_dicts[0]
        for key in ("document_number", "po_number", "supplier", "date",
                    "invoice_number", "grn_number"):
            if key in first and first[key]:
                hoisted.setdefault(key, first[key])

    merged_header = {**hoisted, **header_meta}
    return {**merged_header, "lines": line_dicts}


def _looks_like_key_value_block(block: list[list[str]]) -> bool:
    if not block:
        return False
    header = [c.strip().lower() for c in block[0]]
    return header[:2] == ["field", "value"] and len(header) == 2


def _rows_to_dict(block: list[list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in block[1:]:
        if len(row) >= 2:
            key = row[0].strip().lower()
            val = row[1].strip()
            if key:
                out[key] = val
    return out


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
_LINE_QTY_KEYS = ("quantity", "qty", "quantity_received", "quantity_billed")
_LINE_PRICE_KEYS = ("unit_price", "price", "unitprice")
_LINE_TOTAL_KEYS = ("line_total", "total", "amount", "line_amount")
_LINE_SKU_KEYS = ("sku", "item", "item_code", "article", "material")
_LINE_DESC_KEYS = ("description", "desc", "text", "item_description")
_LINE_NUM_KEYS = ("line_number", "line", "line_no", "position", "pos")


def _normalise(raw: dict[str, Any], doc_type: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ParseError("Verwacht een JSON-object of CSV met kolommen.")

    lines_raw = raw.get("lines") or raw.get("items") or []
    if not isinstance(lines_raw, list):
        raise ParseError("Veld 'lines' moet een lijst zijn.")

    lines: list[dict[str, Any]] = []
    for idx, line in enumerate(lines_raw, start=1):
        if not isinstance(line, dict):
            raise ParseError(f"Regel {idx}: verwacht een object, kreeg {type(line).__name__}.")

        line_number = _first(line, _LINE_NUM_KEYS)
        sku = _first(line, _LINE_SKU_KEYS)
        desc = _first(line, _LINE_DESC_KEYS)
        qty = _first(line, _LINE_QTY_KEYS)
        price = _first(line, _LINE_PRICE_KEYS)
        total = _first(line, _LINE_TOTAL_KEYS)

        try:
            line_number_val = int(line_number) if line_number not in (None, "") else idx
        except (TypeError, ValueError):
            line_number_val = idx

        lines.append({
            "line_number": line_number_val,
            "sku": _as_str(sku),
            "description": _as_str(desc),
            "quantity": _to_float(qty),
            "unit_price": _to_float(price),
            "line_total": _to_float(total),
        })

    total = _to_float(raw.get("total") or raw.get("grand_total"))
    if total is None and any(l["line_total"] is not None for l in lines):
        total = round(sum((l["line_total"] or 0.0) for l in lines), 2)

    document_number = _as_str(
        raw.get("document_number") or raw.get("invoice_number")
        or raw.get("grn_number") or raw.get("po_number")
    )
    po_number = _as_str(raw.get("po_number") or raw.get("document_number"))

    return {
        "document_type": doc_type,
        "document_number": document_number or "",
        "po_number": po_number or "",
        "supplier": _as_str(raw.get("supplier") or raw.get("vendor") or ""),
        "date": _as_str(raw.get("date") or raw.get("document_date") or ""),
        "lines": lines,
        "total": total,
    }


def _first(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("€", "").replace(" ", "")
    if s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    elif s.count(",") >= 1 and s.count(".") >= 1:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError as e:
        raise ParseError(f"Getal onleesbaar: '{v}'") from e


def _as_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()
