"""Regression tests for the issues on SAAF-Project/three-way-match-audit.

Each test feeds the exact evasion from an issue through the parser and the
matcher. Before the fix every one of them came back as a green MATCH.

Invalid documents are stopped by the parser or by the pandera validation
(services/validation.py). Where a rule also lives in the matcher as a
backstop, a second test passes the bad document to the matcher directly and
expects FAIL.
"""
import pytest

from app.services.matcher import three_way_match
from app.services.parsers import ParseError, parse_document
from conftest import GRN_HEADER, INV_HEADER, PO_HEADER, SAMPLES, csv_doc

PO_LINES = [
    "1,SKU-A100,Widget A,50,24.50,1225.00",
    "2,SKU-B200,Widget B,20,89.00,1780.00",
    "3,SKU-C300,Bevestigingsset,100,3.75,375.00",
]
GRN_LINES = [
    "1,SKU-A100,Widget A,50",
    "2,SKU-B200,Widget B,20",
    "3,SKU-C300,Bevestigingsset,100",
]


def match(po: bytes, grn: bytes, inv: bytes, **tol):
    return three_way_match(
        parse_document(po, "po.csv", "PO"),
        parse_document(grn, "grn.csv", "GRN"),
        parse_document(inv, "inv.csv", "INVOICE"),
        **tol,
    )


def valid_docs():
    """Parsed PO, GRN and invoice that match, for mutating in matcher tests."""
    return (parse_document(po_csv(), "po.csv", "PO"),
            parse_document(grn_csv(), "grn.csv", "GRN"),
            parse_document(inv_csv(), "inv.csv", "INVOICE"))


def po_csv():
    return csv_doc(PO_HEADER, PO_LINES)


def grn_csv():
    return csv_doc(GRN_HEADER, GRN_LINES, "line_number,sku,description,quantity")


def inv_csv(lines=None, header=INV_HEADER):
    return csv_doc(header, lines or PO_LINES)


# --- Baseline ---------------------------------------------------------------
def test_samples_still_match():
    report = match((SAMPLES / "po_sample.csv").read_bytes(),
                   (SAMPLES / "grn_sample.csv").read_bytes(),
                   (SAMPLES / "invoice_sample.csv").read_bytes())
    assert report.result == "MATCH", report.to_dict()


def test_json_po_sample_matches_csv_documents():
    report = three_way_match(
        parse_document((SAMPLES / "po_sample.json").read_bytes(), "po.json", "PO"),
        parse_document(grn_csv(), "grn.csv", "GRN"),
        parse_document(inv_csv(), "inv.csv", "INVOICE"),
    )
    assert report.result == "MATCH", report.to_dict()


def test_mismatch_sample_fails():
    report = match((SAMPLES / "po_sample.csv").read_bytes(),
                   (SAMPLES / "grn_sample.csv").read_bytes(),
                   (SAMPLES / "invoice_mismatch.csv").read_bytes())
    assert report.result == "FAIL"


# --- Issue #16: blank, NaN, inf and 1e309 values --------------------------
def test_blank_invoice_quantity_and_price_are_rejected():
    lines = ["1,SKU-A100,Widget A,,,1225.00"] + PO_LINES[1:]
    with pytest.raises(ParseError, match="ontbreekt"):
        parse_document(inv_csv(lines), "inv.csv", "INVOICE")


def test_matcher_fails_on_missing_values():
    po, grn, inv = valid_docs()
    inv["lines"][0]["quantity"] = None
    inv["lines"][0]["unit_price"] = None
    report = three_way_match(po, grn, inv)
    assert report.result == "FAIL"
    line = report.line_results[0]
    assert line.result == "FAIL"
    assert any("aantal ontbreekt" in i for i in line.issues)
    assert any("stukprijs ontbreekt" in i for i in line.issues)


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf", "Infinity", "1e309", "1e3"])
def test_non_finite_numbers_are_rejected(value):
    lines = [f"1,SKU-A100,Widget A,{value},{value},1225.00"] + PO_LINES[1:]
    with pytest.raises(ParseError):
        parse_document(inv_csv(lines), "inv.csv", "INVOICE")


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e309"])
def test_non_finite_json_is_rejected(literal):
    raw = ('{"document_number": "INV-1", "po_number": "PO-1", "supplier": "ACME",'
           f' "lines": [{{"sku": "A", "quantity": {literal}, "unit_price": 1, "line_total": 1}}]}}')
    with pytest.raises(ParseError):
        parse_document(raw.encode(), "inv.json", "INVOICE")


def test_negative_amounts_are_rejected():
    lines = ["1,SKU-A100,Widget A,50,-24.50,1225.00"] + PO_LINES[1:]
    with pytest.raises(ParseError, match="negatief"):
        parse_document(inv_csv(lines), "inv.csv", "INVOICE")


def test_nan_passed_to_matcher_directly_is_not_a_pass():
    po = parse_document(po_csv(), "po.csv", "PO")
    grn = parse_document(grn_csv(), "grn.csv", "GRN")
    inv = parse_document(inv_csv(), "inv.csv", "INVOICE")
    inv["lines"][0]["quantity"] = float("nan")
    inv["lines"][0]["unit_price"] = float("inf")
    report = three_way_match(po, grn, inv)
    assert report.result == "FAIL"
    assert report.line_results[0].result == "FAIL"


def test_api_json_is_valid_rfc8259(sample_bytes):
    import json
    report = match(sample_bytes["po"], sample_bytes["grn"], sample_bytes["inv"])
    json.dumps(report.to_dict(), allow_nan=False)


# --- Issue #17: duplicate SKU rows hide a higher unit price ----------------
SPLIT_OVERPRICED = [
    "1,SKU-A100,Widget A,1,24.50,24.50",
    "2,SKU-A100,Widget A,49,999.00,1200.50",
] + PO_LINES[1:]


def test_split_line_overpricing_is_rejected():
    with pytest.raises(ParseError, match="regeltotaal|stukprijzen"):
        parse_document(inv_csv(SPLIT_OVERPRICED), "inv.csv", "INVOICE")


def test_matcher_fails_on_split_line_overpricing():
    po, grn, inv = valid_docs()
    inv["lines"][:1] = [
        {"line_number": 1, "sku": "SKU-A100", "description": "Widget A",
         "quantity": 1.0, "unit_price": 24.50, "line_total": 24.50},
        {"line_number": 2, "sku": "SKU-A100", "description": "Widget A",
         "quantity": 49.0, "unit_price": 999.00, "line_total": 1200.50},
    ]
    report = three_way_match(po, grn, inv)
    assert report.result == "FAIL"
    line = next(l for l in report.line_results if l.sku == "SKU-A100")
    assert line.result == "FAIL"
    assert any("verschillende stukprijzen" in i for i in line.issues)
    assert any("komt niet overeen met regeltotaal" in i for i in line.issues)


def test_line_arithmetic_is_rejected():
    lines = ["1,SKU-A100,Widget A,50,24.50,1300.00"] + PO_LINES[1:]
    with pytest.raises(ParseError, match="komt niet overeen met regeltotaal"):
        parse_document(inv_csv(lines), "inv.csv", "INVOICE")


def test_matcher_checks_line_arithmetic():
    po, grn, inv = valid_docs()
    inv["lines"][0]["line_total"] = 1300.00
    report = three_way_match(po, grn, inv)
    assert report.result == "FAIL"
    assert any("komt niet overeen met regeltotaal" in i
               for i in report.line_results[0].issues)


def test_consistent_split_lines_still_match():
    lines = [
        "1,SKU-A100,Widget A,20,24.50,490.00",
        "2,SKU-A100,Widget A,30,24.50,735.00",
    ] + PO_LINES[1:]
    report = match(po_csv(), grn_csv(), inv_csv(lines))
    assert report.result == "MATCH", report.to_dict()


# --- Issue #19: empty references and multi-row flat CSVs -------------------
@pytest.mark.parametrize("field,expect", [
    ("po_number", "geen PO-referentie"),
    ("supplier", "geen leveranciersnaam"),
    ("document_number", "geen documentnummer"),
])
def test_empty_header_fields_are_rejected(field, expect):
    header = "\n".join(l for l in INV_HEADER.splitlines() if not l.startswith(field)) + "\n"
    with pytest.raises(ParseError, match=f"'{field}': is leeg"):
        parse_document(inv_csv(header=header), "inv.csv", "INVOICE")


@pytest.mark.parametrize("field,expect", [
    ("po_number", "geen PO-referentie"),
    ("supplier", "geen leveranciersnaam"),
    ("document_number", "geen documentnummer"),
])
def test_matcher_fails_on_empty_header_fields(field, expect):
    po, grn, inv = valid_docs()
    inv[field] = ""
    report = three_way_match(po, grn, inv)
    assert report.result == "FAIL"
    assert any(expect in i for i in report.header_issues), report.header_issues


def test_flat_csv_with_rows_for_two_pos_is_rejected():
    flat = ("po_number,supplier,document_number,line_number,sku,description,quantity,unit_price,line_total\n"
            "PO-2025-0142,ACME Industrial BV,INV-1,1,SKU-A100,Widget A,50,24.50,1225.00\n"
            "PO-2025-9999,ACME Industrial BV,INV-1,2,SKU-B200,Widget B,20,89.00,1780.00\n").encode()
    with pytest.raises(ParseError, match="po_number"):
        parse_document(flat, "inv.csv", "INVOICE")


def test_flat_csv_with_two_suppliers_is_rejected():
    flat = ("po_number,supplier,document_number,line_number,sku,description,quantity,unit_price,line_total\n"
            "PO-2025-0142,ACME Industrial BV,INV-1,1,SKU-A100,Widget A,50,24.50,1225.00\n"
            "PO-2025-0142,Other BV,INV-1,2,SKU-B200,Widget B,20,89.00,1780.00\n").encode()
    with pytest.raises(ParseError, match="supplier"):
        parse_document(flat, "inv.csv", "INVOICE")


def test_consistent_flat_csv_is_accepted():
    flat = ("po_number,supplier,document_number,line_number,sku,description,quantity,unit_price,line_total\n"
            "PO-2025-0142,ACME Industrial BV,INV-1,1,SKU-A100,Widget A,50,24.50,1225.00\n"
            "PO-2025-0142,ACME Industrial BV,INV-1,2,SKU-B200,Widget B,20,89.00,1780.00\n").encode()
    doc = parse_document(flat, "inv.csv", "INVOICE")
    assert doc["po_number"] == "PO-2025-0142" and len(doc["lines"]) == 2


# --- Evasion sample and other fail-open paths ------------------------------
def test_evasion_sample_with_decoy_columns_is_rejected():
    with pytest.raises(ParseError, match="verschillende"):
        parse_document((SAMPLES / "invoice_evasion.csv").read_bytes(), "inv.csv", "INVOICE")


def test_stated_total_must_agree_with_lines():
    header = INV_HEADER + "total,3633.00\n"
    report = match(po_csv(), grn_csv(), inv_csv(header=header))
    assert report.result == "FAIL"
    assert any("som van de regels" in i for i in report.header_issues)


def test_invoiced_but_not_received_fails():
    grn = csv_doc(GRN_HEADER, GRN_LINES[:2], "line_number,sku,description,quantity")
    report = match(po_csv(), grn, inv_csv())
    assert report.result == "FAIL"


def test_rows_after_a_blank_line_are_not_dropped():
    raw = inv_csv() + b"\n" + LINES_EXTRA
    with pytest.raises(ParseError, match="meer dan"):
        parse_document(raw, "inv.csv", "INVOICE")


LINES_EXTRA = b"line_number,sku,description,quantity,unit_price,line_total\n4,SKU-D400,Hidden,1,1000.00,1000.00\n"


@pytest.mark.parametrize("value", ["1,000", "1.000"])
def test_ambiguous_thousands_are_rejected(value):
    lines = [f'1,SKU-A100,Widget A,"{value}",24.50,1225.00'] + PO_LINES[1:]
    with pytest.raises(ParseError, match="dubbelzinnig"):
        parse_document(inv_csv(lines), "inv.csv", "INVOICE")


@pytest.mark.parametrize("text,expected", [
    ("1.225,00", 1225.0), ("1,234.56", 1234.56), ("24,50", 24.5), ("€ 24.50", 24.5),
])
def test_number_formats(text, expected):
    lines = [f'1,SKU-A100,Widget A,1,"{text}","{text}"'] + PO_LINES[1:]
    doc = parse_document(inv_csv(lines), "inv.csv", "INVOICE")
    assert doc["lines"][0]["unit_price"] == expected


@pytest.mark.parametrize("bad", ["-1", "nan", "200", "abc"])
def test_tolerances_are_bounded(bad):
    with pytest.raises(ValueError):
        match(po_csv(), grn_csv(), inv_csv(), price_tolerance=bad)


# --- Issue #21: spreadsheet formula injection, Excel files -----------------
@pytest.mark.parametrize("cell", ["=HYPERLINK(\"http://x\")", "+1+1", "-2+3", "@SUM(A1)",
                                  "=cmd|' /C calc'!A0"])
def test_formula_cells_are_rejected(cell):
    lines = [f'1,"{cell}",Widget A,50,24.50,1225.00'] + PO_LINES[1:]
    with pytest.raises(ParseError, match="formule"):
        parse_document(inv_csv(lines), "inv.csv", "INVOICE")


def test_formula_in_header_is_rejected():
    header = INV_HEADER.replace("ACME Industrial BV", "=1+1")
    with pytest.raises(ParseError, match="formule"):
        parse_document(inv_csv(header=header), "inv.csv", "INVOICE")


@pytest.mark.parametrize("magic", [b"PK\x03\x04", b"\xd0\xcf\x11\xe0", b"%PDF-1.7"])
def test_binary_files_renamed_to_csv_are_rejected(magic):
    with pytest.raises(ParseError):
        parse_document(magic + b"\x00" * 100, "inv.csv", "INVOICE")


def test_control_characters_are_rejected():
    lines = ['1,SKU-A100,"Widget\x07A",50,24.50,1225.00'] + PO_LINES[1:]
    with pytest.raises(ParseError, match="stuurtekens"):
        parse_document(inv_csv(lines), "inv.csv", "INVOICE")


def test_too_many_lines_are_rejected():
    lines = [f"{i},SKU-{i},Item,1,1.00,1.00" for i in range(1, 5002)]
    with pytest.raises(ParseError, match="5000"):
        parse_document(inv_csv(lines), "inv.csv", "INVOICE")
