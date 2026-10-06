"""Gemini audit agent — drives two runs of three-way match via tool use.

The AI makes exactly two tool calls:
  Run 1 — user-specified tolerances (what the auditor configured)
  Run 2 — AI professional judgment (tolerances chosen based on purchase type,
           supplier context, and applicable accounting standards)

Guardrails:
  - Only one tool is registered; the model cannot call anything else.
  - Tolerance params are clamped to [0, 1] server-side before the tool runs.
  - Verdicts produced by the matcher are immutable — the AI cannot change them.
  - First turn forces a tool call (mode=ANY); cap enforced at _MAX_TOOL_CALLS.

Requires GEMINI_API_KEY environment variable.
"""
from __future__ import annotations

import json
import os
from typing import Any

from app.services.matcher import three_way_match as _matcher

_MODEL = "gemini-flash-lite-latest"
_MAX_TOOL_CALLS = 3

_SYSTEM_PROMPT = """You are a P2P audit agent specialising in Procure-to-Pay controls and the IIA audit framework.

You have exactly one tool: three_way_match. You MUST call it exactly twice:

CALL 1 — User tolerances: The user message tells you the exact values to use. Call with those values.
CALL 2 — Professional judgment: Based on the purchase type, supplier, line items, amounts, and applicable
accounting standards (IFRS/IAS 2, CIPS procurement norms, or relevant industry practice), choose tolerances
that a professional auditor would apply to this specific purchase. These may be stricter OR looser than the
user's values — what matters is that they reflect sound accounting judgment for this category of spend.

RULES YOU CANNOT BREAK:
1. You MUST make both calls before producing your final assessment.
2. You CANNOT change, override, or contradict any FAIL/WARNING/MATCH verdict either call returns.
3. Your findings must only reference lines where a call returned FAIL or WARNING.
4. Do not fabricate issues on lines that returned MATCH in both calls.

After both calls, respond with ONLY this JSON object — no markdown fences, no extra keys:
{
  "summary": "<1-2 sentence plain-language summary of the overall audit situation>",
  "risk_level": "<HIGH | MEDIUM | LOW | CLEAR>",
  "ai_tolerances": {
    "price_tolerance": <float>,
    "qty_tolerance": <float>,
    "total_tolerance": <float>,
    "rationale": "<why these tolerances are appropriate for this specific purchase — cite accounting standards or industry norms>"
  },
  "findings": [
    {
      "line": "<SKU or line identifier>",
      "issue": "<specific issue with materiality context>",
      "risk": "<HIGH | MEDIUM | LOW>",
      "recommendation": "<actionable step for the AP team>"
    }
  ],
  "patterns": ["<cross-line pattern or fraud signal, if any>"],
  "overall_recommendation": "<what the AP team should do next>"
}

Risk level: HIGH = any FAIL verdict or fraud pattern; MEDIUM = WARNING verdicts; LOW = minor issues; CLEAR = all MATCH."""


def _clamp(v: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(text.strip())


def run_audit_agent(
    po: dict[str, Any],
    grn: dict[str, Any],
    inv: dict[str, Any],
    price_tolerance: float,
    qty_tolerance: float,
    total_tolerance: float,
) -> dict[str, Any] | None:
    """Run two-pass agentic audit.

    Pass 1: AI calls matcher with user tolerances.
    Pass 2: AI calls matcher again with its own professional judgment tolerances.

    Returns:
        {
          "report":      dict,        # Run 1 — user tolerances (authoritative)
          "ai_report":   dict | None, # Run 2 — AI judgment tolerances
          "narrative":   dict,        # AI narrative including ai_tolerances rationale
          "tool_calls":  list,        # Full call log for re-performance
        }
    or None on failure (caller falls back to direct rule-based match).
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None

    # ── Tool definition ────────────────────────────────────────────────────── #
    tool = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="three_way_match",
                description=(
                    "Run the authoritative rule-based three-way match on the uploaded documents. "
                    "Returns FAIL/WARNING/MATCH per line plus overall verdict and discrepancy totals. "
                    "Tolerances are floats in [0, 1]. You must call this twice."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "price_tolerance": types.Schema(
                            type=types.Type.NUMBER,
                            description="Max unit-price delta in euros. Range [0, 1].",
                        ),
                        "qty_tolerance": types.Schema(
                            type=types.Type.NUMBER,
                            description="Max quantity delta in units. Range [0, 1].",
                        ),
                        "total_tolerance": types.Schema(
                            type=types.Type.NUMBER,
                            description="Max document-total delta in euros. Range [0, 1].",
                        ),
                    },
                    required=["price_tolerance", "qty_tolerance", "total_tolerance"],
                ),
            )
        ]
    )

    client = genai.Client(api_key=api_key)

    user_message = (
        "Audit the following three procurement documents.\n\n"
        "## Purchase Order\n" + json.dumps(po, indent=2, ensure_ascii=False)
        + "\n\n## Goods Receipt Note\n" + json.dumps(grn, indent=2, ensure_ascii=False)
        + "\n\n## Invoice\n" + json.dumps(inv, indent=2, ensure_ascii=False)
        + f"\n\nCALL 1: Call three_way_match with price_tolerance={price_tolerance}, "
        f"qty_tolerance={qty_tolerance}, total_tolerance={total_tolerance} (user-specified).\n"
        "CALL 2: Then call three_way_match again with your own professional judgment tolerances "
        "based on the purchase type and accounting standards."
    )

    contents: list = [
        types.Content(role="user", parts=[types.Part(text=user_message)])
    ]

    tool_calls_log: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []  # indexed by call order
    tool_call_count = 0

    try:
        while True:
            if tool_call_count == 0:
                tool_cfg = types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="ANY",
                        allowed_function_names=["three_way_match"],
                    )
                )
            else:
                tool_cfg = types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode="AUTO")
                )

            response = client.models.generate_content(
                model=_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_PROMPT,
                    tools=[tool],
                    tool_config=tool_cfg,
                ),
            )

            candidate_content = response.candidates[0].content
            if not candidate_content or not candidate_content.parts:
                return None

            contents.append(candidate_content)

            fc_parts = [p for p in candidate_content.parts if p.function_call is not None]

            if not fc_parts:
                # No more tool calls — final narrative response
                narrative_text = next(
                    (p.text for p in candidate_content.parts if getattr(p, "text", None)),
                    None,
                )
                if narrative_text is None or not reports:
                    return None
                narrative = _parse_json(narrative_text)
                return {
                    "report":     reports[0],
                    "ai_report":  reports[1] if len(reports) > 1 else None,
                    "narrative":  narrative,
                    "tool_calls": tool_calls_log,
                }

            fn_response_parts = []
            for fc_part in fc_parts:
                if tool_call_count >= _MAX_TOOL_CALLS:
                    break
                fc = fc_part.function_call
                tool_call_count += 1
                raw_args = dict(fc.args) if fc.args else {}
                clamped = {
                    "price_tolerance": _clamp(raw_args.get("price_tolerance", price_tolerance)),
                    "qty_tolerance":   _clamp(raw_args.get("qty_tolerance",   qty_tolerance)),
                    "total_tolerance": _clamp(raw_args.get("total_tolerance", total_tolerance)),
                }
                report = _matcher(po, grn, inv, **clamped)
                report_dict = report.to_dict()
                reports.append(report_dict)
                tool_calls_log.append({
                    "call_number":    tool_call_count,
                    "label":          "user_tolerances" if tool_call_count == 1 else "ai_judgment",
                    "requested_args": raw_args,
                    "clamped_args":   clamped,
                    "overall_verdict": report_dict.get("result"),
                })
                fn_response_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response=report_dict,
                        )
                    )
                )

            contents.append(types.Content(role="user", parts=fn_response_parts))

            if tool_call_count >= _MAX_TOOL_CALLS:
                final = client.models.generate_content(
                    model=_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                    ),
                )
                if not reports:
                    return None
                narrative = _parse_json(final.text)
                return {
                    "report":     reports[0],
                    "ai_report":  reports[1] if len(reports) > 1 else None,
                    "narrative":  narrative,
                    "tool_calls": tool_calls_log,
                }

    except Exception:
        import traceback
        traceback.print_exc()
        return None
