"""
P2P 3-Way Match Audit Report Generator
Reads match_results.json and produces a professional PDF audit report.

Usage:
    python generate_audit_report.py                     # default: match_results.json
    python generate_audit_report.py my_results.json     # custom input
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image, KeepTogether,
)


# ── Brand colours ──────────────────────────────────────────────────────────────
BLUE_DARK  = colors.HexColor("#1B3A6B")
BLUE_MID   = colors.HexColor("#2E6DB4")
BLUE_LIGHT = colors.HexColor("#D6E4F7")
GREEN      = colors.HexColor("#2E7D32")
RED        = colors.HexColor("#C62828")
GREY_LIGHT = colors.HexColor("#F5F5F5")
GREY_MID   = colors.HexColor("#BDBDBD")


def load_results(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def make_donut(passed: int, failed: int) -> BytesIO:
    fig, ax = plt.subplots(figsize=(3.5, 3.5))
    sizes  = [passed, failed] if (passed + failed) > 0 else [1, 0]
    clrs   = ["#2E7D32", "#C62828"]
    wedges, _ = ax.pie(
        sizes, colors=clrs, startangle=90,
        wedgeprops={"width": 0.55, "edgecolor": "white", "linewidth": 2},
    )
    total = passed + failed
    pct   = f"{passed/total*100:.0f}%" if total else "—"
    ax.text(0, 0, pct, ha="center", va="center", fontsize=22, fontweight="bold", color="#1B3A6B")
    ax.text(0, -0.22, "pass rate", ha="center", va="center", fontsize=9, color="#555555")
    patch_pass = mpatches.Patch(color="#2E7D32", label=f"Pass ({passed})")
    patch_fail = mpatches.Patch(color="#C62828", label=f"Fail ({failed})")
    ax.legend(handles=[patch_pass, patch_fail], loc="lower center",
              bbox_to_anchor=(0.5, -0.15), ncol=2, fontsize=8, frameon=False)
    ax.set_aspect("equal")
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return buf


def build_styles():
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "title", parent=base["Title"],
            textColor=BLUE_DARK, fontSize=20, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"],
            textColor=BLUE_MID, fontSize=11, spaceAfter=2,
        ),
        "section": ParagraphStyle(
            "section", parent=base["Heading2"],
            textColor=BLUE_DARK, fontSize=13, spaceBefore=14, spaceAfter=6,
            borderPad=2,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"],
            fontSize=9, leading=13,
        ),
        "finding": ParagraphStyle(
            "finding", parent=base["Normal"],
            textColor=RED, fontSize=8, leading=11,
        ),
        "pass_tag": ParagraphStyle(
            "pass_tag", parent=base["Normal"],
            textColor=GREEN, fontSize=9, fontName="Helvetica-Bold",
        ),
        "fail_tag": ParagraphStyle(
            "fail_tag", parent=base["Normal"],
            textColor=RED, fontSize=9, fontName="Helvetica-Bold",
        ),
    }
    return styles


def generate(input_path: Path, output_path: Path):
    data    = load_results(input_path)
    summary = data["summary"]
    matches = data["matches"]
    styles  = build_styles()

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2.5*cm, bottomMargin=2*cm,
        title="P2P 3-Way Match Audit Report",
        author="SAAF Audit Agent",
    )

    story = []
    now   = datetime.now().strftime("%d %B %Y  %H:%M")

    # ── Cover header ────────────────────────────────────────────────────────────
    story.append(Paragraph("P2P 3-Way Match Audit Report", styles["title"]))
    story.append(Paragraph("Purchase Order × Goods Receipt × Invoice", styles["subtitle"]))
    story.append(Paragraph(f"Generated: {now}", styles["body"]))
    story.append(HRFlowable(width="100%", thickness=2, color=BLUE_DARK, spaceAfter=12))

    # ── Executive summary ───────────────────────────────────────────────────────
    story.append(Paragraph("Executive Summary", styles["section"]))

    donut_buf = make_donut(summary["passed"], summary["failed"])
    donut_img = Image(donut_buf, width=7*cm, height=7*cm)

    kpi_data = [
        ["Transactions reviewed", str(summary["total"])],
        ["Matched (PASS)",        str(summary["passed"])],
        ["Discrepancies (FAIL)",  str(summary["failed"])],
    ]
    kpi_table = Table(kpi_data, colWidths=[7*cm, 3*cm])
    kpi_table.setStyle(TableStyle([
        ("FONTNAME",   (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 0), (-1, -1), 10),
        ("FONTNAME",   (1, 0), (1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR",  (1, 1), (1, 1), GREEN),
        ("TEXTCOLOR",  (1, 2), (1, 2), RED),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [GREY_LIGHT, colors.white]),
        ("TOPPADDING",  (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("GRID",       (0, 0), (-1, -1), 0.5, GREY_MID),
    ]))

    summary_layout = Table([[donut_img, kpi_table]], colWidths=[8*cm, 10*cm])
    summary_layout.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(summary_layout)
    story.append(Spacer(1, 0.5*cm))

    # ── Detail table ─────────────────────────────────────────────────────────────
    story.append(Paragraph("Transaction Detail", styles["section"]))

    header = ["PO #", "Vendor", "Item", "PO Qty", "GR Qty", "INV Qty",
              "PO Price", "INV Price", "Status", "Findings"]
    col_w = [1.8*cm, 3*cm, 3.5*cm, 1.3*cm, 1.3*cm, 1.3*cm, 1.8*cm, 1.8*cm, 1.3*cm, 0]
    # last col gets remaining space
    page_w = A4[0] - 4*cm
    col_w[-1] = page_w - sum(col_w[:-1])

    rows = [header]
    for m in matches:
        status_para = Paragraph(
            m["status"],
            styles["pass_tag"] if m["status"] == "PASS" else styles["fail_tag"],
        )
        findings_text = "\n".join(m["findings"]) if m["findings"] else "—"
        findings_para = Paragraph(findings_text, styles["finding"] if m["findings"] else styles["body"])

        row = [
            m["po_number"],
            m["vendor"],
            m["item"],
            str(int(m["po_quantity"]))  if m["po_quantity"]  is not None else "—",
            str(int(m["gr_quantity"]))  if m["gr_quantity"]  is not None else "—",
            str(int(m["inv_quantity"])) if m["inv_quantity"] is not None else "—",
            f"€{m['po_unit_price']:.2f}"  if m["po_unit_price"]  is not None else "—",
            f"€{m['inv_unit_price']:.2f}" if m["inv_unit_price"] is not None else "—",
            status_para,
            findings_para,
        ]
        rows.append(row)

    detail_table = Table(rows, colWidths=col_w, repeatRows=1)
    detail_style = TableStyle([
        # Header
        ("BACKGROUND",   (0, 0), (-1, 0), BLUE_DARK),
        ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0), 8),
        ("ALIGN",        (0, 0), (-1, 0), "CENTER"),
        # Body
        ("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",     (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY_LIGHT]),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("GRID",         (0, 0), (-1, -1), 0.4, GREY_MID),
    ])
    detail_table.setStyle(detail_style)
    story.append(detail_table)

    # ── Footer note ──────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.8*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY_MID))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        "This report was generated automatically by the SAAF P2P Audit Agent. "
        "Findings should be reviewed and confirmed by a qualified auditor before action is taken.",
        ParagraphStyle("footer", parent=getSampleStyleSheet()["Normal"],
                       fontSize=7, textColor=colors.grey),
    ))

    doc.build(story)
    print(f"Report written to: {output_path}")


if __name__ == "__main__":
    input_path  = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("match_results.json")
    output_path = Path("audit_report.pdf")

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        print("Run 'python three_way_match.py' first to generate match_results.json")
        sys.exit(1)

    generate(input_path, output_path)
