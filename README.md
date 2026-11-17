# P2P 3-Way Match Audit

**Live demo:** https://three-way-match-audit.vercel.app/

## Purpose

This project reconciles Procure-to-Pay (P2P) transactions across three source documents — **purchase order**, **goods receipt**, and **invoice** — to detect quantity and price discrepancies before payment. The 3-way match is a standard internal control over financial reporting (ICFR): it prevents over-payment, duplicate payment, and payment for goods or services never received. See [`AUDIT-CRITERIA.md`](./AUDIT-CRITERIA.md) for the control objectives this repo is judged against, and what's actually verified today.

## Input and output

**Input (per match run):** three documents per transaction, supplied as CSV or JSON:

| Document | Key fields |
|---|---|
| Purchase order (PO) | PO number, vendor/supplier, item, quantity, unit price |
| Goods receipt (GR / GRN) | GR number, PO number, item, quantity received |
| Invoice | Invoice number, PO number, item, quantity billed, unit price billed |

Matching is done on the PO number; a transaction passes when PO, GR, and invoice quantities agree and the invoice price matches the PO price within a disclosed tolerance. Any discrepancy — including a document that's missing entirely — is reported as a finding, never silently dropped.

**Output:** a verdict per line and overall (`MATCH` / `WARNING` / `FAIL`) with the findings behind it, as a result page in the browser or as JSON from `POST /api/match`. An invalid file is rejected with a message naming the file. Nothing is stored on the server.

**Code — this branch currently carries two independent implementations, not one pipeline:**

| Implementation | Location | Status |
|---|---|---|
| Webapp (FastAPI, file upload, configurable tolerances, three-tier MATCH/WARNING/FAIL verdicts) | [`webapp/`](./webapp/) | Newest; see [`webapp/README.md`](./webapp/README.md) for how to run it. |
| Legacy CLI script (PDF report generator only) | [`tools/scripts/generate_audit_report.py`](./tools/scripts/generate_audit_report.py) | **Do not use for real audit output** — its findings, auditor name, and conclusion text are hardcoded and do not reflect the input data. See `AUDIT-CRITERIA.md` CO-3. |

A third, working CLI implementation (`three_way_match.py` + a data-driven `generate_audit_report.py`) previously lived on a separate `main` branch with an unrelated git history; that branch's content was merged into `master` via PR #5, but `main` itself was later deleted. `AUDIT-CRITERIA.md` in this repo documents that CLI version specifically — see the notice at the top of that file.

Sample/test data for the legacy script lives in `tools/scripts/data/p2p/`; sample data for the webapp lives in `webapp/sample_data/`.

## Prerequisites

- Python 3.12 for `webapp/` (the version CI tests on).
- Dependencies are pinned in [`webapp/requirements.txt`](./webapp/requirements.txt); install and run steps are in [`webapp/README.md`](./webapp/README.md).
- No API key is needed for the match itself. The optional advisory AI review uses the Google Gemini API (model `gemini-flash-lite-latest`) and runs only when the environment variable `GEMINI_API_KEY` is set; without it nothing is sent.
- **Data residency:** with a key set, the parsed PO, goods-receipt and invoice data and the match result are sent to Google. The page footer and the downloadable audit trail say whether that happened. On the unpaid Gemini tier, Google's terms allow it to use submitted content to improve its products, so use a paid key — or no key — for real supplier data.
- The legacy script `tools/scripts/generate_audit_report.py` is unsupported: it needs `reportlab` and `matplotlib`, which are not pinned here, and its findings are hardcoded (see `AUDIT-CRITERIA.md` §5).

## Install and run

```bash
cd webapp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open http://127.0.0.1:8000 and run a demo with the synthetic files in [`webapp/sample_data/`](./webapp/sample_data/): `po_sample.csv`, `grn_sample.csv` and `invoice_sample.csv` give a `MATCH`; `invoice_mismatch.csv` gives a `FAIL`. To run the tests: `pip install -r requirements-dev.txt && python -m pytest`.

## Limitations and human review

- The output is a reconciliation aid, not an audit conclusion. MATCH / WARNING / FAIL verdicts must be reviewed by a qualified auditor before anyone acts on them.
- Verdicts depend on the tolerances chosen on the start page or in the request (see `webapp/README.md`). Record the tolerances used with every result.
- The legacy script `tools/scripts/generate_audit_report.py` produces hardcoded findings, names and conclusions that do not come from the input data. Do not use it for audit output (see `AUDIT-CRITERIA.md` CO-3).
- `AUDIT-CRITERIA.md` lists the webapp's control objectives and acceptance criteria, each mapped to a test; CO-3.5 is still open.
- The webapp accepts at most 1 MB and 5000 lines per file, rejects negative amounts (credit notes), and has no login or rate limiting. The full list of input checks is in [`webapp/README.md`](./webapp/README.md#invoercontrole-en-beveiliging).

## Guardrails

The code follows the SAAF command allowlist (`regulatory/guardrails/allowed-commands.md` in the main SAAF-Project repo). The Python code in this repo runs no shell commands and does not `pip install` at runtime. The `curl` examples in `webapp/README.md` are calls a user makes to the webapp's API; the tool itself does not run them.

## License and contact

- License: MIT, see [`LICENSE`](./LICENSE).
- Owners: vvsodrs and wehren, see [`CODEOWNERS`](./CODEOWNERS). They review every pull request and do the quarterly review against the SAAF standards.
- Plan: there is no plan for this repo in `SAAF-Project/plans/` yet. Audit criteria, coverage gaps and open items are in [`AUDIT-CRITERIA.md`](./AUDIT-CRITERIA.md).
