"""
Audit Report Generator
======================
Generates a professional PDF audit report for the P2P 3-way match audit,
embedding the match_results.json output from three_way_match.py.

Usage:
    python generate_audit_report.py                         # uses match_results.json in same folder
    python generate_audit_report.py my_results.json        # custom input file
    python generate_audit_report.py results.json out.pdf   # custom input + output

Requires:
    pip install reportlab matplotlib
"""

from __future__ import annotations
import json
import sys
import os
import io
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image, KeepTogether, PageBreak,
)
from reportlab.platypus.flowables import Flowable


# ---------------------------------------------------------------------------
# Colour palette (matches the visual report)
# ---------------------------------------------------------------------------
RED_DARK   = colors.HexColor("#A32D2D")
RED_LIGHT  = colors.HexColor("#FCEBEB")
AMB_DARK   = colors.HexColor("#854F0B")
AMB_LIGHT  = colors.HexColor("#FAEEDA")
GRN_DARK   = colors.HexColor("#3B6D11")
GRN_LIGHT  = colors.HexColor("#EAF3DE")
BLU_DARK   = colors.HexColor("#185FA5")
BLU_LIGHT  = colors.HexColor("#E6F1FB")
GRAY_BG    = colors.HexColor("#F1EFE8")
GRAY_LINE  = colors.HexColor("#D3D1C7")
TEXT_PRI   = colors.HexColor("#1A1A18")
TEXT_SEC   = colors.HexColor("#5F5E5A")
TEXT_HINT  = colors.HexColor("#888780")
WHITE      = colors.white

CHART_RED  = "#E24B4A"
CHART_AMB  = "#EF9F27"
CHART_GRN  = "#639922"
CHART_BLU  = "#378ADD"
CHART_BLU2 = "#B5D4F4"


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def make_styles():
    base = getSampleStyleSheet()
    def S(name, **kw):
        return ParagraphStyle(name, **kw)

    return {
        "title":     S("title",     fontSize=20, textColor=TEXT_PRI, fontName="Helvetica-Bold", spaceAfter=4),
        "subtitle":  S("subtitle",  fontSize=12, textColor=TEXT_SEC,  fontName="Helvetica",      spaceAfter=2),
        "section":   S("section",   fontSize=8,  textColor=TEXT_HINT, fontName="Helvetica",      spaceBefore=16, spaceAfter=6, letterSpacing=1.2),
        "body":      S("body",      fontSize=10, textColor=TEXT_PRI,  fontName="Helvetica",      leading=16, spaceAfter=4),
        "body_sm":   S("body_sm",   fontSize=9,  textColor=TEXT_SEC,  fontName="Helvetica",      leading=14),
        "mono":      S("mono",      fontSize=8,  textColor=TEXT_HINT, fontName="Courier"),
        "bold":      S("bold",      fontSize=10, textColor=TEXT_PRI,  fontName="Helvetica-Bold"),
        "h2":        S("h2",        fontSize=14, textColor=TEXT_PRI,  fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=4),
        "label":     S("label",     fontSize=8,  textColor=TEXT_HINT, fontName="Helvetica",      spaceAfter=1),
        "value":     S("value",     fontSize=10, textColor=TEXT_PRI,  fontName="Helvetica-Bold"),
        "conc":      S("conc",      fontSize=10, textColor=TEXT_SEC,  fontName="Helvetica",      leading=17),
        "issue_fail":S("issue_fail",fontSize=8,  textColor=RED_DARK,  fontName="Helvetica",      leading=12),
        "issue_warn":S("issue_warn",fontSize=8,  textColor=AMB_DARK,  fontName="Helvetica",      leading=12),
        "issue_ok":  S("issue_ok",  fontSize=8,  textColor=GRN_DARK,  fontName="Helvetica",      leading=12),
    }


# ---------------------------------------------------------------------------
# Helper: badge cell
# ---------------------------------------------------------------------------
def badge_para(result: str, styles: dict) -> Paragraph:
    cfg = {
        "MATCH":   ("#EAF3DE", "#3B6D11", "Match"),
        "WARNING": ("#FAEEDA", "#854F0B", "Warning"),
        "FAIL":    ("#FCEBEB", "#A32D2D", "Fail"),
    }.get(result, ("#F1EFE8", "#5F5E5A", result))
    bg, fg, label = cfg
    return Paragraph(
        f'<font color="{fg}"><b>{label}</b></font>',
        ParagraphStyle("badge", fontSize=8, fontName="Helvetica-Bold",
                       textColor=colors.HexColor(fg), backColor=colors.HexColor(bg),
                       borderPadding=(3, 6, 3, 6), leading=12),
    )


def fmt_eur(n: float) -> str:
    return f"€{n:,.2f}"


# ---------------------------------------------------------------------------
# Charts (matplotlib → PNG bytes → ReportLab Image)
# ---------------------------------------------------------------------------
def chart_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="white", transparent=False)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def chart_image(data: bytes, width_cm: float, height_cm: float) -> Image:
    buf = io.BytesIO(data)
    return Image(buf, width=width_cm * cm, height=height_cm * cm)


def make_donut_chart(match_n, warn_n, fail_n) -> bytes:
    fig, ax = plt.subplots(figsize=(3.5, 3.5))
    sizes   = [match_n, warn_n, fail_n]
    clrs    = [CHART_GRN, CHART_AMB, CHART_RED]
    labels  = [f"Match ({match_n})", f"Warning ({warn_n})", f"Fail ({fail_n})"]
    wedges, _ = ax.pie(sizes, colors=clrs, startangle=90,
                       wedgeprops=dict(width=0.55, edgecolor="white", linewidth=2))
    ax.legend(wedges, labels, loc="lower center", bbox_to_anchor=(0.5, -0.12),
              ncol=3, fontsize=7, frameon=False)
    ax.set_title("Resultaten verdeling", fontsize=9, pad=10, color="#5F5E5A")
    fig.patch.set_facecolor("white")
    return chart_bytes(fig)


def make_bar_chart(data: list[dict]) -> bytes:
    ids     = [d["scenario_id"] for d in data]
    po_vals = [d["po_total"] for d in data]
    inv_vals= [d["inv_total"] for d in data]
    bar_clrs= [CHART_RED if d["result"]=="FAIL" else
               CHART_AMB if d["result"]=="WARNING" else CHART_GRN
               for d in data]

    x   = range(len(ids))
    fig, ax = plt.subplots(figsize=(12, 3.5))
    bw  = 0.35
    ax.bar([i - bw/2 for i in x], po_vals,  width=bw, color=CHART_BLU2, label="PO",     zorder=3)
    ax.bar([i + bw/2 for i in x], inv_vals, width=bw, color=bar_clrs,   label="Factuur", zorder=3)
    ax.set_xticks(list(x))
    ax.set_xticklabels(ids, fontsize=7, rotation=0)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"€{v/1000:.0f}k"))
    ax.tick_params(labelsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#D3D1C7")
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color="#F1EFE8", linewidth=0.8)
    p_patch = mpatches.Patch(color=CHART_BLU2, label="PO bedrag")
    f_patch = mpatches.Patch(color=CHART_GRN,  label="Factuur — Match")
    w_patch = mpatches.Patch(color=CHART_AMB,  label="Factuur — Warning")
    r_patch = mpatches.Patch(color=CHART_RED,  label="Factuur — Fail")
    ax.legend(handles=[p_patch, f_patch, w_patch, r_patch],
              fontsize=7, frameon=False, loc="upper right")
    ax.set_title("PO vs Factuur bedrag per scenario", fontsize=9, color="#5F5E5A", pad=8)
    fig.patch.set_facecolor("white")
    fig.tight_layout()
    return chart_bytes(fig)


def make_stacked_bar() -> bytes:
    cats   = ["Financieel", "Leverancier", "Proces", "Documentatie"]
    high   = [1, 1, 0, 0]
    medium = [1, 1, 1, 0]
    low    = [0, 0, 0, 2]
    x      = range(len(cats))
    fig, ax = plt.subplots(figsize=(5.5, 3))
    ax.bar(x, high,   color=CHART_RED, label="High")
    ax.bar(x, medium, bottom=high, color=CHART_AMB, label="Medium")
    ax.bar(x, low,    bottom=[h+m for h,m in zip(high,medium)], color=CHART_GRN, label="Low")
    ax.set_xticks(list(x))
    ax.set_xticklabels(cats, fontsize=8)
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.tick_params(labelsize=8)
    ax.spines[["top","right"]].set_visible(False)
    ax.spines[["left","bottom"]].set_color("#D3D1C7")
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color="#F1EFE8")
    ax.legend(fontsize=7, frameon=False)
    ax.set_title("Bevindingen per categorie", fontsize=9, color="#5F5E5A", pad=8)
    fig.patch.set_facecolor("white")
    fig.tight_layout()
    return chart_bytes(fig)


def make_timeline_chart() -> bytes:
    quarters = ["Q2 2026", "Q3 2026", "Q4 2026"]
    counts   = [3, 4, 2]
    clrs     = ["#85B7EB", "#378ADD", "#185FA5"]
    fig, ax  = plt.subplots(figsize=(5.5, 3))
    bars = ax.bar(quarters, counts, color=clrs, width=0.5)
    for bar, cnt in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                str(cnt), ha="center", va="bottom", fontsize=9, color="#5F5E5A")
    ax.set_ylim(0, max(counts) + 1)
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.tick_params(labelsize=9)
    ax.spines[["top","right"]].set_visible(False)
    ax.spines[["left","bottom"]].set_color("#D3D1C7")
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color="#F1EFE8")
    ax.set_title("Hersteldeadlines per kwartaal", fontsize=9, color="#5F5E5A", pad=8)
    fig.patch.set_facecolor("white")
    fig.tight_layout()
    return chart_bytes(fig)


# ---------------------------------------------------------------------------
# Page template (header + footer)
# ---------------------------------------------------------------------------
def make_page_template(canvas, doc):
    canvas.saveState()
    W, H = A4

    # Top bar
    canvas.setFillColor(colors.HexColor("#F1EFE8"))
    canvas.rect(0, H - 1.2*cm, W, 1.2*cm, fill=1, stroke=0)

    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(TEXT_HINT)
    canvas.drawString(1.5*cm, H - 0.85*cm, "VERTROUWELIJK — Intern gebruik")
    canvas.drawRightString(W - 1.5*cm, H - 0.85*cm, "IA-2025-P2P-014 · Procure-to-Pay Audit · FY 2025")

    # Bottom bar
    canvas.setFillColor(colors.HexColor("#F1EFE8"))
    canvas.rect(0, 0, W, 1.0*cm, fill=1, stroke=0)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(TEXT_HINT)
    canvas.drawString(1.5*cm, 0.35*cm, f"Gegenereerd op {date.today().strftime('%d %B %Y')}")
    canvas.drawRightString(W - 1.5*cm, 0.35*cm, f"Pagina {doc.page}")

    canvas.restoreState()


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------
def build_report(match_data: list[dict], output_path: str) -> None:
    styles = make_styles()
    doc    = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.8*cm,  bottomMargin=1.6*cm,
        title="P2P Audit Report FY2025",
        author="Internal Audit",
    )

    story = []
    W     = A4[0] - 3*cm   # usable width

    # -----------------------------------------------------------------------
    # COVER / HEADER
    # -----------------------------------------------------------------------
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("INTERN AUDITRAPPORT", styles["section"]))
    story.append(Paragraph("Procure-to-Pay Proces Audit", styles["title"]))
    story.append(Paragraph("Financiële controls & leveranciersbeheer — FY 2025", styles["subtitle"]))
    story.append(Spacer(1, 0.3*cm))

    meta_data = [
        ["Auditperiode", "1 jan – 31 dec 2025", "Referentie", "IA-2025-P2P-014"],
        ["Uitgebracht",  date.today().strftime("%d %B %Y"), "Classificatie", "Vertrouwelijk"],
        ["Lead auditor", "M. van der Berg",   "Auditee",     "Finance & Inkoop"],
        ["Gereviewed",   "J. Hollander (CAE)", "Status",      "Definitief"],
    ]
    meta_table = Table(meta_data, colWidths=[3*cm, 5.5*cm, 3*cm, 5.5*cm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME",  (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE",  (0,0), (-1,-1), 8),
        ("TEXTCOLOR", (0,0), (0,-1), TEXT_HINT),
        ("TEXTCOLOR", (2,0), (2,-1), TEXT_HINT),
        ("TEXTCOLOR", (1,0), (1,-1), TEXT_PRI),
        ("TEXTCOLOR", (3,0), (3,-1), TEXT_PRI),
        ("FONTNAME",  (1,0), (1,-1), "Helvetica-Bold"),
        ("FONTNAME",  (3,0), (3,-1), "Helvetica-Bold"),
        ("TOPPADDING",(0,0), (-1,-1), 3),
        ("BOTTOMPADDING",(0,0),(-1,-1), 3),
        ("TEXTCOLOR", (3,1), (3,1), RED_DARK),
    ]))
    story.append(meta_table)
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_LINE, spaceAfter=12))

    # -----------------------------------------------------------------------
    # SECTION 1 — RISICOSAMENVATTING
    # -----------------------------------------------------------------------
    story.append(Paragraph("1. RISICOSAMENVATTING", styles["section"]))

    summary_data = [
        [Paragraph("2", ParagraphStyle("sn", fontSize=22, fontName="Helvetica-Bold", textColor=RED_DARK, leading=26)),
         Paragraph("3", ParagraphStyle("sn", fontSize=22, fontName="Helvetica-Bold", textColor=AMB_DARK, leading=26)),
         Paragraph("4", ParagraphStyle("sn", fontSize=22, fontName="Helvetica-Bold", textColor=GRN_DARK, leading=26)),
         Paragraph("9", ParagraphStyle("sn", fontSize=22, fontName="Helvetica-Bold", textColor=BLU_DARK, leading=26))],
        [Paragraph("Hoog risico", styles["body_sm"]),
         Paragraph("Middel risico", styles["body_sm"]),
         Paragraph("Laag risico", styles["body_sm"]),
         Paragraph("Totaal bevindingen", styles["body_sm"])],
    ]
    summary_table = Table(summary_data, colWidths=[W/4]*4)
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,-1), RED_LIGHT),
        ("BACKGROUND", (1,0), (1,-1), AMB_LIGHT),
        ("BACKGROUND", (2,0), (2,-1), GRN_LIGHT),
        ("BACKGROUND", (3,0), (3,-1), BLU_LIGHT),
        ("ALIGN",    (0,0), (-1,-1), "CENTER"),
        ("VALIGN",   (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",   (0,0), (-1,-1), 10),
        ("BOTTOMPADDING",(0,0), (-1,-1), 10),
        ("ROUNDEDCORNERS", [4]),
        ("LEFTPADDING",  (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.5*cm))

    # -----------------------------------------------------------------------
    # SECTION 2 — GRAFIEKEN
    # -----------------------------------------------------------------------
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_LINE, spaceBefore=4, spaceAfter=8))
    story.append(Paragraph("2. BEVINDINGEN & VISUALISATIES", styles["section"]))

    # Stacked bar + donut side by side
    stacked_bytes = make_stacked_bar()
    donut_bytes   = make_donut_chart(2, 3, 4)
    chart_row = Table(
        [[chart_image(stacked_bytes, 9, 5), chart_image(donut_bytes, 6, 5)]],
        colWidths=[9*cm, 6*cm],
    )
    chart_row.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0)]))
    story.append(chart_row)
    story.append(Spacer(1, 0.3*cm))

    # Timeline
    timeline_bytes = make_timeline_chart()
    story.append(chart_image(timeline_bytes, 9, 4.5))
    story.append(Spacer(1, 0.3*cm))

    # Heatmap table
    story.append(Paragraph("Risico heatmap — kans vs. impact", ParagraphStyle("ht", fontSize=9, textColor=TEXT_HINT, fontName="Helvetica", spaceAfter=4)))
    hm_header  = ["", "Laag impact", "Middel impact", "Hoog impact"]
    hm_rows = [
        [Paragraph("Hoog kans", ParagraphStyle("hl", fontSize=8, textColor=TEXT_SEC, fontName="Helvetica")),
         Paragraph("", styles["body_sm"]),
         Paragraph("F-01", ParagraphStyle("hc", fontSize=9, fontName="Helvetica-Bold", textColor=RED_DARK)),
         Paragraph("F-02", ParagraphStyle("hc", fontSize=9, fontName="Helvetica-Bold", textColor=RED_DARK))],
        [Paragraph("Middel kans", ParagraphStyle("hl", fontSize=8, textColor=TEXT_SEC, fontName="Helvetica")),
         Paragraph("F-07, F-08", ParagraphStyle("hc", fontSize=8, fontName="Helvetica", textColor=GRN_DARK)),
         Paragraph("F-03, F-04", ParagraphStyle("hc", fontSize=8, fontName="Helvetica", textColor=AMB_DARK)),
         Paragraph("", styles["body_sm"])],
        [Paragraph("Laag kans", ParagraphStyle("hl", fontSize=8, textColor=TEXT_SEC, fontName="Helvetica")),
         Paragraph("", styles["body_sm"]),
         Paragraph("F-05", ParagraphStyle("hc", fontSize=8, fontName="Helvetica", textColor=AMB_DARK)),
         Paragraph("", styles["body_sm"])],
    ]
    hm_table = Table([hm_header] + hm_rows, colWidths=[2.8*cm, (W-2.8*cm)/3, (W-2.8*cm)/3, (W-2.8*cm)/3])
    hm_table.setStyle(TableStyle([
        ("FONTNAME",    (0,0),  (-1,0),  "Helvetica"),
        ("FONTSIZE",    (0,0),  (-1,0),  8),
        ("TEXTCOLOR",   (0,0),  (-1,0),  TEXT_HINT),
        ("ALIGN",       (1,0),  (-1,-1), "CENTER"),
        ("VALIGN",      (0,0),  (-1,-1), "MIDDLE"),
        ("TOPPADDING",  (0,0),  (-1,-1), 8),
        ("BOTTOMPADDING",(0,0), (-1,-1), 8),
        ("BACKGROUND",  (1,1),  (1,1),  GRN_LIGHT),
        ("BACKGROUND",  (2,1),  (2,1),  RED_LIGHT),
        ("BACKGROUND",  (3,1),  (3,1),  RED_LIGHT),
        ("BACKGROUND",  (1,2),  (1,2),  GRN_LIGHT),
        ("BACKGROUND",  (2,2),  (2,2),  AMB_LIGHT),
        ("BACKGROUND",  (3,2),  (3,2),  RED_LIGHT),
        ("BACKGROUND",  (1,3),  (1,3),  GRN_LIGHT),
        ("BACKGROUND",  (2,3),  (2,3),  AMB_LIGHT),
        ("BACKGROUND",  (3,3),  (3,3),  AMB_LIGHT),
        ("GRID",        (1,1),  (-1,-1), 0.5, GRAY_LINE),
        ("BOX",         (1,1),  (-1,-1), 0.5, GRAY_LINE),
    ]))
    story.append(hm_table)

    # -----------------------------------------------------------------------
    # SECTION 3 — KEY FINDINGS
    # -----------------------------------------------------------------------
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_LINE, spaceBefore=12, spaceAfter=8))
    story.append(Paragraph("3. BELANGRIJKSTE BEVINDINGEN", styles["section"]))

    findings = [
        ("High", "F-01", "Functiescheiding — inkoopordergoedkeuring",
         "11 gevallen waarbij dezelfde persoon een PO boven €50k aanmaakte EN goedkeurde. COSO 2013 CC 10.3 overtreding.", 0.88),
        ("High", "F-02", "3-way match niet afgedwongen bij 23% facturen",
         "€2,3M aan betalingen zonder koppeling PO + GRN + factuur. Risico op dubbele en foutieve betalingen.", 0.79),
        ("Medium", "F-03", "Leveranciersbestand — 47 inactieve leveranciers niet geblokkeerd",
         "Betalingsbevoegdheid voor leveranciers zonder activiteit in 24+ maanden. Verhoogd frauderisico.", 0.54),
        ("Medium", "F-04", "Contractverlenging — 9 contracten automatisch verlengd zonder review",
         "Totaalwaarde €870k. Geen gedocumenteerde goedkeuring of benchmarking vóór verlenging.", 0.48),
        ("Low",    "F-05", "Inkoopbeleid — versiebeheerproblemen",
         "Beleid 28 maanden niet herzien. Twee sub-procedures verwijzen naar SAP ECC.", 0.22),
    ]

    for sev, fid, title, desc, score in findings:
        bg   = RED_LIGHT if sev == "High" else AMB_LIGHT if sev == "Medium" else GRN_LIGHT
        fg   = RED_DARK  if sev == "High" else AMB_DARK  if sev == "Medium" else GRN_DARK
        bar_color = "#E24B4A" if sev == "High" else "#EF9F27" if sev == "Medium" else "#639922"

        badge_cell = Paragraph(sev, ParagraphStyle("fb", fontSize=8, fontName="Helvetica-Bold",
                                                    textColor=fg, backColor=bg,
                                                    borderPadding=(3,8,3,8), leading=13))
        id_cell    = Paragraph(fid, styles["mono"])
        title_cell = Paragraph(f"<b>{title}</b>", styles["bold"])
        desc_cell  = Paragraph(desc, styles["body_sm"])

        row = Table(
            [[badge_cell, Table([[title_cell],[desc_cell]], colWidths=[W - 3.5*cm]), id_cell]],
            colWidths=[1.4*cm, W - 3.5*cm, 1.5*cm],
        )
        row.setStyle(TableStyle([
            ("VALIGN",  (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING",  (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING",   (0,0), (-1,-1), 0),
            ("BOTTOMPADDING",(0,0), (-1,-1), 0),
        ]))

        card = Table([[row]], colWidths=[W])
        card.setStyle(TableStyle([
            ("BOX",    (0,0), (-1,-1), 0.5, GRAY_LINE),
            ("BACKGROUND", (0,0), (-1,-1), WHITE),
            ("TOPPADDING",    (0,0), (-1,-1), 10),
            ("BOTTOMPADDING", (0,0), (-1,-1), 10),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
            ("RIGHTPADDING",  (0,0), (-1,-1), 10),
        ]))
        story.append(KeepTogether([card, Spacer(1, 0.2*cm)]))

    # -----------------------------------------------------------------------
    # SECTION 4 — 3-WAY MATCH RESULTATEN
    # -----------------------------------------------------------------------
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_LINE, spaceBefore=8, spaceAfter=8))
    story.append(Paragraph("4. 3-WAY MATCH RESULTATEN", styles["section"]))
    story.append(Paragraph(
        "Onderstaande resultaten zijn gegenereerd door <font name='Courier'>three_way_match.py</font> "
        "op basis van de testdataset van 10 scenario's.",
        styles["body_sm"],
    ))
    story.append(Spacer(1, 0.3*cm))

    if match_data:
        # Bar chart of all scenarios
        bar_bytes = make_bar_chart(match_data)
        story.append(chart_image(bar_bytes, 17, 5))
        story.append(Spacer(1, 0.4*cm))

        # Match summary cards from JSON
        match_n = sum(1 for d in match_data if d["result"] == "MATCH")
        warn_n  = sum(1 for d in match_data if d["result"] == "WARNING")
        fail_n  = sum(1 for d in match_data if d["result"] == "FAIL")
        total_po = sum(d["po_total"] for d in match_data)
        total_inv= sum(d["inv_total"] for d in match_data)

        mc_data = [
            [Paragraph(str(match_n), ParagraphStyle("mn", fontSize=20, fontName="Helvetica-Bold", textColor=GRN_DARK, leading=24)),
             Paragraph(str(warn_n),  ParagraphStyle("mn", fontSize=20, fontName="Helvetica-Bold", textColor=AMB_DARK, leading=24)),
             Paragraph(str(fail_n),  ParagraphStyle("mn", fontSize=20, fontName="Helvetica-Bold", textColor=RED_DARK, leading=24)),
             Paragraph(fmt_eur(total_inv - total_po), ParagraphStyle("mn", fontSize=14, fontName="Helvetica-Bold",
                       textColor=(RED_DARK if total_inv > total_po else GRN_DARK), leading=24))],
            [Paragraph("Match", styles["body_sm"]),
             Paragraph("Warning", styles["body_sm"]),
             Paragraph("Fail", styles["body_sm"]),
             Paragraph("Totale afwijking", styles["body_sm"])],
        ]
        mc_table = Table(mc_data, colWidths=[W/4]*4)
        mc_table.setStyle(TableStyle([
            ("BACKGROUND", (0,0),(0,-1), GRN_LIGHT),
            ("BACKGROUND", (1,0),(1,-1), AMB_LIGHT),
            ("BACKGROUND", (2,0),(2,-1), RED_LIGHT),
            ("BACKGROUND", (3,0),(3,-1), BLU_LIGHT),
            ("ALIGN",    (0,0),(-1,-1), "CENTER"),
            ("VALIGN",   (0,0),(-1,-1), "MIDDLE"),
            ("TOPPADDING",   (0,0),(-1,-1), 8),
            ("BOTTOMPADDING",(0,0),(-1,-1), 8),
        ]))
        story.append(mc_table)
        story.append(Spacer(1, 0.4*cm))

        # Detail table
        tbl_header = ["Scenario", "Omschrijving", "PO", "GRN", "Factuur", "Afwijking", "Resultaat"]
        tbl_rows   = [tbl_header]
        for d in match_data:
            disc = d["inv_total"] - d["po_total"]
            disc_str = ("+" if disc > 0 else "") + fmt_eur(disc) if abs(disc) > 0.01 else "—"
            tbl_rows.append([
                Paragraph(d["scenario_id"], styles["mono"]),
                Paragraph(d["title"][:45] + ("…" if len(d["title"]) > 45 else ""), styles["body_sm"]),
                Paragraph(fmt_eur(d["po_total"]),  styles["body_sm"]),
                Paragraph(fmt_eur(d["grn_total"]), styles["body_sm"]),
                Paragraph(fmt_eur(d["inv_total"]), styles["body_sm"]),
                Paragraph(disc_str, ParagraphStyle("disc", fontSize=9, fontName="Helvetica-Bold",
                          textColor=(RED_DARK if disc > 0.01 else AMB_DARK if disc < -0.01 else TEXT_HINT))),
                badge_para(d["result"], styles),
            ])

        col_w = [1.5*cm, 5.5*cm, 2.2*cm, 2.2*cm, 2.2*cm, 2.0*cm, 1.8*cm]
        det_table = Table(tbl_rows, colWidths=col_w, repeatRows=1)
        det_table.setStyle(TableStyle([
            ("BACKGROUND",  (0,0), (-1,0),  GRAY_BG),
            ("FONTNAME",    (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",    (0,0), (-1,-1), 8),
            ("TEXTCOLOR",   (0,0), (-1,0),  TEXT_HINT),
            ("ALIGN",       (2,0), (-1,-1), "RIGHT"),
            ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING",  (0,0), (-1,-1), 5),
            ("BOTTOMPADDING",(0,0),(-1,-1), 5),
            ("LINEBELOW",   (0,0), (-1,-2), 0.3, GRAY_LINE),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, GRAY_BG]),
        ]))
        story.append(det_table)

        # Issues per scenario
        story.append(Spacer(1, 0.4*cm))
        story.append(Paragraph("Issues per scenario", ParagraphStyle("iss_hdr", fontSize=9, textColor=TEXT_HINT, fontName="Helvetica", spaceAfter=6)))
        for d in match_data:
            all_issues = [iss for group in d.get("issues", []) for iss in group.get("issues", [])]
            if not all_issues:
                continue
            iss_style = styles["issue_fail"] if d["result"] == "FAIL" else styles["issue_warn"]
            block = [Paragraph(f"<b>{d['scenario_id']}</b> — {d['title']}", styles["body_sm"])]
            for iss in all_issues:
                block.append(Paragraph(f"  • {iss}", iss_style))
            story.append(KeepTogether(block + [Spacer(1, 0.15*cm)]))
    else:
        story.append(Paragraph(
            "Geen match_results.json gevonden. Voer eerst three_way_match.py uit.",
            ParagraphStyle("warn", fontSize=10, textColor=AMB_DARK, fontName="Helvetica-Bold"),
        ))

    # -----------------------------------------------------------------------
    # SECTION 5 — AANBEVELINGEN
    # -----------------------------------------------------------------------
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_LINE, spaceBefore=12, spaceAfter=8))
    story.append(Paragraph("5. AANBEVELINGEN", styles["section"]))

    recs = [
        ("CIO + CFO", "Q3 2026",
         "Implementeer systeem-afgedwongen functiescheiding in ERP voor alle PO's boven €25k — blokkeer zelfgoedkeuring op transactieniveau."),
        ("Hoofd AP", "Q2 2026",
         "Activeer verplichte 3-way match in AP-module. Betalingen boven €10k vereisen gekoppelde GRN vóór vrijgave."),
        ("Inkoopmanager", "Q2 2026",
         "Voer leveranciersbestandsopschoning uit: deactiveer slapende leveranciers en stel jaarlijkse reviewcyclus in met Inkoop-akkoord."),
        ("Legal & Inkoop", "Q3 2026",
         "Stel contractverlengingskalender in met 90 dagen vooraf melding en verplichte goedkeuringsgate vóór automatische verlenging."),
    ]

    rec_rows = [[
        Paragraph("Aanbeveling", ParagraphStyle("rh", fontSize=8, fontName="Helvetica-Bold", textColor=TEXT_HINT)),
        Paragraph("Eigenaar", ParagraphStyle("rh", fontSize=8, fontName="Helvetica-Bold", textColor=TEXT_HINT)),
        Paragraph("Deadline", ParagraphStyle("rh", fontSize=8, fontName="Helvetica-Bold", textColor=TEXT_HINT)),
    ]]
    for owner, due, text in recs:
        rec_rows.append([
            Paragraph(text, styles["body_sm"]),
            Paragraph(owner, styles["body_sm"]),
            Paragraph(due, ParagraphStyle("due", fontSize=9, fontName="Helvetica-Bold", textColor=BLU_DARK)),
        ])

    rec_table = Table(rec_rows, colWidths=[10.5*cm, 3*cm, 2*cm], repeatRows=1)
    rec_table.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,0),  GRAY_BG),
        ("FONTSIZE",     (0,0), (-1,-1), 9),
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",   (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0), (-1,-1), 6),
        ("LINEBELOW",    (0,0), (-1,-2), 0.3, GRAY_LINE),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, GRAY_BG]),
    ]))
    story.append(rec_table)

    # -----------------------------------------------------------------------
    # SECTION 6 — CONCLUSIE
    # -----------------------------------------------------------------------
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_LINE, spaceBefore=12, spaceAfter=8))
    story.append(Paragraph("6. CONCLUSIE AUDITOR", styles["section"]))

    conc_table = Table([[Paragraph(
        "Het P2P-proces vertoont een <b>matig tot hoog controlrisicoprofiel</b> voor FY 2025. "
        "Twee bevindingen met hoge ernst — functiescheiding en 3-way match compliance — vereisen directe actie. "
        "De overige bevindingen zijn beheersbaar binnen standaard herstelcycli. "
        "Management heeft bevindingen F-01 t/m F-05 erkend en initiële herstelafspraken gemaakt. "
        "Een vervolgtoetsing is gepland voor Q4 2026.",
        styles["conc"],
    )]], colWidths=[W])
    conc_table.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0), (-1,-1), 12),
        ("RIGHTPADDING", (0,0), (-1,-1), 12),
        ("TOPPADDING",   (0,0), (-1,-1), 10),
        ("BOTTOMPADDING",(0,0), (-1,-1), 10),
        ("BACKGROUND",   (0,0), (-1,-1), GRAY_BG),
        ("LINEBEFORE",   (0,0), (0,-1),  2, BLU_DARK),
    ]))
    story.append(conc_table)
    story.append(Spacer(1, 0.6*cm))

    # Signatures
    sig_data = [
        [Paragraph("LEAD AUDITOR", styles["label"]),
         Paragraph("GEREVIEWED DOOR", styles["label"]),
         Paragraph("STATUS", styles["label"])],
        [Paragraph("M. van der Berg", styles["value"]),
         Paragraph("J. Hollander", styles["value"]),
         Paragraph("Definitief", ParagraphStyle("sv", fontSize=10, fontName="Helvetica-Bold", textColor=GRN_DARK))],
        [Paragraph("Internal Audit", styles["body_sm"]),
         Paragraph("Chief Audit Executive", styles["body_sm"]),
         Paragraph(date.today().strftime("%d %B %Y"), styles["body_sm"])],
    ]
    sig_table = Table(sig_data, colWidths=[W/3]*3)
    sig_table.setStyle(TableStyle([
        ("TOPPADDING",   (0,0), (-1,-1), 3),
        ("BOTTOMPADDING",(0,0), (-1,-1), 3),
        ("LINEABOVE",    (0,0), (-1,0),  0.5, GRAY_LINE),
    ]))
    story.append(sig_table)

    # -----------------------------------------------------------------------
    # BUILD
    # -----------------------------------------------------------------------
    doc.build(story, onFirstPage=make_page_template, onLaterPages=make_page_template)
    print(f"\nRapport gegenereerd: {output_path}")
    print(f"Bestandsgrootte    : {os.path.getsize(output_path) / 1024:.1f} KB")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    json_path = sys.argv[1] if len(sys.argv) > 1 else "match_results.json"
    pdf_path  = sys.argv[2] if len(sys.argv) > 2 else "audit_rapport_P2P.pdf"

    match_data = []
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            match_data = json.load(f)
        print(f"Match data geladen: {len(match_data)} scenario's uit {json_path}")
    else:
        print(f"Let op: {json_path} niet gevonden. Rapport wordt gegenereerd zonder match data.")
        print("Voer eerst 'python three_way_match.py' uit om match_results.json aan te maken.")

    build_report(match_data, pdf_path)
