> ⚠️ **Branch mismatch notice (2026-09-15):** this matrix summarizes [`AUDIT-CRITERIA.md`](./AUDIT-CRITERIA.md), which describes the CLI implementation on this repo's `main` branch. Those files (`three_way_match.py`, `README.md`) do not exist on `master`. `master` currently has a different legacy CLI script *and* a separate new `webapp/` implementation, neither covered by this matrix. See `AUDIT-CRITERIA.md`'s notice and §5 (Coverage gaps) for detail.

---

# Audit criteria matrix — P2P 3-Way Match Audit Agent (CLI tool, `main` branch)

> Quick-reference view of [`AUDIT-CRITERIA.md`](./AUDIT-CRITERIA.md) — that file remains the source of truth.

| # | Aspect checked | Framework / standard | What is checked | Verified? |
|---|---|---|---|---|
| **CO-1** | Completeness of the matched population | IIA Standard 2320 · COSO 2013 CC10 | Every PO, GR, and invoice in the input ends up in `match_results.json`; nothing is silently dropped just because it's only present in one of the three files | ☑ record-count verified · ☐ orphan case not exercised (no test data) |
| **CO-2** | Quantity and price discrepancies (PO ↔ GR ↔ invoice) | COSO 2013 CC10.3 · SOx ICFR · SAAF domain taxonomy §9 (P2P) | Quantity mismatches (GR or invoice vs. PO) and price differences beyond the €0.01 tolerance are flagged as findings and set status to FAIL | ☑ verified live (2 PASS / 3 FAIL on sample data) |
| **CO-3** | Traceability / no fabricated output | IIA Standard 2330 · ISAE 3000 | Every finding, name, and figure in the PDF report is traceable to `match_results.json` — no hardcoded findings or conclusions | ☑ true on `main` · ✕ **not** true of `master`'s `tools/scripts/generate_audit_report.py` (hardcoded findings/auditor names) |
| **CO-4** | Orphaned documents (PO without GR/invoice, or vice versa) | COSO Fraud Risk Management Guide · Segregation of Duties in P2P | A PO with no goods receipt, or an invoice with no PO, is surfaced as a finding — never reported as PASS or silently omitted | ☐ not yet tested — sample data contains no orphan case |
| **CO-5** | Confidentiality of vendor/pricing data | ISO 27001 Annex A (A.5.12, A.8.24) | No network calls at runtime; output stays within the local path supplied to the agent | ☑ verified by code inspection (CLI tool only; `webapp/` is a network service and needs its own assessment) |

## Notes

- This matrix covers **only the CLI tool as it exists on `main`** — not `master`'s legacy script, and not the new `webapp/` implementation merged into `master` on 2026-09-15.
- **CO-1 (orphan case) and CO-4 are not yet exercised by real data.**
- **AI-specific frameworks (EU AI Act, OWASP LLM Top 10) are deliberately excluded** — this is a deterministic Python script, not an LLM-based agent.
