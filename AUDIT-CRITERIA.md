> ⚠️ **Branch mismatch notice (2026-09-15):** this document describes the CLI implementation on this repo's `main` branch (`README.md`, `requirements.txt`, `three_way_match.py`, `generate_audit_report.py`, `samples/p2p/`). **Those files do not exist on `master`.** `master` currently carries a different, older CLI script (`tools/scripts/generate_audit_report.py`, with hardcoded findings — see CO-3 below) *and*, as of today, a separate `webapp/` implementation (FastAPI, configurable tolerances, three-tier MATCH/WARNING/FAIL verdicts) that this document does not cover at all. Treat this as a placeholder for the A2 deliverable pending reconciliation of the repo's branches — do not assume the files/behavior below are runnable from `master` as-is.

---

# `AUDIT-CRITERIA.md` — P2P 3-Way Match Audit Agent

> Copied and filled in from `docs/conventions/audit-criteria-template.md` in the main SAAF-Project repo.
> This is the output of the **A2 — Audit Criteria & Controls** track (Session 6). It lives next to `README.md`: the README says what the agent does and how to run it; this document says what it must be judged against as an auditee.

---

## Metadata

| Field | Value |
|---|---|
| **Agent** | P2P 3-Way Match Audit Agent |
| **Repository** | https://github.com/SAAF-Project/three-way-match-audit (describes the `main` branch — see notice above) |
| **Maintainer(s)** | wehren (wil@itriskcontrol.nl) |
| **Last reviewed** | 2026-09-15 |
| **Status** | Draft |

## 1. What the agent does

Reconciles Procure-to-Pay transactions across three source documents — purchase order, goods receipt, and invoice — supplied as CSV exports, and renders the result as a PDF audit report. `three_way_match.py` joins `purchase_orders.csv`, `goods_receipts.csv`, and `invoices.csv` on `po_number`, checks that quantity matches exactly and unit price matches within a fixed €0.01 tolerance, and writes `match_results.json` (a PASS/FAIL status plus a findings list per PO). `generate_audit_report.py` turns that JSON into `audit_report.pdf`: an executive summary (pass-rate donut chart, KPI counts) and a per-transaction detail table with findings. It is a **deterministic reconciliation script, not an LLM-based agent** — no model inference happens at runtime, so AI-specific frameworks are intentionally not mapped below (see Coverage gaps).

## 2. Control objectives & framework mapping

| Control objective | Framework + clause/area | Why relevant |
|---|---|---|
| **CO-1** — Completeness: every PO, GR, and invoice in the input is included in the matched population and reported, none silently dropped | IIA Standard 2320 (Analysis & Evaluation); COSO 2013 Control Activities (CC10 — completeness of transaction processing) | An audit conclusion is only as good as the population it covers; a document missing from `match_results.json` or the PDF understates risk without anyone noticing. |
| **CO-2** — Quantity and price discrepancies between PO, GR, and invoice are detected and disclosed within a stated tolerance | COSO 2013 Control Activities (CC10.3); SAAF domain taxonomy §9 Procure-to-Pay (`docs/reference/domains-and-frameworks.md`); SOx ICFR | This is the actual control the agent claims to test — 3-way match is a standard ICFR control preventing over-, duplicate, or fraudulent payment. |
| **CO-3** — Every reported finding and figure is traceable to, and reproducible from, the supplied input files; nothing in the output is fabricated or hardcoded | IIA Standard 2330 (Documenting Information); ISAE 3000 (sufficient appropriate evidence) | This repo's `master`-branch copy of `generate_audit_report.py` (`tools/scripts/generate_audit_report.py`) ships **hardcoded findings, a fixed auditor name, and a fixed conclusion regardless of input data**. This objective exists specifically to keep the `main`-branch implementation from regressing to that. |
| **CO-4** — Orphaned documents (a PO, GR, or invoice with no counterpart) are surfaced as findings, never silently passed or dropped | COSO Fraud Risk Management Guide; Internal Control — Segregation of Duties in P2P | An invoice with no PO, or a PO with no goods receipt, is a classic unauthorized-purchase / unrecorded-liability red flag; auditors expect these on the exceptions list, not omitted from it. |
| **CO-5** — Confidentiality and availability of the vendor and pricing data the agent processes | ISO 27001 Annex A (A.5.12 Classification of information, A.8.24 Cryptography) — applied narrowly, see Coverage gaps | Purchase prices and vendor identities are commercially sensitive. Today's `main`-branch tool is fully offline and local; that property must be preserved deliberately, not by accident, as the agent evolves — note that `master`'s separate `webapp/` implementation is a network service and would need this control re-assessed on its own terms (out of scope for this document — see notice above). |

*Framework menu: ISO 27001 · GDPR · DORA · NIS2 · EU AI Act · COSO · COBIT · SOx (ICFR) · IIA Standards · OWASP (LLM/AI). Full catalogue: `docs/reference/domains-and-frameworks.md`.*

## 3. Acceptance criteria (testable, pass/fail)

**CO-1**
- Given *N* distinct `po_number` values across the three input CSVs combined, `match_results.json.matches` contains exactly *N* records.
- Given a `po_number` present in only one of the three files, the agent still emits a match record for it and lists which document(s) are missing — it never silently drops it.
- The PDF's "Transactions reviewed" KPI always equals `summary.total`, which always equals `len(matches)`.

**CO-2**
- Given a GR or invoice quantity that differs from the PO quantity, the agent appends a "Quantity mismatch" / "Invoice quantity mismatch" finding and sets status `FAIL`.
- Given an invoice unit price that differs from the PO unit price by more than the disclosed tolerance (currently €0.01, `PRICE_TOLERANCE` in `three_way_match.py`), the agent appends a "Price mismatch" finding and sets status `FAIL`.
- Given PO, GR, and invoice values that agree exactly on quantity and within tolerance on price, the agent returns status `PASS` with an empty findings list.

**CO-3**
- Running `three_way_match.py` twice against the same three CSVs produces byte-identical `match_results.json` (no timestamps, randomness, or external calls in the matching path).
- No string literal in `generate_audit_report.py` names a specific finding, auditor, vendor, or amount — every user-facing value in the PDF is read from `data["summary"]` or `data["matches"]`.
- The PDF footer's generation timestamp is the only value in the report not sourced from `match_results.json`, and it is presented only as a generation timestamp, never as a data value.

**CO-4**
- Given a `po_number` in `purchase_orders.csv` absent from `goods_receipts.csv`, the record's findings include "No goods receipt found" and status is `FAIL` — never `PASS`.
- Given a `po_number` in `invoices.csv` with no matching purchase order, the agent still creates a record (vendor reported as `"Unknown"`, per current code) rather than omitting the invoice from the report.

**CO-5**
- The agent makes no network calls at runtime.
- Output files (`match_results.json`, `audit_report.pdf`) are written only to the path given on the command line / current working directory.

## 4. Good output / never do

| A correct output MUST contain | The agent must NEVER |
|---|---|
| ✓ Every row traceable to a `po_number` present in the source CSVs | ✕ Hardcode findings, auditor names, or a fixed narrative conclusion instead of deriving them from `match_results.json` — **this exact defect ships today in `tools/scripts/generate_audit_report.py` on this branch** |
| ✓ An explicit PASS/FAIL status and findings list per transaction, consistent with the tolerance rules in `three_way_match.py` | ✕ Report `PASS` for a transaction with a missing PO, GR, or invoice |
| ✓ A summary figure (pass rate / counts) that reconciles exactly with the sum of PASS/FAIL rows in the detail table | ✕ Silently drop a `po_number` because it's absent from one of the three source files |
| ✓ The existing reviewer disclaimer ("Findings should be reviewed and confirmed by a qualified auditor before action is taken") on every report | ✕ Hard-code credentials, API keys, or secrets (none present today — keep it that way; this offline script has no reason to ever need one) |
| ✓ Findings conform to `outputs/schemas/finding-schema.json` if/when this agent's output is consumed by another SAAF tool | ✕ Send PO, vendor, or price data to any external network service without a documented basis |

## 5. Coverage gaps

- **This document does not match this branch.** It describes `main`'s CLI tool, not what's actually on `master` — see the notice at the top of this file. Reconciling that mismatch (merging `main` into `master`, or writing separate criteria per implementation) is itself the largest open item here.
- **`master` now carries three unrelated implementations of "3-way match"**: the legacy `tools/scripts/generate_audit_report.py` (hardcoded findings, no matching engine), the `main`-branch CLI tool this document describes, and a newly-merged `webapp/` (FastAPI, configurable tolerances, three-tier verdicts) that has its own, not-yet-written audit criteria.
- **No automated tests** for the `main`-branch CLI tool. There is no `tests/` directory; the only verification is a manual run against a 5-row sample. The org's own portal review (2026-06-09) already flagged `hasTests: false`, and that is still true today.
- **Duplicate `po_number` rows are silently collapsed** in the CLI tool's matching logic (`{row["po_number"]: row for row in ...}` keeps only the last row per PO) — a partial delivery or split invoice would silently lose a row instead of raising a finding.
- **Tolerance rules are fixed and undocumented as a control parameter** in the CLI tool: €0.01 price tolerance, 0% quantity tolerance, hardcoded with no rationale recorded. (The new `webapp/` implementation does better here — it exposes tolerances as configurable form fields.)
- **No segregation-of-duties detection** anywhere in this repo yet — no implementation ingests who created or approved a PO or invoice.
- **AI-specific frameworks (EU AI Act, OWASP LLM Top 10) are deliberately not mapped above.** The `main`-branch tool is a deterministic script with no LLM call in its runtime path; citing AI-specific regulatory criteria here would be citation padding, not a real control.
- **The PDF-rendering path was verified by code read, not by execution**, in the environment used to write this document (no outbound network access to install `reportlab`/`matplotlib`). The matching engine (`three_way_match.py`, on `main`) *was* executed live.

## 6. Status / validation

| Acceptance criterion | Verified? | Evidence |
|---|---|---|
| CO-1 — record count equals distinct `po_number` count | ☑ | Ran `three_way_match.py` (on `main`) against its sample data on 2026-09-15: 5 `po_number`s in, 5 records out. |
| CO-1 — orphan `po_number` not dropped | ☐ | Not exercised — sample data contains no orphan case. Verified by code read only. |
| CO-2 — quantity/price mismatches detected | ☑ | Same run: 2 PASS, 3 correctly-flagged FAIL. |
| CO-3 — deterministic output | ☑ | Ran the script twice against the same input; byte-identical output both times. |
| CO-3 — no hardcoded content in the report generator | ☑ (`main` only) | Confirmed by code review on `main`. **Not** true of `master`'s `tools/scripts/generate_audit_report.py`. |
| CO-4 — orphan PO/invoice handling | ☐ | Not exercised — same missing test case as CO-1. |
| CO-5 — no network calls | ☑ | Verified by inspection — no `requests`/`urllib`/`socket` imports (CLI tool only; `webapp/` is a network service by design and is out of scope here). |
| CO-5 — writes stay local | ☑ | Verified by code read (CLI tool only). |

## 7. Observability

**Logged/traced today (CLI tool, on `main`):** two `print()` statements to stdout. No log file, no log levels, no timestamp beyond the PDF's own "Generated: …" footer line.

**Missing:**
- No record of who ran the tool, when, or against which specific CSV file versions.
- No error/exception logging — an unhandled exception prints a raw Python traceback to stderr.
- No run history — each execution overwrites the previous output files.
- No linkage between a PDF report and the exact input data that produced it.

Not assessed here: observability for `tools/scripts/generate_audit_report.py` or the new `webapp/` — both need their own review.
