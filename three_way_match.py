"""
P2P 3-Way Match Engine
Compares Purchase Orders, Goods Receipts, and Invoices to identify discrepancies.
Output: match_results.json
"""

import csv
import json
import sys
from pathlib import Path

SAMPLES_DIR = Path("samples/p2p")
PRICE_TOLERANCE = 0.01  # 1 cent

REQUIRED_COLUMNS = {
    "purchase_orders.csv": {"po_number", "vendor", "item_description", "quantity", "unit_price"},
    "goods_receipts.csv": {"po_number", "quantity_received", "receipt_date"},
    "invoices.csv": {"po_number", "quantity_billed", "unit_price_billed", "invoice_date"},
}


def load_csv(filename):
    path = SAMPLES_DIR / filename
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    required = REQUIRED_COLUMNS.get(filename, set())
    if rows:
        missing = required - set(rows[0].keys())
        if missing:
            raise ValueError(
                f"{filename} is missing required column(s): {', '.join(sorted(missing))}"
            )
    return rows


def match(po_file="purchase_orders.csv", gr_file="goods_receipts.csv", inv_file="invoices.csv"):
    pos = {row["po_number"]: row for row in load_csv(po_file)}
    grs = {row["po_number"]: row for row in load_csv(gr_file)}
    invs = {row["po_number"]: row for row in load_csv(inv_file)}

    results = []
    all_po_numbers = set(pos) | set(grs) | set(invs)

    for po_num in sorted(all_po_numbers):
        po = pos.get(po_num)
        gr = grs.get(po_num)
        inv = invs.get(po_num)

        findings = []

        if not po:
            findings.append("No purchase order found")
        if not gr:
            findings.append("No goods receipt found")
        if not inv:
            findings.append("No invoice found")

        if po and gr and inv:
            po_qty = float(po["quantity"])
            gr_qty = float(gr["quantity_received"])
            inv_qty = float(inv["quantity_billed"])
            po_price = float(po["unit_price"])
            inv_price = float(inv["unit_price_billed"])

            if gr_qty != po_qty:
                findings.append(
                    f"Quantity mismatch: PO={po_qty}, GR={gr_qty}"
                )
            if inv_qty != po_qty:
                findings.append(
                    f"Invoice quantity mismatch: PO={po_qty}, INV={inv_qty}"
                )
            if abs(inv_price - po_price) > PRICE_TOLERANCE:
                findings.append(
                    f"Price mismatch: PO={po_price:.2f}, INV={inv_price:.2f}"
                )

        record = {
            "po_number": po_num,
            "vendor": po["vendor"] if po else "Unknown",
            "item": po["item_description"] if po else (inv["item_description"] if inv else "Unknown"),
            "po_quantity": float(po["quantity"]) if po else None,
            "gr_quantity": float(gr["quantity_received"]) if gr else None,
            "inv_quantity": float(inv["quantity_billed"]) if inv else None,
            "po_unit_price": float(po["unit_price"]) if po else None,
            "inv_unit_price": float(inv["unit_price_billed"]) if inv else None,
            "gr_date": gr["receipt_date"] if gr else None,
            "inv_date": inv["invoice_date"] if inv else None,
            "status": "PASS" if not findings else "FAIL",
            "findings": findings,
        }
        results.append(record)

    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r["status"] == "PASS"),
        "failed": sum(1 for r in results if r["status"] == "FAIL"),
    }

    output = {"summary": summary, "matches": results}

    out_path = Path("match_results.json")
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Match complete: {summary['passed']}/{summary['total']} passed — results written to {out_path}")
    return output


if __name__ == "__main__":
    match()
