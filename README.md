# P2P 3-Way Match Audit

**Live demo:** https://three-way-match-audit-iota.vercel.app/

## Purpose

This project reconciles Procure-to-Pay (P2P) transactions across three source documents — **purchase order**, **goods receipt**, and **invoice** — to detect quantity and price discrepancies before payment. The 3-way match is a standard internal control over financial reporting (ICFR): it prevents over-payment, duplicate payment, and payment for goods or services never received. See [`AUDIT-CRITERIA.md`](./AUDIT-CRITERIA.md) for the control objectives this repo is judged against, and what's actually verified today.

## Sources used

**Input data (per match run):** three documents per transaction, supplied as CSV or JSON:

| Document | Key fields |
|---|---|
| Purchase order (PO) | PO number, vendor/supplier, item, quantity, unit price |
| Goods receipt (GR / GRN) | GR number, PO number, item, quantity received |
| Invoice | Invoice number, PO number, item, quantity billed, unit price billed |

Matching is done on the PO number; a transaction passes when PO, GR, and invoice quantities agree and the invoice price matches the PO price within a disclosed tolerance. Any discrepancy — including a document that's missing entirely — is reported as a finding, never silently dropped.

**Code — this branch currently carries two independent implementations, not one pipeline:**

| Implementation | Location | Status |
|---|---|---|
| Webapp (FastAPI, file upload, configurable tolerances, three-tier MATCH/WARNING/FAIL verdicts) | [`webapp/`](./webapp/) | Newest; see [`webapp/README.md`](./webapp/README.md) for how to run it. |
| Legacy CLI script (PDF report generator only) | [`tools/scripts/generate_audit_report.py`](./tools/scripts/generate_audit_report.py) | **Do not use for real audit output** — its findings, auditor name, and conclusion text are hardcoded and do not reflect the input data. See `AUDIT-CRITERIA.md` CO-3. |

A third, working CLI implementation (`three_way_match.py` + a data-driven `generate_audit_report.py`) previously lived on a separate `main` branch with an unrelated git history; that branch's content was merged into `master` via PR #5, but `main` itself was later deleted. `AUDIT-CRITERIA.md` in this repo documents that CLI version specifically — see the notice at the top of that file.

Sample/test data for the legacy script lives in `tools/scripts/data/p2p/`; sample data for the webapp lives in `webapp/sample_data/`.

## Prerequisites

- Python: TODO(owner): state the supported Python version(s) for `webapp/`.
- Dependencies are pinned in [`webapp/requirements.txt`](./webapp/requirements.txt); install and run steps are in [`webapp/README.md`](./webapp/README.md).
- No API keys or accounts are needed: the webapp on `master` makes no model calls. Open PR #13 adds a Gemini-based agent to the webapp; if that is merged, its key must come from an environment variable, and a model and data-residency note must be added here.
- TODO(owner): list the Python packages needed by the legacy script `tools/scripts/generate_audit_report.py` (its docstring names `reportlab` and `matplotlib`), or mark that script as unsupported.

## Limitations and human review

- The output is a reconciliation aid, not an audit conclusion. MATCH / WARNING / FAIL verdicts must be reviewed by a qualified auditor before anyone acts on them.
- Verdicts depend on the tolerances chosen on the start page or in the request (see `webapp/README.md`). Record the tolerances used with every result.
- The legacy script `tools/scripts/generate_audit_report.py` produces hardcoded findings, names and conclusions that do not come from the input data. Do not use it for audit output (see `AUDIT-CRITERIA.md` CO-3).
- `AUDIT-CRITERIA.md` describes the CLI implementation from the deleted `main` branch, not the webapp. The webapp has no audit criteria of its own yet.
- TODO(owner): add any further known limits of the webapp (for example, file size limits and the items listed in `sec_issues.txt`).

## Guardrails

The code follows the SAAF command allowlist (`regulatory/guardrails/allowed-commands.md` in the main SAAF-Project repo). The Python code in this repo runs no shell commands and does not `pip install` at runtime. The `curl` examples in `webapp/README.md` are calls a user makes to the webapp's API; the tool itself does not run them.

## License and contact

- License: TODO(owner): licence to be decided by Stichting SAAF.
- Maintainer: wehren (see the metadata in [`AUDIT-CRITERIA.md`](./AUDIT-CRITERIA.md)). TODO(owner): confirm the maintainer for the webapp.
- Plan: TODO(owner): link the plan in `SAAF-Project/plans/` if one exists for this repo.
