"""Three-way match logic.

Compares a purchase order (PO), goods receipt (GRN) and invoice at both the
header and line level and produces a per-line + overall verdict:

  MATCH   — everything aligns within tolerance
  WARNING — non-critical difference (e.g. short receipt that is not invoiced)
  FAIL    — material mismatch, or a value needed for a check is missing

No silent pass: a check that cannot be performed because a value is
missing, not a number, or contradicted elsewhere in the same document is a
FAIL, never a quiet skip.

All user-visible issue text goes through a `messages` dict (loaded from the
i18n JSON files) so the matcher can produce output in any language without
code changes. Severity is driven by the key that was emitted, not by the
language-specific message text.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

Verdict = Literal["MATCH", "WARNING", "FAIL"]

# Default tolerances — configurable per call.
DEFAULT_PRICE_TOLERANCE = 0.01       # € on unit price
DEFAULT_QTY_TOLERANCE = 0.0          # units
DEFAULT_TOTAL_TOLERANCE = 0.05       # € on document total
DEFAULT_LINE_TOTAL_TOLERANCE = 0.01  # € on per-line amount

# Upper bound for every tolerance. A tolerance this wide already makes the
# check meaningless; above it the match would pass almost anything.
MAX_TOLERANCE = 100.0

# Float noise allowance, so 3 × 0.10 equals 0.30 even with a zero tolerance.
_EPS = 1e-9

# Default Dutch message templates — matches the historical behaviour when
# three_way_match() is called without a `messages` argument (e.g. unit tests
# and the CLI). The webapp passes the loaded i18n dict instead.
DEFAULT_MESSAGES: dict[str, str] = {
    "doc_po":                "Inkooporder",
    "doc_grn":               "Goederenontvangst",
    "doc_inv":               "Factuur",
    "field_quantity":        "aantal",
    "field_unit_price":      "stukprijs",
    "field_line_total":      "regeltotaal",

    "po_missing_number":     "PO bevat geen inkoopordernummer.",
    "missing_doc_number":    "{doc} bevat geen documentnummer.",
    "missing_po_ref":        "{doc} bevat geen PO-referentie.",
    "missing_supplier":      "{doc} bevat geen leveranciersnaam.",
    "missing_total":         "{doc} bevat geen documenttotaal en geen regeltotalen.",
    "po_ref_grn_differs":    "PO-referentie op goederenontvangst wijkt af: '{grn_po}' vs PO '{po_num}'.",
    "po_ref_inv_differs":    "PO-referentie op factuur wijkt af: '{inv_po}' vs PO '{po_num}'.",
    "supplier_inconsistent": "Leveranciernaam is niet consistent tussen documenten: {names}.",
    "total_vs_lines":        "{doc}: vermeld totaal {total} wijkt af van de som van de regels {lines_sum}.",
    "total_discrepancy":     "Totale afwijking PO ↔ factuur: {disc} (PO {po_total} → factuur {inv_total}).",

    "line_missing_po":       "Regel ontbreekt op de inkooporder.",
    "line_missing_inv":      "Regel ontbreekt op de factuur.",
    "line_missing_grn":      "Regel ontbreekt op de goederenontvangst.",
    "value_missing":         "{doc}: {field} ontbreekt of is geen geldig getal.",
    "line_arithmetic":       "{doc}: aantal × stukprijs ({qty} × {price} = {expected}) komt niet overeen met regeltotaal {total}.",
    "dup_price_differs":     "{doc}: artikel staat op meerdere regels met verschillende stukprijzen: {prices}.",
    "qty_billed_vs_po":      "Gefactureerd aantal wijkt af van PO: {inv_qty} vs {po_qty}.",
    "qty_received_more_po":  "Ontvangen aantal groter dan besteld: {grn_qty} vs {po_qty}.",
    "qty_received_less_po":  "Ontvangen aantal minder dan besteld: {grn_qty} vs {po_qty}.",
    "qty_billed_vs_grn":     "Gefactureerd aantal groter dan ontvangen: {inv_qty} vs {grn_qty}.",
    "price_differs":         "Stukprijs wijkt af: PO {po_price} → factuur {inv_price}.",
    "line_total_differs":    "Regeltotaal wijkt af: PO {po_total} → factuur {inv_total}.",
}

# Every header finding is material: a missing reference or supplier means the
# documents cannot be shown to belong together. Driven by key, so wording /
# language changes can't silently flip severity.
_HEADER_FAIL_KEYS = frozenset({
    "po_missing_number",
    "missing_doc_number",
    "missing_po_ref",
    "missing_supplier",
    "missing_total",
    "po_ref_grn_differs",
    "po_ref_inv_differs",
    "supplier_inconsistent",
    "total_vs_lines",
})

_DOC_KEYS = {"PO": "doc_po", "GRN": "doc_grn", "INVOICE": "doc_inv"}


@dataclass
class LineResult:
    line_number: int
    sku: str
    description: str
    po_qty: float | None
    grn_qty: float | None
    inv_qty: float | None
    po_price: float | None
    inv_price: float | None
    po_total: float | None
    inv_total: float | None
    result: Verdict = "MATCH"
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_number": self.line_number,
            "sku": self.sku,
            "description": self.description,
            "po_qty": self.po_qty,
            "grn_qty": self.grn_qty,
            "inv_qty": self.inv_qty,
            "po_price": self.po_price,
            "inv_price": self.inv_price,
            "po_total": self.po_total,
            "inv_total": self.inv_total,
            "result": self.result,
            "issues": self.issues,
        }


@dataclass
class MatchReport:
    result: Verdict
    header_issues: list[str]
    line_results: list[LineResult]
    po_total: float | None
    grn_total: float | None
    inv_total: float | None
    totals_discrepancy: float | None
    po: dict[str, Any]
    grn: dict[str, Any]
    inv: dict[str, Any]

    def summary(self) -> dict[str, int]:
        counts = {"MATCH": 0, "WARNING": 0, "FAIL": 0}
        for lr in self.line_results:
            counts[lr.result] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "header_issues": self.header_issues,
            "line_results": [lr.to_dict() for lr in self.line_results],
            "po_total": self.po_total,
            "grn_total": self.grn_total,
            "inv_total": self.inv_total,
            "totals_discrepancy": self.totals_discrepancy,
            "summary": self.summary(),
            "po": self.po,
            "grn": self.grn,
            "inv": self.inv,
        }


def validate_tolerance(name: str, value: Any) -> float:
    """Return `value` as a float, or raise ValueError when it is not a
    finite number between 0 and MAX_TOLERANCE."""
    try:
        val = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} is not a number")
    if not math.isfinite(val) or val < 0 or val > MAX_TOLERANCE:
        raise ValueError(f"{name} must be between 0 and {MAX_TOLERANCE:g}")
    return val


def three_way_match(
    po: dict[str, Any],
    grn: dict[str, Any],
    inv: dict[str, Any],
    *,
    price_tolerance: float = DEFAULT_PRICE_TOLERANCE,
    qty_tolerance: float = DEFAULT_QTY_TOLERANCE,
    total_tolerance: float = DEFAULT_TOTAL_TOLERANCE,
    line_total_tolerance: float = DEFAULT_LINE_TOTAL_TOLERANCE,
    messages: dict[str, str] | None = None,
) -> MatchReport:
    price_tolerance = validate_tolerance("price_tolerance", price_tolerance)
    qty_tolerance = validate_tolerance("qty_tolerance", qty_tolerance)
    total_tolerance = validate_tolerance("total_tolerance", total_tolerance)
    line_total_tolerance = validate_tolerance("line_total_tolerance", line_total_tolerance)
    msgs = {**DEFAULT_MESSAGES, **(messages or {})}

    header_entries = _check_header(po, grn, inv, msgs, total_tolerance)
    header_issues = [e["text"] for e in header_entries]
    header_has_fail = any(e["key"] in _HEADER_FAIL_KEYS for e in header_entries)

    # Build line lookup by sku, falling back to line_number.
    tol = {"price": price_tolerance, "line_total": line_total_tolerance}
    po_lines, po_row_issues = _index_lines(po.get("lines", []), "PO", tol, msgs)
    grn_lines, grn_row_issues = _index_lines(grn.get("lines", []), "GRN", tol, msgs)
    inv_lines, inv_row_issues = _index_lines(inv.get("lines", []), "INVOICE", tol, msgs)

    all_keys = list(dict.fromkeys(list(po_lines) + list(grn_lines) + list(inv_lines)))
    line_results: list[LineResult] = []

    for key in all_keys:
        po_l = po_lines.get(key)
        grn_l = grn_lines.get(key)
        inv_l = inv_lines.get(key)

        anchor = po_l or inv_l or grn_l or {}
        lr = LineResult(
            line_number=int(anchor.get("line_number") or 0),
            sku=anchor.get("sku", ""),
            description=anchor.get("description", ""),
            po_qty=_num(po_l, "quantity"),
            grn_qty=_num(grn_l, "quantity"),
            inv_qty=_num(inv_l, "quantity"),
            po_price=_num(po_l, "unit_price"),
            inv_price=_num(inv_l, "unit_price"),
            po_total=_num(po_l, "line_total"),
            inv_total=_num(inv_l, "line_total"),
        )

        row_issues = (po_row_issues.get(key, []) + grn_row_issues.get(key, [])
                      + inv_row_issues.get(key, []))
        _grade_line(lr, po_l, grn_l, inv_l,
                    qty_tolerance=qty_tolerance,
                    price_tolerance=price_tolerance,
                    line_total_tolerance=line_total_tolerance,
                    msgs=msgs,
                    row_issues=row_issues)
        line_results.append(lr)

    po_total = _finite(po.get("total"))
    grn_total = _finite(grn.get("total"))
    inv_total = _finite(inv.get("total"))
    disc: float | None = None
    if po_total is not None and inv_total is not None:
        disc = round(inv_total - po_total, 2)
        if abs(disc) > total_tolerance + _EPS:
            header_issues.append(msgs["total_discrepancy"].format(
                disc=_eur(disc), po_total=_eur(po_total), inv_total=_eur(inv_total),
            ))
            header_has_fail = True

    result = _rollup(line_results, header_has_fail, header_issues)

    return MatchReport(
        result=result,
        header_issues=header_issues,
        line_results=line_results,
        po_total=po_total,
        grn_total=grn_total,
        inv_total=inv_total,
        totals_discrepancy=disc,
        po=_doc_meta(po),
        grn=_doc_meta(grn),
        inv=_doc_meta(inv),
    )


# ---------------------------------------------------------------------------
# Header checks
# ---------------------------------------------------------------------------
def _check_header(po, grn, inv, msgs: dict[str, str],
                  total_tolerance: float = DEFAULT_TOTAL_TOLERANCE) -> list[dict[str, str]]:
    """Return a list of {"key": <msg_key>, "text": <formatted text>} entries.

    Keeping the key alongside the text means severity rollup is driven by
    identifier instead of by searching the (now translatable) text.

    Every reference the match relies on must be present: an empty PO
    reference or supplier would otherwise skip its consistency check and
    let unrelated documents pass as a match.
    """
    entries: list[dict[str, str]] = []

    def add(key: str, **vars) -> None:
        entries.append({"key": key, "text": msgs[key].format(**vars)})

    def doc(d: dict[str, Any], fallback: str) -> str:
        return msgs[_DOC_KEYS.get(d.get("document_type") or fallback, "doc_po")]

    po_num = _text(po.get("po_number")) or _text(po.get("document_number"))
    grn_po = _text(grn.get("po_number"))
    inv_po = _text(inv.get("po_number"))

    if not po_num:
        add("po_missing_number")
    for d, fallback in ((grn, "GRN"), (inv, "INVOICE")):
        if not _text(d.get("document_number")):
            add("missing_doc_number", doc=doc(d, fallback))
    if not grn_po:
        add("missing_po_ref", doc=doc(grn, "GRN"))
    if not inv_po:
        add("missing_po_ref", doc=doc(inv, "INVOICE"))
    if grn_po and po_num and grn_po != po_num:
        add("po_ref_grn_differs", grn_po=grn_po, po_num=po_num)
    if inv_po and po_num and inv_po != po_num:
        add("po_ref_inv_differs", inv_po=inv_po, po_num=po_num)

    suppliers = []
    for d, fallback in ((po, "PO"), (grn, "GRN"), (inv, "INVOICE")):
        name = _text(d.get("supplier"))
        if not name:
            add("missing_supplier", doc=doc(d, fallback))
        else:
            suppliers.append(name)
    if len({" ".join(s.casefold().split()) for s in suppliers}) > 1:
        add("supplier_inconsistent", names=" / ".join(suppliers))

    # Totals: the PO and invoice need one, and a stated total must agree with
    # the lines in the same document.
    for d, fallback in ((po, "PO"), (inv, "INVOICE")):
        total = _finite(d.get("total"))
        if total is None:
            add("missing_total", doc=doc(d, fallback))
            continue
        lines_sum = _finite(d.get("lines_sum"))
        if d.get("total_stated") and lines_sum is not None \
                and abs(total - lines_sum) > total_tolerance + _EPS:
            add("total_vs_lines", doc=doc(d, fallback),
                total=_eur(total), lines_sum=_eur(lines_sum))

    return entries


# ---------------------------------------------------------------------------
# Line-level checks
# ---------------------------------------------------------------------------
def _index_lines(
    lines: list[dict[str, Any]],
    doc_type: str,
    tol: dict[str, float],
    msgs: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[tuple[str, str]]]]:
    """Index lines by key and collect row-level findings per key.

    Row-level checks run before rows with the same SKU are combined, because
    combining hides them: per row, quantity × unit price must equal the line
    total, and rows of one SKU must share one unit price. Combined rows get
    the summed quantity and total and the weighted unit price; a value that
    is missing on any of the rows stays missing.
    """
    doc = msgs[_DOC_KEYS[doc_type]]
    issues: dict[str, list[tuple[str, str]]] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}

    for line in lines:
        key = _line_key(line)
        grouped.setdefault(key, []).append(line)
        qty = _num(line, "quantity")
        price = _num(line, "unit_price")
        total = _num(line, "line_total")
        if qty is not None and price is not None and total is not None:
            expected = round(qty * price, 2)
            if abs(expected - total) > tol["line_total"] + _EPS:
                issues.setdefault(key, []).append(("FAIL", msgs["line_arithmetic"].format(
                    doc=doc, qty=_num_str(qty), price=_eur(price),
                    expected=_eur(expected), total=_eur(total))))

    out: dict[str, dict[str, Any]] = {}
    for key, rows in grouped.items():
        combined = dict(rows[0])
        if len(rows) > 1:
            for fld in ("quantity", "line_total"):
                vals = [_num(r, fld) for r in rows]
                combined[fld] = None if any(v is None for v in vals) else round(sum(vals), 4)
            prices = [_num(r, "unit_price") for r in rows]
            known = [p for p in prices if p is not None]
            if known and max(known) - min(known) > tol["price"] + _EPS:
                issues.setdefault(key, []).append(("FAIL", msgs["dup_price_differs"].format(
                    doc=doc, prices=", ".join(_eur(p) for p in known))))
            if any(p is None for p in prices):
                combined["unit_price"] = None
            elif combined["quantity"] and combined["line_total"] is not None:
                combined["unit_price"] = round(combined["line_total"] / combined["quantity"], 4)
        out[key] = combined
    return out, issues


def _line_key(line: dict[str, Any]) -> str:
    sku = (line.get("sku") or "").strip().upper()
    if sku:
        return f"SKU:{sku}"
    ln = line.get("line_number")
    return f"LINE:{ln}" if ln is not None else f"DESC:{(line.get('description') or '').strip().lower()}"


def _grade_line(
    lr: LineResult,
    po_l: dict[str, Any] | None,
    grn_l: dict[str, Any] | None,
    inv_l: dict[str, Any] | None,
    *,
    qty_tolerance: float,
    price_tolerance: float,
    line_total_tolerance: float = DEFAULT_LINE_TOTAL_TOLERANCE,
    msgs: dict[str, str] | None = None,
    row_issues: list[tuple[str, str]] | None = None,
) -> None:
    msgs = {**DEFAULT_MESSAGES, **(msgs or {})}
    # Track which categories of issue have fired this line, instead of
    # grepping the text later — the text is translated.
    emitted: set[str] = set()

    def raise_to(severity: Verdict) -> None:
        if severity == "FAIL" or (severity == "WARNING" and lr.result == "MATCH"):
            lr.result = severity

    def add(key: str, severity: Verdict, **vars) -> None:
        lr.issues.append(msgs[key].format(**vars))
        emitted.add(key)
        raise_to(severity)

    for severity, text in row_issues or []:
        lr.issues.append(text)
        raise_to(severity)  # type: ignore[arg-type]

    if po_l is None:
        add("line_missing_po", "FAIL")
    if inv_l is None:
        add("line_missing_inv", "FAIL")
    if grn_l is None:
        # Billing for goods that were never received is the case a 3-way
        # match exists to stop; an open PO line that is not billed yet is not.
        add("line_missing_grn", "FAIL" if inv_l is not None else "WARNING")

    # Values every check below needs. Missing means FAIL, not "skip the check".
    required = (
        (po_l, "doc_po", ("quantity", "unit_price")),
        (grn_l, "doc_grn", ("quantity",)),
        (inv_l, "doc_inv", ("quantity", "unit_price", "line_total")),
    )
    for line, doc_key, fields in required:
        if line is None:
            continue
        for fld in fields:
            if _num(line, fld) is None:
                add("value_missing", "FAIL", doc=msgs[doc_key], field=msgs[f"field_{fld}"])

    # Quantity checks — always compare what we have.
    po_qty = _num(po_l, "quantity")
    grn_qty = _num(grn_l, "quantity")
    inv_qty = _num(inv_l, "quantity")

    if po_qty is not None and inv_qty is not None and abs(inv_qty - po_qty) > qty_tolerance + _EPS:
        add("qty_billed_vs_po", "FAIL", inv_qty=_num_str(inv_qty), po_qty=_num_str(po_qty))
    if po_qty is not None and grn_qty is not None and abs(grn_qty - po_qty) > qty_tolerance + _EPS:
        # Over-receipt is worse than short-receipt.
        if grn_qty > po_qty:
            add("qty_received_more_po", "FAIL", grn_qty=_num_str(grn_qty), po_qty=_num_str(po_qty))
        else:
            add("qty_received_less_po", "WARNING", grn_qty=_num_str(grn_qty), po_qty=_num_str(po_qty))
    if grn_qty is not None and inv_qty is not None and inv_qty - grn_qty > qty_tolerance + _EPS:
        add("qty_billed_vs_grn", "FAIL", inv_qty=_num_str(inv_qty), grn_qty=_num_str(grn_qty))

    # Price / total checks.
    po_price = _num(po_l, "unit_price")
    inv_price = _num(inv_l, "unit_price")
    if po_price is not None and inv_price is not None and abs(inv_price - po_price) > price_tolerance + _EPS:
        add("price_differs", "FAIL", po_price=_eur(po_price), inv_price=_eur(inv_price))

    po_total = _num(po_l, "line_total")
    inv_total = _num(inv_l, "line_total")
    if po_total is not None and inv_total is not None and abs(inv_total - po_total) > line_total_tolerance + _EPS:
        # Only flag if not already caught by qty/price mismatch — the line
        # total discrepancy is implied by those and would just be noise.
        caught_already = emitted & {
            "qty_billed_vs_po", "qty_received_more_po", "qty_received_less_po",
            "qty_billed_vs_grn", "price_differs",
        }
        if not caught_already:
            add("line_total_differs", "FAIL", po_total=_eur(po_total), inv_total=_eur(inv_total))


def _rollup(lines, header_has_fail: bool, header_issues: list[str]) -> Verdict:
    if any(l.result == "FAIL" for l in lines):
        return "FAIL"
    if header_has_fail:
        return "FAIL"
    if any(l.result == "WARNING" for l in lines) or header_issues:
        return "WARNING"
    return "MATCH"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _finite(v: Any) -> float | None:
    """float(v) when it is a finite number, else None. NaN and infinity are
    treated as missing so that no comparison silently evaluates to False."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _num(line: dict[str, Any] | None, key: str) -> float | None:
    if not line:
        return None
    return _finite(line.get(key))


def _text(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _num_str(v: float) -> str:
    return f"{v:g}"


def _eur(v: float) -> str:
    return f"€{v:,.2f}"


def _doc_meta(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_type": d.get("document_type"),
        "document_number": d.get("document_number"),
        "po_number": d.get("po_number"),
        "supplier": d.get("supplier"),
        "date": d.get("date"),
        "total": _finite(d.get("total")),
        "line_count": len(d.get("lines", [])),
    }
