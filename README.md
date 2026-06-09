# P2P 3-Way Match Audit Agent

Generates a professional PDF audit report for a Purchase-to-Pay 3-way match audit
(purchase order × goods receipt × invoice).

## How to run

```bash
pip install -r requirements.txt
python generate_audit_report.py                     # uses match_results.json
python generate_audit_report.py my_results.json     # custom input
```

To first generate `match_results.json` from CSV data:

```bash
python three_way_match.py                           # reads CSV files from samples/p2p/
```

## Input / output

- **Input:** `match_results.json` (output of `three_way_match.py`) + CSV data files in `samples/p2p/`
- **Output:** `audit_report.pdf`

## CSV format

The `samples/p2p/` directory contains three files:

| File | Description |
|------|-------------|
| `purchase_orders.csv` | PO number, vendor, item, quantity, unit price |
| `goods_receipts.csv` | GR number, PO number, item, quantity received |
| `invoices.csv` | Invoice number, PO number, item, quantity billed, unit price billed |

## Match logic

A transaction **passes** when PO quantity, GR quantity, and invoice quantity all agree and the invoice price matches the PO price within tolerance. Any discrepancy is flagged as a finding in the PDF report.

## Related plan

`plans/hackathon-4/...`

Part of SAAF Project
