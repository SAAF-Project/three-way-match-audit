# Audit criteria matrix — P2P 3-Way Match Audit Agent

> Summary matrix of the control objectives detailed in [`AUDIT-CRITERIA.md`](./AUDIT-CRITERIA.md). This file is a quick-reference view only — `AUDIT-CRITERIA.md` remains the source of truth (full acceptance criteria, good-output/never-do list, coverage gaps, observability).
>
> **Repository:** https://github.com/SAAF-Project/three-way-match-audit (`main` branch) · **Last reviewed:** 2026-09-15

| # | Aspect checked | Framework / standard | What is checked | Verified? |
|---|---|---|---|---|
| **CO-1** | Completeness of the matched population | IIA Standard 2320 · COSO 2013 CC10 | Every PO, GR, and invoice in the input ends up in `match_results.json`; nothing is silently dropped just because it's only present in one of the three files | ☑ record-count verified · ☐ orphan case not exercised (no test data) |
| **CO-2** | Quantity and price discrepancies (PO ↔ GR ↔ invoice) | COSO 2013 CC10.3 · SOx ICFR · SAAF domain taxonomy §9 (P2P) | Quantity mismatches (GR or invoice vs. PO) and price differences beyond the €0.01 tolerance are flagged as findings and set status to FAIL | ☑ verified live (2 PASS / 3 FAIL on sample data) |
| **CO-3** | Traceability / no fabricated output | IIA Standard 2330 · ISAE 3000 | Every finding, name, and figure in the PDF report is traceable to `match_results.json` — no hardcoded findings or conclusions | ☑ true on `main` · ✕ **not** true on `master` (known regression — hardcoded findings/auditor names) |
| **CO-4** | Orphaned documents (PO without GR/invoice, or vice versa) | COSO Fraud Risk Management Guide · Segregation of Duties in P2P | A PO with no goods receipt, or an invoice with no PO, is surfaced as a finding — never reported as PASS or silently omitted | ☐ not yet tested — sample data contains no orphan case |
| **CO-5** | Confidentiality of vendor/pricing data | ISO 27001 Annex A (A.5.12, A.8.24) | No network calls at runtime; output stays within the local path supplied to the agent | ☑ verified by code inspection (no `requests`/`urllib`/`socket`) |

## Notes

- **CO-1 (orphan case) and CO-4 are not yet exercised by real data** — the current `samples/p2p/` CSVs contain no orphan `po_number`, so those two checks are verified by code read only, not by a live run. Recommend adding an orphan case before the next A1 stress test.
- **AI-specific frameworks (EU AI Act, OWASP LLM Top 10) are deliberately excluded.** This is a deterministic Python script, not an LLM-based agent — citing AI regulation here would be citation padding, not a real control.
