"""Audit trail builder for re-performance and traceability (ISAE 3000 / CO-3).

Produces a JSON record containing SHA-256 hashes of the three input files,
the rule-based match report (authoritative), the AI narrative (advisory),
and the run metadata. This record is returned to the caller for download —
no server-side persistence is needed (works on ephemeral Vercel deployments).
"""
from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import Any

_MODEL = "claude-opus-5-5"
_APP_VERSION = "0.2.0"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(
    *,
    po_bytes: bytes,
    grn_bytes: bytes,
    invoice_bytes: bytes,
    po_filename: str,
    grn_filename: str,
    invoice_filename: str,
    price_tolerance: float,
    qty_tolerance: float,
    total_tolerance: float,
    match_report: dict[str, Any],
    audit_narrative: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a structured audit trail dict suitable for JSON serialisation."""
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "app_version": _APP_VERSION,
        "run_parameters": {
            "price_tolerance": price_tolerance,
            "qty_tolerance": qty_tolerance,
            "total_tolerance": total_tolerance,
        },
        "input_files": {
            "po":      {"filename": po_filename,      "sha256": _sha256(po_bytes)},
            "grn":     {"filename": grn_filename,     "sha256": _sha256(grn_bytes)},
            "invoice": {"filename": invoice_filename, "sha256": _sha256(invoice_bytes)},
        },
        "ai_model": _MODEL if audit_narrative else None,
        "match_report": match_report,
        "audit_narrative": audit_narrative,
        "re_performance_note": (
            "To re-perform: supply the original files (verify by SHA-256 hash above), "
            "run the three-way matcher with the parameters above, and call the AI agent "
            f"with model {_MODEL}. The narrative is advisory; match_report is authoritative."
        ),
    }
