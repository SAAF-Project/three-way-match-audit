"""Audit trail builder for re-performance and traceability (ISAE 3000 / CO-3).

Produces a JSON record containing SHA-256 hashes of the three input files,
the rule-based match report (authoritative), the AI narrative (advisory),
and the run metadata. This record is returned to the caller for download —
no server-side persistence is needed (works on ephemeral Vercel deployments).
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

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
    tool_calls: list[dict[str, Any]] | None = None,
    ai: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a structured audit trail dict suitable for JSON serialisation."""
    return {
        "schema_version": "1.1",
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
        # What happened to the AI part, stated even when it failed or was off.
        "ai": {
            "status": ai.get("status") if ai else "disabled",
            "reason": ai.get("reason") if ai else None,
            "data_sent_externally": bool(ai and ai.get("data_sent")),
            "provider": ai.get("provider") if ai else None,
            "model": ai.get("model") if ai else None,
        },
        # Only set when a validated narrative is included.
        "ai_model": ai.get("model") if ai and audit_narrative else None,
        "ai_tool_calls": tool_calls,
        "match_report": match_report,
        "audit_narrative": audit_narrative,
        "re_performance_note": _re_performance_note(ai, audit_narrative),
    }


def _re_performance_note(ai: dict[str, Any] | None, narrative: dict[str, Any] | None) -> str:
    base = ("To re-perform: supply the original files (verify by SHA-256 hash above) and "
            "run three_way_match() with run_parameters. match_report is authoritative and "
            "was computed in Python with those parameters.")
    if narrative and ai:
        return (base + f" The advisory narrative was produced by {ai.get('model')} via "
                f"{ai.get('provider')}; ai_tool_calls records the advisory Run 2. "
                "Model output is not deterministic and may differ on re-run.")
    status = ai.get("status") if ai else "disabled"
    return base + f" No AI narrative is included (AI status: {status})."


def to_json(log: dict[str, Any]) -> str:
    """Serialise strictly: NaN or Infinity would make the file invalid JSON."""
    return json.dumps(log, indent=2, ensure_ascii=False, allow_nan=False)
