"""Gemini audit agent — drives three-way match via tool use.

The AI calls `three_way_match` as a registered tool (max 3 times), then
produces a structured AuditNarrative JSON. Guardrails:
  - Only one tool is registered; the model cannot call anything else.
  - Tolerance params are clamped to [0, 1] server-side before the tool runs.
  - Verdicts produced by the matcher are immutable — the AI cannot change them.
  - First turn forces a tool call (mode=ANY); subsequent turns use AUTO.
  - Loop is hard-capped at _MAX_TOOL_CALLS.

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

You have exactly one tool: three_way_match. You MUST call it at least once to get the authoritative match results.
You may call it up to 3 times total if you want to explore different tolerance settings to assess borderline findings.

RULES YOU CANNOT BREAK:
1. You MUST call three_way_match before producing your assessment.
2. You CANNOT change, override, or contradict any FAIL/WARNING/MATCH verdict the tool returns.
3. Your findings must only reference lines where the tool returned FAIL or WARNING.
4. Do not fabricate issues on lines the tool returned as MATCH.

After calling the tool, respond with ONLY a JSON object — no markdown fences, no extra keys:
{
  "summary": "<1-2 sentence plain-language summary of the overall audit situation>",
  "risk_level": "<HIGH | MEDIUM | LOW | CLEAR>",
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

Risk level guidance:
- HIGH: any FAIL verdict, fraud pattern, or total discrepancy > 1% of document value
- MEDIUM: WARNING verdicts, discrepancies 0.1%-1%
- LOW: discrepancies within tolerance or < 0.1%
- CLEAR: all lines MATCH, no issues found"""


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
    """Run the agentic audit: the AI calls the matcher as a tool.

    Returns {"report": dict, "narrative": dict, "tool_calls": list} or None on failure.
    The caller should fall back to a direct three_way_match() call when None is returned.
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
                    "Tolerances are floats in [0, 1]. You must call this before giving your assessment."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "price_tolerance": types.Schema(
                            type=types.Type.NUMBER,
                            description=f"Max unit-price delta in euros. Default {price_tolerance}. Range [0, 1].",
                        ),
                        "qty_tolerance": types.Schema(
                            type=types.Type.NUMBER,
                            description=f"Max quantity delta in units. Default {qty_tolerance}. Range [0, 1].",
                        ),
                        "total_tolerance": types.Schema(
                            type=types.Type.NUMBER,
                            description=f"Max document-total delta in euros. Default {total_tolerance}. Range [0, 1].",
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
        + f"\n\nSuggested tolerances — price: {price_tolerance}, "
        f"qty: {qty_tolerance}, total: {total_tolerance}. "
        "Call three_way_match now."
    )

    contents: list = [
        types.Content(role="user", parts=[types.Part(text=user_message)])
    ]

    tool_calls_log: list[dict[str, Any]] = []
    last_report: dict[str, Any] | None = None
    tool_call_count = 0

    try:
        while True:
            # Force a tool call on the first turn; let the model decide on subsequent turns
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
                # No tool calls — the model produced its final narrative text
                narrative_text = next(
                    (p.text for p in candidate_content.parts if getattr(p, "text", None)),
                    None,
                )
                if narrative_text is None or last_report is None:
                    return None
                return {
                    "report": last_report,
                    "narrative": _parse_json(narrative_text),
                    "tool_calls": tool_calls_log,
                }

            # Execute each function call (server-side clamping enforces tolerance guardrail)
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
                last_report = report.to_dict()
                tool_calls_log.append({
                    "call_number": tool_call_count,
                    "requested_args": raw_args,
                    "clamped_args": clamped,
                    "overall_verdict": last_report.get("result"),
                })
                fn_response_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response=last_report,
                        )
                    )
                )

            contents.append(types.Content(role="user", parts=fn_response_parts))

            # Hard cap: if max tool calls reached, force a final text-only generation
            if tool_call_count >= _MAX_TOOL_CALLS:
                final = client.models.generate_content(
                    model=_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        # No tools= key: model cannot make another tool call
                    ),
                )
                if last_report is None:
                    return None
                return {
                    "report": last_report,
                    "narrative": _parse_json(final.text),
                    "tool_calls": tool_calls_log,
                }

    except Exception:
        import traceback
        traceback.print_exc()
        return None
