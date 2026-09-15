"""Audit workpaper builder.

Produces a single self-contained JSON document that captures everything an
audit-file needs to prove completeness and correctness of one 3-way match:

  * The raw source files that were used, identified by SHA-256 (so a
    reviewer can independently re-hash the files they receive and confirm
    they are the same bytes that were matched).
  * The parsed / normalised representation of each document (so the match
    can be re-run without touching the raw CSV/JSON parsers).
  * The exact match parameters (tolerances, tool version).
  * The full match result, per line, with every issue message.
  * An attestation block for reviewer sign-off.

The file is designed to be:
  * Reproducible — given the same source files and parameters, re-running
    the matcher must yield the same match_result block.
  * Machine-verifiable — the SHA-256 fields let a downstream tool prove
    the source files have not been altered since the workpaper was cut.
  * Human-readable — one JSON, indent=2, stable key order.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.0"
TOOL_NAME = "SAAF Three-way Match"
TOOL_VERSION = "0.1.0"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_meta(raw: bytes, filename: str) -> dict[str, Any]:
    return {
        "filename": filename,
        "size_bytes": len(raw),
        "sha256": sha256_hex(raw),
    }


def build_workpaper(
    *,
    sources: dict[str, dict[str, Any]],
    parsed: dict[str, dict[str, Any]],
    report: dict[str, Any],
    parameters: dict[str, float],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "audit_workpaper": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now,
            "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
            "match_parameters": parameters,
        },
        "source_data": {
            "purchase_order":  {**sources["po"],  "parsed": parsed["po"]},
            "goods_receipt":   {**sources["grn"], "parsed": parsed["grn"]},
            "purchase_invoice":{**sources["inv"], "parsed": parsed["inv"]},
        },
        "match_result": {
            "verdict": report["result"],
            "summary": report["summary"],
            "header_issues": report["header_issues"],
            "line_results": report["line_results"],
            "totals": {
                "po_total":  report["po_total"],
                "grn_total": report["grn_total"],
                "inv_total": report["inv_total"],
                "discrepancy": report["totals_discrepancy"],
            },
        },
        "attestation": {
            "reviewed_by": "",
            "reviewed_at": "",
            "notes": "",
        },
    }


def workpaper_filename(report: dict[str, Any]) -> str:
    """Return a stable, informative default filename for the download."""
    po = report.get("po", {}) or {}
    po_num = (po.get("po_number") or po.get("document_number") or "unknown").replace("/", "_")
    verdict = report.get("result", "UNKNOWN")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"audit_workpaper_{po_num}_{verdict}_{stamp}.json"
