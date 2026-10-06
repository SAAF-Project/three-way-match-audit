"""Gemini audit agent — reads a MatchReport, returns a structured AuditNarrative.

The agent is READ-ONLY: it contextualises and explains the findings produced by
the rule-based matcher. It cannot change verdicts, tolerances, or any audit output.

Requires GEMINI_API_KEY environment variable (free tier at aistudio.google.com).
"""
from __future__ import annotations

import json
import os
from typing import Any

_MODEL = "gemini-2.0-flash"

_SYSTEM_PROMPT = """You are a read-only audit reviewer specialising in Procure-to-Pay (P2P) controls and the IIA audit framework.

You receive the JSON output of an automated three-way match (purchase order, goods receipt, invoice).
Your role is to explain and contextualise the findings — you may NOT change, override, or contradict
the verdict assigned to any line. Every FAIL, WARNING, and MATCH verdict has already been determined
by the authoritative rule-based matcher. Your role is to assess materiality, detect patterns across
lines (e.g. simultaneous price AND quantity inflation on the same invoice is a fraud signal, not two
independent errors), and recommend specific remediation steps.

Respond with a single JSON object matching this exact schema — no markdown fences, no extra keys:
{
  "summary": "<1-2 sentence plain-language summary of the overall audit situation>",
  "risk_level": "<one of: HIGH | MEDIUM | LOW | CLEAR>",
  "findings": [
    {
      "line": "<SKU or line identifier>",
      "issue": "<specific issue on this line, including materiality context>",
      "risk": "<HIGH | MEDIUM | LOW>",
      "recommendation": "<specific, actionable step for the AP team>"
    }
  ],
  "patterns": ["<cross-line pattern if multiple findings share a root cause or suggest a coordinated anomaly>"],
  "overall_recommendation": "<what the AP team should do next — be specific about escalation, hold payment, or approve>"
}

Risk level guidance:
- HIGH: Any FAIL verdict, potential fraud pattern, or total discrepancy > 1% of document value
- MEDIUM: WARNING verdicts, short receipts, minor discrepancies between 0.1% and 1%
- LOW: Only informational warnings, discrepancies within tolerance or < 0.1%
- CLEAR: All lines MATCH, no issues found

Include a finding only for lines with FAIL or WARNING verdicts. Do not fabricate issues on MATCH lines."""


def audit_narrative(match_report: dict[str, Any]) -> dict[str, Any] | None:
    """Call Gemini with the match report and return a structured AuditNarrative dict.

    Returns None if GEMINI_API_KEY is not set or if the call fails — the caller
    falls back gracefully to the rule-based report alone.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        import google.generativeai as genai
    except ImportError:
        return None

    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        model_name=_MODEL,
        system_instruction=_SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
        ),
    )

    user_message = (
        "Here is the three-way match report to review:\n\n"
        + json.dumps(match_report, indent=2, ensure_ascii=False)
        + "\n\nReturn your audit assessment as a JSON object matching the schema in your instructions."
    )

    try:
        response = model.generate_content(user_message)
        return json.loads(response.text)
    except Exception:
        return None
