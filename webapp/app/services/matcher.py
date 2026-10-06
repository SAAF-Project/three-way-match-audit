"""Three-way match logic.

Compares a purchase order (PO), goods receipt (GRN) and invoice at both the
header and line level and produces a per-line + overall verdict:

  MATCH   — everything aligns within tolerance
  WARNING — non-critical difference (e.g. small qty variance, missing GRN price)
  FAIL    — material mismatch (qty or amount outside tolerance, missing line)

All user-visible issue text goes through a `messages` dict (loaded from the
i18n JSON files) so the matcher can produce output in any language without
code changes. Severity is driven by the key that was emitted, not by the
language-specific message text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Verdict = Literal["MATCH", "WARNING", "FAIL"]

# Default tolerances — configurable per call.
DEFAULT_PRICE_TOLERANCE = 0.01       # € on unit price
DEFAULT_QTY_TOLERANCE = 0.0          # units
DEFAULT_TOTAL_TOLERANCE = 0.05       # € on document total
DEFAULT_LINE_TOTAL_TOLERANCE = 0.01  # € on per-line amount

# Default Dutch message templates — matches the historical behaviour when
# three_way_match() is called without a `messages` argument (e.g. unit tests
# and the CLI). The webapp passes the loaded i18n dict instead.
DEFAULT_MESSAGES: dict[str, str] = {
    "po_missing_number":     "PO bevat geen inkoopordernummer.",
    "po_ref_grn_differs":    "PO-referentie op goederenontvangst wijkt af: '{grn_po}' vs PO '{po_num}'.",
    "po_ref_inv_differs":    "PO-referentie op factuur wijkt af: '{inv_po}' vs PO '{po_num}'.",
    "supplier_inconsistent": "Leveranciernaam is niet consistent tussen documenten: {names}.",
    "total_discrepancy":     "Totale afwijking PO ↔ factuur: {disc} (PO {po_total} → factuur {inv_total}).",
    "line_missing_po":       "Regel ontbreekt op de inkooporder.",
    "line_missing_inv":      "Regel ontbreekt op de factuur.",
    "line_missing_grn":      "Regel ontbreekt op de goederenontvangst.",
    "qty_billed_vs_po":      "Gefactureerd aantal wijkt af van PO: {inv_qty} vs {po_qty}.",
    "qty_received_more_po":  "Ontvangen aantal groter dan besteld: {grn_qty} vs {po_qty}.",
    "qty_received_less_po":  "Ontvangen aantal minder dan besteld: {grn_qty} vs {po_qty}.",
    "qty_billed_vs_grn":     "Gefactureerd aantal groter dan ontvangen: {inv_qty} vs {grn_qty}.",
    "price_differs":         "Stukprijs wijkt af: PO {po_price} → factuur {inv_price}.",
    "line_total_differs":    "Regeltotaal wijkt af: PO {po_total} → factuur {inv_total}.",
}

# Which header issue KEYS roll up to FAIL. Everything else is WARNING-level.
# Driven by key, so wording / language changes can't silently flip severity.
_HEADER_FAIL_KEYS = frozenset({
    "po_ref_grn_differs",
    "po_ref_inv_differs",
    "supplier_inconsistent",
})


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
    po_total: float
    grn_total: float | None
    inv_total: float
    totals_discrepancy: float
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
    msgs = {**DEFAULT_MESSAGES, **(messages or {})}

    header_entries = _check_header(po, grn, inv, msgs)
    header_issues = [e["text"] for e in header_entries]
    header_has_fail = any(e["key"] in _HEADER_FAIL_KEYS for e in header_entries)

    # Build line lookup by (line_number, sku) — prefer sku, fall back to line_number.
    po_lines = _index_lines(po.get("lines", []))
    grn_lines = _index_lines(grn.get("lines", []))
    inv_lines = _index_lines(inv.get("lines", []))

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
            po_qty=(po_l or {}).get("quantity"),
            grn_qty=(grn_l or {}).get("quantity"),
            inv_qty=(inv_l or {}).get("quantity"),
            po_price=(po_l or {}).get("unit_price"),
            inv_price=(inv_l or {}).get("unit_price"),
            po_total=(po_l or {}).get("line_total"),
            inv_total=(inv_l or {}).get("line_total"),
        )

        _grade_line(lr, po_l, grn_l, inv_l,
                    qty_tolerance=qty_tolerance,
                    price_tolerance=price_tolerance,
                    line_total_tolerance=line_total_tolerance,
                    msgs=msgs)
        line_results.append(lr)

    po_total = float(po.get("total") or 0.0)
    grn_total = grn.get("total")
    inv_total = float(inv.get("total") or 0.0)
    disc = round(inv_total - po_total, 2)

    if abs(disc) > total_tolerance:
        header_issues.append(msgs["total_discrepancy"].format(
            disc=_eur(disc), po_total=_eur(po_total), inv_total=_eur(inv_total),
        ))

    result = _rollup(line_results, header_has_fail, disc, total_tolerance, header_issues)

    return MatchReport(
        result=result,
        header_issues=header_issues,
        line_results=line_results,
        po_total=po_total,
        grn_total=float(grn_total) if grn_total is not None else None,
        inv_total=inv_total,
        totals_discrepancy=disc,
        po=_doc_meta(po),
        grn=_doc_meta(grn),
        inv=_doc_meta(inv),
    )


# ---------------------------------------------------------------------------
# Header checks
# ---------------------------------------------------------------------------
def _check_header(po, grn, inv, msgs: dict[str, str]) -> list[dict[str, str]]:
    """Return a list of {"key": <msg_key>, "text": <formatted text>} entries.

    Keeping the key alongside the text means severity rollup is driven by
    identifier instead of by searching the (now translatable) text.
    """
    entries: list[dict[str, str]] = []
    po_num = po.get("po_number") or po.get("document_number") or ""
    grn_po = grn.get("po_number") or ""
    inv_po = inv.get("po_number") or ""

    def add(key: str, **vars) -> None:
        entries.append({"key": key, "text": msgs[key].format(**vars)})

    if not po_num:
        add("po_missing_number")
    if grn_po and po_num and grn_po != po_num:
        add("po_ref_grn_differs", grn_po=grn_po, po_num=po_num)
    if inv_po and po_num and inv_po != po_num:
        add("po_ref_inv_differs", inv_po=inv_po, po_num=po_num)

    suppliers = {d.get("supplier", "").strip().lower() for d in (po, grn, inv) if d.get("supplier")}
    if len({s for s in suppliers if s}) > 1:
        names = " / ".join(sorted(d.get("supplier", "") for d in (po, grn, inv) if d.get("supplier")))
        add("supplier_inconsistent", names=names)

    return entries


# ---------------------------------------------------------------------------
# Line-level checks
# ---------------------------------------------------------------------------
def _index_lines(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for line in lines:
        key = _line_key(line)
        # If duplicate keys appear, sum the quantities (rare, but possible in GRN partial receipts).
        if key in out:
            existing = out[key]
            for fld in ("quantity", "line_total"):
                a = existing.get(fld)
                b = line.get(fld)
                if a is not None and b is not None:
                    existing[fld] = round(a + b, 4)
                elif b is not None:
                    existing[fld] = b
        else:
            out[key] = dict(line)
    return out


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
) -> None:
    msgs = msgs or DEFAULT_MESSAGES
    # Track which categories of issue have fired this line, instead of
    # grepping the text later — the text is translated.
    emitted: set[str] = set()

    def add(key: str, severity: Verdict, **vars) -> None:
        lr.issues.append(msgs[key].format(**vars))
        emitted.add(key)
        if severity == "FAIL" or (severity == "WARNING" and lr.result == "MATCH"):
            lr.result = severity

    if po_l is None:
        add("line_missing_po", "FAIL")
    if inv_l is None:
        add("line_missing_inv", "FAIL")
    if grn_l is None:
        add("line_missing_grn", "WARNING")

    # Quantity checks — always compare what we have.
    po_qty = _num(po_l, "quantity")
    grn_qty = _num(grn_l, "quantity")
    inv_qty = _num(inv_l, "quantity")

    if po_qty is not None and inv_qty is not None and abs(inv_qty - po_qty) > qty_tolerance:
        add("qty_billed_vs_po", "FAIL", inv_qty=_num_str(inv_qty), po_qty=_num_str(po_qty))
    if po_qty is not None and grn_qty is not None and abs(grn_qty - po_qty) > qty_tolerance:
        # Over-receipt is worse than short-receipt.
        if grn_qty > po_qty:
            add("qty_received_more_po", "FAIL", grn_qty=_num_str(grn_qty), po_qty=_num_str(po_qty))
        else:
            add("qty_received_less_po", "WARNING", grn_qty=_num_str(grn_qty), po_qty=_num_str(po_qty))
    if grn_qty is not None and inv_qty is not None and abs(inv_qty - grn_qty) > qty_tolerance:
        if inv_qty > grn_qty:
            add("qty_billed_vs_grn", "FAIL", inv_qty=_num_str(inv_qty), grn_qty=_num_str(grn_qty))

    # Price / total checks.
    po_price = _num(po_l, "unit_price")
    inv_price = _num(inv_l, "unit_price")
    if po_price is not None and inv_price is not None and abs(inv_price - po_price) > price_tolerance:
        add("price_differs", "FAIL", po_price=_eur(po_price), inv_price=_eur(inv_price))

    po_total = _num(po_l, "line_total")
    inv_total = _num(inv_l, "line_total")
    if po_total is not None and inv_total is not None and abs(inv_total - po_total) > line_total_tolerance:
        # Only flag if not already caught by qty/price mismatch — the line
        # total discrepancy is implied by those and would just be noise.
        caught_already = emitted & {
            "qty_billed_vs_po", "qty_received_more_po", "qty_received_less_po",
            "qty_billed_vs_grn", "price_differs",
        }
        if not caught_already:
            add("line_total_differs", "FAIL", po_total=_eur(po_total), inv_total=_eur(inv_total))


def _rollup(lines, header_has_fail: bool, disc: float, total_tolerance: float,
            header_issues: list[str]) -> Verdict:
    if any(l.result == "FAIL" for l in lines):
        return "FAIL"
    if header_has_fail:
        return "FAIL"
    if abs(disc) > total_tolerance:
        return "FAIL"
    if any(l.result == "WARNING" for l in lines) or header_issues:
        return "WARNING"
    return "MATCH"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _num(line: dict[str, Any] | None, key: str) -> float | None:
    if not line:
        return None
    v = line.get(key)
    return None if v is None else float(v)


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
        "total": d.get("total"),
        "line_count": len(d.get("lines", [])),
    }
