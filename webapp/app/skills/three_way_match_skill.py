"""SAAF reusable skill: P2P 3-way match audit with AI risk assessment.

This module exposes ``run()`` as the SAAF skill entry point.
Other agents can import and call it directly, or invoke it via the
/api/match/explain HTTP endpoint.

Guardrails:
- The AI agent is advisory only; match_report is always the authoritative output.
- The Claude model is read-only: it cannot modify verdicts, tolerances, or inputs.
- If ANTHROPIC_API_KEY is absent the skill returns the rule-based result only.
"""
from __future__ import annotations

from typing import Any

from app.services.agent import audit_narrative
from app.services.audit_log import build as build_audit_log
from app.services.matcher import three_way_match
from app.services.parsers import ParseError, parse_document


async def run(
    po: bytes,
    grn: bytes,
    invoice: bytes,
    *,
    po_filename: str = "po",
    grn_filename: str = "grn",
    invoice_filename: str = "invoice",
    price_tolerance: float = 0.01,
    qty_tolerance: float = 0.0,
    total_tolerance: float = 0.05,
) -> dict[str, Any]:
    """SAAF skill: P2P 3-way match audit with AI risk assessment and audit trail.

    Args:
        po: Raw bytes of the purchase order (CSV or JSON).
        grn: Raw bytes of the goods receipt note (CSV or JSON).
        invoice: Raw bytes of the supplier invoice (CSV or JSON).
        po_filename: Original filename, used for format detection.
        grn_filename: Original filename, used for format detection.
        invoice_filename: Original filename, used for format detection.
        price_tolerance: Maximum acceptable unit price delta (default 0.01 = €0.01).
        qty_tolerance: Maximum acceptable quantity delta (default 0 = exact match).
        total_tolerance: Maximum acceptable document total delta (default 0.05 = €0.05).

    Returns:
        A dict with keys:
          - ``match_report``: authoritative rule-based results (always present)
          - ``audit_narrative``: AI risk assessment (None if API key absent or call failed)
          - ``audit_trail``: full re-performance record with input hashes

    Raises:
        ParseError: if any input file cannot be parsed.
    """
    po_doc = parse_document(po, po_filename, "PO")
    grn_doc = parse_document(grn, grn_filename, "GRN")
    inv_doc = parse_document(invoice, invoice_filename, "INVOICE")

    report = three_way_match(
        po_doc, grn_doc, inv_doc,
        price_tolerance=price_tolerance,
        qty_tolerance=qty_tolerance,
        total_tolerance=total_tolerance,
    )
    report_dict = report.to_dict()
    narrative = audit_narrative(report_dict)
    trail = build_audit_log(
        po_bytes=po, grn_bytes=grn, invoice_bytes=invoice,
        po_filename=po_filename,
        grn_filename=grn_filename,
        invoice_filename=invoice_filename,
        price_tolerance=price_tolerance,
        qty_tolerance=qty_tolerance,
        total_tolerance=total_tolerance,
        match_report=report_dict,
        audit_narrative=narrative,
    )

    return {
        "match_report": report_dict,
        "audit_narrative": narrative,
        "audit_trail": trail,
    }
