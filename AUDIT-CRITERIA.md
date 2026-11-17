# `AUDIT-CRITERIA.md` — P2P 3-Way Match Audit

What this repository must be judged against as an auditee: its control objectives, testable acceptance criteria, and known limits. It covers the FastAPI webapp in [`webapp/`](./webapp/), which is what runs at https://three-way-match-audit.vercel.app. The legacy script `tools/scripts/generate_audit_report.py` is out of scope and must not be used for audit output (see §5).

## Metadata

| Field | Value |
|---|---|
| **Agent** | P2P 3-Way Match Audit |
| **Repository** | https://github.com/SAAF-Project/three-way-match-audit (`master`, `webapp/`) |
| **Maintainer(s)** | wehren, vvsodrs — see `CODEOWNERS` |
| **Last reviewed** | 2026-11-17 |
| **Status** | Reviewed — every criterion below is mapped to an automated test or marked open in §6 |

## 1. What the agent does

The auditor uploads a purchase order, a goods receipt and an invoice (CSV or JSON) and sets four tolerances. The webapp parses and validates the three documents, matches them line by line in deterministic Python and returns `MATCH`, `WARNING` or `FAIL` per line and overall, with the findings behind each verdict. Optionally, when `GEMINI_API_KEY` is set, Google Gemini adds an advisory review on top; it cannot change the verdict. The output supports the auditor's test of the 3-way match control; it is not an audit conclusion.

## 2. Control objectives & framework mapping

| Control objective | Framework + clause/area | Why relevant |
|---|---|---|
| **CO-1** — Completeness: every line on the PO, goods receipt and invoice is in the result; nothing is silently dropped or truncated | IIA Global Internal Audit Standards, Domain IV (performing engagements: analysis and evaluation); COSO 2013, Control Activities | A missing line understates risk without anyone noticing. |
| **CO-2** — Quantity, price and amount discrepancies are detected within the stated tolerances, and input that would hide one is rejected or fails | COSO 2013, Control Activities; SOx (ICFR) — Procure-to-Pay | The 3-way match is the ICFR control against over-, duplicate and fraudulent payment; an evasion that turns a mismatch into `MATCH` defeats it. |
| **CO-3** — The verdict is reproducible from the inputs and parameters, and the advisory AI cannot alter or contradict it | IIA Global Internal Audit Standards, Domain IV (documenting engagements); ISAE 3000 (sufficient appropriate evidence); EU AI Act, transparency and human oversight | An auditor must be able to re-perform the result; an AI narrative must not become the evidence. |
| **CO-4** — Uploaded documents are treated as untrusted input: they cannot inject formulas, scripts or model instructions | OWASP Top 10 for LLM Applications (prompt injection); OWASP CSV injection; ISO 27001 Annex A, secure development | Supplier documents are attacker-controlled. |
| **CO-5** — Supplier and pricing data stay confidential: they leave the service only for the opt-in AI review, and the user is told when they do | ISO 27001 Annex A, information transfer; GDPR, transparency | Purchase prices and supplier identities are commercially sensitive. |

## 3. Acceptance criteria (testable, pass/fail)

**CO-1**
- [code] CO-1.1 Given an invoice line that is not on the PO, the result contains that line with `FAIL` and the finding "missing on the purchase order".
- [code] CO-1.2 Given a PO line that is not on the invoice, the result contains that line and reports it missing on the invoice.
- [code] CO-1.3 Given a CSV with a second block of lines after a blank row, the file is rejected instead of the second block being dropped.
- [code] CO-1.4 Given a document with more than 5,000 lines, it is rejected instead of being truncated.

**CO-2**
- [code] CO-2.1 Given the sample invoice with a higher unit price and a higher quantity than the PO, the overall result is `FAIL`.
- [code] CO-2.2 Given a blank, `NaN`, `inf`, `1e309` or negative quantity or unit price, the document is rejected; passed to the matcher directly, the line is `FAIL`.
- [code] CO-2.3 Given one SKU split over two invoice rows with different unit prices, the document is rejected; passed to the matcher directly, the line is `FAIL`.
- [code] CO-2.4 Given a row where quantity × unit price differs from the line total, the document is rejected.
- [code] CO-2.5 Given two alias columns for the same field with different values (`sample_data/invoice_evasion.csv`), the document is rejected.
- [code] CO-2.6 Given an empty PO reference, supplier or document number on the invoice, the document is rejected; passed to the matcher directly, the result is `FAIL`.
- [code] CO-2.7 Given a flat CSV whose rows name two different POs or suppliers, the document is rejected.
- [code] CO-2.8 Given a tolerance that is negative, above 100, `NaN`, `inf` or not a number, the request is rejected.
- [code] CO-2.9 Given an invoiced line that is not on the goods receipt, the result is `FAIL`.

**CO-3**
- [code] CO-3.1 Given any AI answer, Run 1 (the verdict) is computed in Python with the user's tolerances and equals the result of the rule-based `/api/match`.
- [code] CO-3.2 Given an AI narrative whose risk level contradicts a `FAIL` verdict, or whose findings name a line that matched, the narrative is rejected and not shown.
- [code] CO-3.3 Given AI-proposed tolerances outside [0, 1], they are clamped, and a second tool call is refused.
- [code] CO-3.4 Given a run, the audit trail records the SHA-256 hash of each input file, the tolerances, the verdict and the AI status.
- [llm] CO-3.5 Given an accepted AI narrative, every recommendation follows from a finding in the rule-based result.

**CO-4**
- [code] CO-4.1 Given a text cell starting with `=`, `+`, `-` or `@`, the document is rejected.
- [code] CO-4.2 Given an Excel, zip or PDF file renamed to `.csv`, or a disallowed MIME type, the upload is rejected.
- [code] CO-4.3 Given a request body above 3 MB, also when chunked, the server answers 413 before parsing.
- [code] CO-4.4 Given HTML or script in a document field or file name, the result page shows it escaped.
- [code] CO-4.5 Given document text that tries to close or open the prompt delimiters, it is escaped before it reaches the model.

**CO-5**
- [code] CO-5.1 Given no `GEMINI_API_KEY`, no data is sent and the audit trail says so.
- [code] CO-5.2 Given an AI run, the result page and the audit trail name the provider and model the data went to; without a key, the pages say nothing is sent.
- [code] CO-5.3 Given any match result, the response carries `Cache-Control: no-store` and the security headers (CSP, `X-Frame-Options`, `nosniff`).

## 4. Good output / never do

| # | A correct output MUST contain | # | The agent must NEVER |
|---|---|---|---|
| M-1 | ✓ [code] A verdict per line and overall, with the finding behind every `WARNING` and `FAIL` | N-1 | ✕ [code] Return `MATCH` when a value needed for a check is missing, non-finite or contradictory |
| M-2 | ✓ [code] The file name in every rejection message | N-2 | ✕ [llm] Present the result as an audit conclusion with no human review |
| M-3 | ✓ [code] The tolerances used, in the audit trail | N-3 | ✕ [code] Store uploaded files on the server |
| M-4 | ✓ [code] Whether data was sent to an AI provider, and which | N-4 | ✕ [code] Hard-code credentials or secrets |
| M-5 | ✓ [code] Uploaded text treated as data: escaped in HTML and in the prompt | N-5 | ✕ [llm] Follow instructions found inside the input documents |
| M-6 | ✓ [code] The model name in the audit trail for every accepted AI narrative | N-6 | ✕ [code] Let the model change the verdict |

## 5. Coverage gaps

- No authentication and no rate limiting on the public site; each AI run with a key costs quota. A platform or proxy control is needed when the site should not be public.
- Credit notes (negative amounts) and multi-PO invoices are not supported; they are rejected, not matched.
- CO-3.5 has no automated check yet: whether a recommendation is supported is judged by reading the run.
- On the unpaid Gemini tier, Google may use submitted content; with real supplier data use a paid key or no key.
- `tools/scripts/generate_audit_report.py` produces hardcoded findings and is not covered by these criteria.

## 6. Status / validation

Evidence is the test of that name in `webapp/tests/`, run by the `Tests` workflow on every pull request.

| Criterion | Verified? | Evidence |
|---|---|---|
| CO-1.1 | ☑ | `test_invoice_line_not_on_po_fails` |
| CO-1.2 | ☑ | `test_po_line_not_invoiced_is_reported` |
| CO-1.3 | ☑ | `test_rows_after_a_blank_line_are_not_dropped` |
| CO-1.4 | ☑ | `test_too_many_lines_are_rejected` |
| CO-2.1 | ☑ | `test_mismatch_sample_fails` |
| CO-2.2 | ☑ | `test_non_finite_numbers_are_rejected`, `test_negative_amounts_are_rejected`, `test_matcher_fails_on_missing_values` |
| CO-2.3 | ☑ | `test_split_line_overpricing_is_rejected`, `test_matcher_fails_on_split_line_overpricing` |
| CO-2.4 | ☑ | `test_line_arithmetic_is_rejected` |
| CO-2.5 | ☑ | `test_evasion_sample_with_decoy_columns_is_rejected` |
| CO-2.6 | ☑ | `test_empty_header_fields_are_rejected`, `test_matcher_fails_on_empty_header_fields` |
| CO-2.7 | ☑ | `test_flat_csv_with_rows_for_two_pos_is_rejected`, `test_flat_csv_with_two_suppliers_is_rejected` |
| CO-2.8 | ☑ | `test_tolerances_are_bounded`, `test_bad_tolerances_are_rejected` |
| CO-2.9 | ☑ | `test_invoiced_but_not_received_fails` |
| CO-3.1 | ☑ | `test_model_cannot_set_run1_tolerances`, `test_run1_matches_plain_rule_based_match` |
| CO-3.2 | ☑ | `test_risk_level_contradicting_fail_is_rejected`, `test_finding_on_matching_line_is_rejected` |
| CO-3.3 | ☑ | `test_tool_args_are_clamped`, `test_second_tool_call_is_refused` |
| CO-3.4 | ☑ | `test_audit_log_records_transmission`, `test_without_key_nothing_is_sent` |
| CO-3.5 | ☐ | Open: no automated check (see §5) |
| CO-4.1 | ☑ | `test_formula_cells_are_rejected`, `test_formula_in_header_is_rejected` |
| CO-4.2 | ☑ | `test_binary_files_renamed_to_csv_are_rejected`, `test_disallowed_mime_types_are_rejected` |
| CO-4.3 | ☑ | `test_oversized_request_is_rejected_before_parsing`, `test_chunked_oversized_request_is_rejected` |
| CO-4.4 | ☑ | `test_xss_in_document_fields_is_escaped` |
| CO-4.5 | ☑ | `test_documents_are_wrapped_in_escaped_delimiters`, `test_escaping_blocks_delimiter_injection` |
| CO-5.1 | ☑ | `test_without_key_nothing_is_sent` |
| CO-5.2 | ☑ | `test_ui_does_not_claim_files_stay_local`, `test_ui_without_key_says_nothing_is_sent` |
| CO-5.3 | ☑ | `test_security_headers_on_pages`, `test_api_match_returns_match` |
| M-1 | ☑ | `test_samples_still_match`, `test_mismatch_sample_fails` |
| M-2 | ☑ | `test_api_returns_400_on_invalid_invoice` |
| M-3, M-4, M-6 | ☑ | `test_valid_narrative_is_accepted`, `test_audit_log_records_transmission` |
| M-5 | ☑ | `test_xss_in_document_fields_is_escaped`, `test_escaping_blocks_delimiter_injection` |
| N-1 | ☑ | CO-2.2 to CO-2.6 tests above |
| N-2 | ☐ | Stated in the README and on the result page; not tested |
| N-3 | ☑ | By code read: no write to disk in `webapp/app/` |
| N-4 | ☑ | By code read: the only key is read from `GEMINI_API_KEY` |
| N-5 | ☐ | Partly: input is delimited and escaped (CO-4.5); model compliance is not tested |
| N-6 | ☑ | `test_model_cannot_set_run1_tolerances` |

## 7. Observability

Each AI run returns an audit trail (`audit_trail.json`, downloadable from the result page and returned by `/api/match/explain`): input file names and SHA-256 hashes, tolerances, the rule-based report, the AI status and reason, provider, model, both tool calls and the validated narrative. A rejected or failed AI answer is logged as a warning or error. The server keeps no copy.
