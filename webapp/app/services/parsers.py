"""Parsers for PO / GRN / Invoice files.

Supported: CSV and JSON. Every parser normalises the input to the same
in-memory shape so the matcher never has to care about the source format:

    {
      "document_type": "PO" | "GRN" | "INVOICE",
      "document_number": "...",
      "po_number": "...",
      "supplier": "...",
      "date": "YYYY-MM-DD" | "",
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
      "total": 250.00,               # stated document total, else sum of lines
      "total_stated": True | False,  # whether `total` came from the file
      "lines_sum": 250.00 | None,    # sum of line totals, None if any is missing
    }

Parsing fails closed: anything that could be read in more than one way
(two columns that both claim to be the quantity, rows of one file pointing
to different POs, "1.000" with no way to tell the decimal separator, NaN,
infinity) raises ParseError instead of picking one reading silently.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from typing import Any

from app.services.validation import MAX_AMOUNT, ValidationFailed, validate_document


class ParseError(ValueError):
    """Raised when a file cannot be parsed into the canonical shape."""


DOC_TYPES = {"PO", "GRN", "INVOICE"}

# Input limits. The web layer also caps the upload size in bytes.
MAX_LINES = 5000
MAX_TEXT_LENGTH = 500

# A text cell that starts with one of these is run as a formula when the file
# is opened in Excel or another spreadsheet (CSV / formula injection).
_FORMULA_PREFIXES = ("=", "+", "-", "@")

# Signatures of binary formats that are sometimes renamed to .csv.
_BINARY_SIGNATURES = (
    (b"PK\x03\x04", "een Excel-bestand (.xlsx) of ander zip-bestand"),
    (b"\xd0\xcf\x11\xe0", "een oud Excel-bestand (.xls)"),
    (b"%PDF", "een PDF"),
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def parse_document(raw: bytes, filename: str, doc_type: str) -> dict[str, Any]:
    """Parse, normalise and validate one uploaded document.

    Two layers reject bad input, each with its own job:
      1. this module — reading the file: formats, number notation, column
         aliases, flat-CSV consistency, formula cells, size limits;
      2. services/validation.py (pandera) — data quality of the parsed
         document: required fields, value ranges, line arithmetic, one price
         per SKU.
    Every error message starts with the file name, so the user knows which
    of the three uploads to fix.
    """
    doc_type = doc_type.upper()
    if doc_type not in DOC_TYPES:
        raise ParseError(f"Onbekend documenttype: {doc_type}")

    try:
        _check_content(raw)
        lower = filename.lower()
        if lower.endswith(".json"):
            parsed = _parse_json(raw)
        elif lower.endswith(".csv"):
            parsed = _parse_csv(raw)
        else:
            raise ParseError("Bestandstype niet ondersteund. Gebruik .csv of .json.")
        doc = _normalise(parsed, doc_type)
        validate_document(parsed, doc, doc_type)
    except ValidationFailed as e:
        raise ParseError(f"'{filename}': " + "; ".join(e.messages)) from e
    except ParseError as e:
        raise ParseError(f"'{filename}': {e}") from e
    return doc


def _check_content(raw: bytes) -> None:
    """Reject empty and binary files before any parser sees them. The file
    extension and the browser's MIME type are claims; the bytes are not."""
    if not raw or not raw.strip():
        raise ParseError("Bestand is leeg.")
    for signature, what in _BINARY_SIGNATURES:
        if raw.startswith(signature):
            raise ParseError(
                f"Dit is {what}, geen CSV of JSON. "
                "Exporteer het blad als CSV (UTF-8) en upload dat bestand."
            )
    if b"\x00" in raw[:8192]:
        raise ParseError("Dit is een binair bestand, geen CSV of JSON.")


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------
def _reject_constant(name: str) -> Any:
    raise ParseError(f"Ongeldige waarde in JSON: {name} (alleen eindige getallen toegestaan).")


def _parse_json(raw: bytes) -> dict[str, Any]:
    try:
        # parse_constant catches the non-standard NaN / Infinity literals.
        return json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant)
    except json.JSONDecodeError as e:
        raise ParseError(f"Ongeldige JSON: {e.msg} (regel {e.lineno})") from e
    except UnicodeDecodeError as e:
        raise ParseError("Bestand is geen geldige UTF-8 tekst.") from e
    except RecursionError as e:
        raise ParseError("JSON is te diep genest.") from e
    except ValueError as e:  # e.g. an integer with too many digits
        if isinstance(e, ParseError):
            raise
        raise ParseError("JSON bevat een onleesbaar getal.") from e


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
#
# A CSV either contains only line rows (flat), or it is a "two-block" CSV
# where the first block is a header key/value section separated from the
# lines block by an empty row.
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
# Flat example (header info repeated on every line; every row must agree):
#
#     po_number,supplier,line_number,sku,description,quantity,unit_price,line_total
#     PO-2025-001,ACME BV,1,SKU-A100,Widget A,10,25.00,250.00
_HEADER_KEYS = ("document_number", "invoice_number", "grn_number", "po_number",
                "supplier", "vendor", "date", "document_date")


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

    try:
        rows = list(csv.reader(io.StringIO(text), dialect))
    except csv.Error as e:
        raise ParseError(f"CSV is onleesbaar: {e}") from e

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
    if _looks_like_key_value_block(blocks[0]):
        if len(blocks) < 2:
            raise ParseError("CSV bevat alleen een kopblok (field,value) en geen regels.")
        header_meta = _rows_to_dict(blocks[0])
        line_blocks = blocks[1:]
    else:
        line_blocks = blocks
    if len(line_blocks) > 1:
        raise ParseError(
            "CSV bevat meer dan één blok regels gescheiden door lege regels. "
            "Zet alle regels in één blok."
        )
    lines_block = line_blocks[0]

    header, *data_rows = lines_block
    header_norm = [h.strip().lower() for h in header]
    duplicates = sorted({h for h in header_norm if h and header_norm.count(h) > 1})
    if duplicates:
        raise ParseError(f"Kolom komt meer dan eens voor: {', '.join(duplicates)}.")

    line_dicts: list[dict[str, Any]] = []
    for row_no, r in enumerate(data_rows, start=1):
        extra = [c for c in r[len(header_norm):] if c.strip()]
        if extra:
            raise ParseError(f"Regel {row_no} heeft meer waarden dan er kolommen zijn.")
        line_dicts.append({header_norm[i]: r[i].strip() if i < len(r) else ""
                           for i in range(len(header_norm)) if header_norm[i]})

    # Flat CSV: header fields repeated on every row must be the same on every
    # row, and must agree with the key/value block when both are present.
    merged_header = dict(header_meta)
    for key in _HEADER_KEYS:
        if key not in header_norm:
            continue
        values = {d[key] for d in line_dicts if d.get(key)}
        if len(values) > 1:
            raise ParseError(
                f"Regels verwijzen naar verschillende waarden voor '{key}': "
                f"{', '.join(sorted(values))}. Eén bestand hoort bij één document."
            )
        if values:
            (value,) = values
            if merged_header.get(key) and merged_header[key] != value:
                raise ParseError(
                    f"'{key}' in het kopblok ({merged_header[key]}) wijkt af "
                    f"van de regels ({value})."
                )
            merged_header[key] = value

    return {**merged_header, "lines": line_dicts}


def _looks_like_key_value_block(block: list[list[str]]) -> bool:
    if not block:
        return False
    header = [c.strip().lower() for c in block[0] if c.strip()]
    return header == ["field", "value"]


def _rows_to_dict(block: list[list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in block[1:]:
        if len(row) >= 2:
            key = row[0].strip().lower()
            val = row[1].strip()
            if not key:
                continue
            if key in out and out[key] != val:
                raise ParseError(f"Veld '{key}' staat twee keer in het kopblok met verschillende waarden.")
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

_DOC_TOTAL_KEYS = ("total", "grand_total", "amount_due", "total_amount", "invoice_total")
_DOC_NUMBER_KEYS = {
    "PO": ("document_number", "po_number"),
    "GRN": ("document_number", "grn_number"),
    "INVOICE": ("document_number", "invoice_number"),
}
_SUPPLIER_KEYS = ("supplier", "vendor")
_DATE_KEYS = ("date", "document_date")


def _normalise(raw: dict[str, Any], doc_type: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ParseError("Verwacht een JSON-object of CSV met kolommen.")

    if "lines" in raw and "items" in raw:
        raise ParseError("Gebruik 'lines' of 'items', niet allebei.")
    lines_raw = raw.get("lines") if "lines" in raw else raw.get("items")
    if lines_raw is None:
        lines_raw = []
    if not isinstance(lines_raw, list):
        raise ParseError("Veld 'lines' moet een lijst zijn.")
    if not lines_raw:
        raise ParseError("Document bevat geen regels.")
    if len(lines_raw) > MAX_LINES:
        raise ParseError(f"Document bevat meer dan {MAX_LINES} regels.")

    lines: list[dict[str, Any]] = []
    for idx, line in enumerate(lines_raw, start=1):
        if not isinstance(line, dict):
            raise ParseError(f"Regel {idx}: verwacht een object, kreeg {type(line).__name__}.")
        where = f"Regel {idx}"

        line_number = _pick(line, _LINE_NUM_KEYS, "regelnummer", where, numeric=True)
        if line_number is None:
            line_number_val = idx
        else:
            try:
                line_number_val = int(float(str(line_number).strip()))
            except (TypeError, ValueError, OverflowError):
                raise ParseError(f"{where}: regelnummer '{_short(line_number)}' is geen geheel getal.")

        lines.append({
            "line_number": line_number_val,
            "sku": _as_text(_pick(line, _LINE_SKU_KEYS, "artikelcode", where), "artikelcode", where),
            "description": _as_text(_pick(line, _LINE_DESC_KEYS, "omschrijving", where), "omschrijving", where),
            "quantity": _to_float(_pick(line, _LINE_QTY_KEYS, "aantal", where, numeric=True), "aantal", where),
            "unit_price": _to_float(_pick(line, _LINE_PRICE_KEYS, "stukprijs", where, numeric=True), "stukprijs", where),
            "line_total": _to_float(_pick(line, _LINE_TOTAL_KEYS, "regeltotaal", where, numeric=True), "regeltotaal", where),
        })

    line_totals = [l["line_total"] for l in lines]
    lines_sum = round(sum(line_totals), 2) if all(t is not None for t in line_totals) else None

    stated_total = _to_float(_pick(raw, _DOC_TOTAL_KEYS, "documenttotaal", "Kop", numeric=True),
                             "documenttotaal", "Kop")
    if stated_total is not None:
        total, total_stated = stated_total, True
    else:
        known = [t for t in line_totals if t is not None]
        total, total_stated = (round(sum(known), 2) if known else None), False

    document_number = _as_text(_pick(raw, _DOC_NUMBER_KEYS[doc_type], "documentnummer", "Kop"),
                               "documentnummer", "Kop")
    po_number = _as_text(raw.get("po_number"), "PO-nummer", "Kop")
    if doc_type == "PO" and not po_number:
        po_number = document_number  # a PO's own number is its PO number

    return {
        "document_type": doc_type,
        "document_number": document_number,
        "po_number": po_number,
        "supplier": _as_text(_pick(raw, _SUPPLIER_KEYS, "leverancier", "Kop"), "leverancier", "Kop"),
        "date": _as_text(_pick(raw, _DATE_KEYS, "datum", "Kop"), "datum", "Kop"),
        "lines": lines,
        "total": total,
        "total_stated": total_stated,
        "lines_sum": lines_sum,
    }


def _pick(d: dict[str, Any], keys: tuple[str, ...], label: str, where: str,
          *, numeric: bool = False) -> Any:
    """Return the value of the alias column that is filled in.

    When more than one alias carries a value and they disagree (say
    `quantity` 20 and `quantity_billed` 22), there is no safe way to choose
    one: the file is rejected instead of the first alias silently winning.
    """
    found = [(k, d[k]) for k in keys if k in d and d[k] not in (None, "")]
    if not found:
        return None
    first_key, first_val = found[0]
    for key, val in found[1:]:
        if numeric:
            same = _to_float(val, label, where) == _to_float(first_val, label, where)
        else:
            same = str(val).strip() == str(first_val).strip()
        if not same:
            raise ParseError(
                f"{where}: kolommen '{first_key}' en '{key}' geven verschillende "
                f"waarden voor {label} ({_short(first_val)} vs {_short(val)}). "
                "Laat één van beide weg."
            )
    return first_val


_NUMBER_RE = re.compile(r"^\d[\d.,]*$")


def _to_float(v: Any, label: str = "getal", where: str = "") -> float | None:
    """Parse an amount or quantity. Fails closed on anything ambiguous,
    negative, non-finite (NaN, inf, 1e309) or absurdly large."""
    prefix = f"{where}: " if where else ""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        raise ParseError(f"{prefix}{label} '{v}' is geen getal.")
    if isinstance(v, (int, float)):
        try:
            val = float(v)
        except OverflowError:
            raise ParseError(f"{prefix}{label} is te groot.")
    else:
        val = _parse_number_text(str(v), label, prefix)

    if not math.isfinite(val):
        raise ParseError(f"{prefix}{label} '{_short(v)}' is geen eindig getal.")
    if val < 0:
        raise ParseError(
            f"{prefix}{label} '{_short(v)}' is negatief. Creditnota's en "
            "negatieve regels worden niet ondersteund."
        )
    if val > MAX_AMOUNT:
        raise ParseError(f"{prefix}{label} '{_short(v)}' is onrealistisch groot.")
    return val


def _parse_number_text(text: str, label: str, prefix: str) -> float:
    s = text.strip()
    for ch in ("€", " ", " ", " "):
        s = s.replace(ch, "")
    if s.startswith("-"):
        raise ParseError(
            f"{prefix}{label} '{_short(text)}' is negatief. Creditnota's en "
            "negatieve regels worden niet ondersteund."
        )
    if not _NUMBER_RE.match(s):
        # Rejects NaN, inf, 1e309, formulas and anything else that is not
        # plainly written digits.
        raise ParseError(f"{prefix}{label} '{_short(text)}' is geen geldig getal.")

    commas, dots = s.count(","), s.count(".")
    if commas and dots:
        # Both separators: the last one is the decimal separator.
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        int_part, _, frac = s.rpartition(dec)
        if thou in frac or int_part.count(dec):
            raise ParseError(f"{prefix}{label} '{_short(text)}' is geen geldig getal.")
        _check_grouping(int_part, thou, text, label, prefix)
        return float(int_part.replace(thou, "") + "." + frac)

    sep = "," if commas else "." if dots else ""
    if not sep:
        return float(s)
    count = commas or dots
    if count > 1:
        # 1.234.567 or 1,234,567: thousands separators only.
        _check_grouping(s, sep, text, label, prefix)
        return float(s.replace(sep, ""))
    int_part, _, frac = s.partition(sep)
    if len(frac) == 3 and int_part not in ("", "0"):
        raise ParseError(
            f"{prefix}{label} '{_short(text)}' is dubbelzinnig: het kan duizendtallen "
            "of decimalen zijn. Schrijf het zonder scheidingsteken voor duizendtallen "
            "(bijv. 1000 of 1000.00)."
        )
    return float(int_part + "." + frac)


def _check_grouping(int_part: str, sep: str, text: str, label: str, prefix: str) -> None:
    groups = int_part.split(sep)
    if not (1 <= len(groups[0]) <= 3) or any(len(g) != 3 for g in groups[1:]):
        raise ParseError(f"{prefix}{label} '{_short(text)}' heeft een ongeldige duizendtal-notatie.")


def _as_text(v: Any, label: str, where: str) -> str:
    """Validate a text field: no control characters, bounded length, and no
    leading formula character that a spreadsheet would execute."""
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        raise ParseError(f"{where}: {label} moet tekst zijn.")
    s = str(v).strip()
    if not s:
        return ""
    if len(s) > MAX_TEXT_LENGTH:
        raise ParseError(f"{where}: {label} is langer dan {MAX_TEXT_LENGTH} tekens.")
    if any(ord(c) < 32 or ord(c) == 127 for c in s):
        raise ParseError(f"{where}: {label} bevat stuurtekens.")
    if s.startswith(_FORMULA_PREFIXES) and not isinstance(v, (int, float)):
        raise ParseError(
            f"{where}: {label} '{_short(s)}' begint met '{s[0]}'. Een spreadsheet "
            "voert zo'n cel uit als formule; verwijder het teken of zet er tekst voor."
        )
    return s


def _short(v: Any, limit: int = 40) -> str:
    s = str(v)
    return s if len(s) <= limit else s[:limit] + "…"
