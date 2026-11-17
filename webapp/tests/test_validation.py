"""Tests for rejecting invalid documents.

Two layers reject: the parser (file format, number notation, alias columns,
flat-CSV consistency, formula cells) and the pandera validation in
app/services/validation.py (required fields, ranges, arithmetic, one price
per SKU). These tests check that a document is rejected and why, not which
layer caught it, so either may own a rule.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.parsers import ParseError, parse_document

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"

HEADER = "field,value\ndocument_number,{doc}\npo_number,PO-1\nsupplier,ACME BV\n\n"
LINES = "line_number,sku,description,quantity,unit_price,line_total\n"


def _csv(lines: str, doc: str = "INV-1", header: str | None = None) -> bytes:
    return ((HEADER.format(doc=doc) if header is None else header) + LINES + lines).encode()


def _invoice(lines: str, **kw) -> dict:
    return parse_document(_csv(lines, **kw), "invoice.csv", "INVOICE")


def _rejects(data: bytes, *fragments: str, doc_type: str = "INVOICE", name: str = "invoice.csv"):
    """Assert the document is rejected, the message names the file, and it
    contains at least one of `fragments` (the reason, in either layer's words)."""
    with pytest.raises(ParseError) as exc:
        parse_document(data, name, doc_type)
    msg = str(exc.value)
    assert msg.startswith(f"'{name}': "), msg
    assert any(f.lower() in msg.lower() for f in fragments), msg


# --- the shipped samples stay valid ---------------------------------------
@pytest.mark.parametrize("name,doc_type", [
    ("po_sample.csv", "PO"),
    ("po_sample.json", "PO"),
    ("grn_sample.csv", "GRN"),
    ("invoice_sample.csv", "INVOICE"),
    ("invoice_mismatch.csv", "INVOICE"),
])
def test_samples_pass(name, doc_type):
    doc = parse_document((SAMPLES / name).read_bytes(), name, doc_type)
    assert doc["lines"]


def test_valid_invoice_passes():
    doc = _invoice("1,SKU-A,Widget,2,10.00,20.00\n")
    assert doc["lines"][0]["line_total"] == 20.0


# --- #16 blank / NaN / infinite numbers -----------------------------------
@pytest.mark.parametrize("qty", ["", "nan", "NaN"])
def test_missing_or_nan_quantity_rejected(qty):
    _rejects(_csv(f"1,SKU-A,Widget,{qty},10.00,20.00\n"), "'quantity': ontbreekt", "aantal")


@pytest.mark.parametrize("value", ["inf", "1e309", "-5"])
def test_infinite_or_negative_price_rejected(value):
    _rejects(_csv(f"1,SKU-A,Widget,2,{value},20.00\n"), "'unit_price'", "stukprijs")


def test_blank_price_rejected_on_invoice_but_allowed_on_grn():
    _rejects(_csv("1,SKU-A,Widget,2,,\n"), "'unit_price': ontbreekt")
    grn = _csv("1,SKU-A,Widget,2,,\n", doc="GRN-1")
    assert parse_document(grn, "grn.csv", "GRN")["lines"]


def test_nan_in_json_rejected():
    data = json.dumps({"document_number": "INV-1", "po_number": "PO-1", "supplier": "ACME",
                       "lines": [{"sku": "A", "quantity": float("nan"),
                                  "unit_price": 1, "line_total": 1}]}).encode()
    _rejects(data, "ontbreekt", "NaN", name="invoice.json")


# --- #17 arithmetic and split-line overpricing ----------------------------
def test_line_arithmetic_mismatch_rejected():
    _rejects(_csv("1,SKU-A,Widget,49,999.00,1200.50\n"), "komt niet overeen met regeltotaal")


def test_split_sku_with_different_prices_rejected():
    _rejects(_csv("1,SKU-A,Widget,1,24.50,24.50\n2,SKU-A,Widget,49,999.00,48951.00\n"),
             "verschillende stukprijzen")


def test_split_sku_with_same_price_allowed():
    doc = _invoice("1,SKU-A,Widget,1,24.50,24.50\n2,SKU-A,Widget,49,24.50,1200.50\n")
    assert len(doc["lines"]) == 2


# --- #19 header fields ----------------------------------------------------
def test_empty_header_rejected():
    header = "field,value\ndocument_number,\npo_number,\nsupplier,\n\n"
    _rejects(_csv("1,SKU-A,Widget,2,10.00,20.00\n", header=header), "Kop 'supplier': is leeg")


def test_flat_csv_with_conflicting_po_rejected():
    data = (b"document_number,po_number,supplier,sku,quantity,unit_price,line_total\n"
            b"INV-1,PO-1,ACME,SKU-A,1,10,10\n"
            b"INV-1,PO-2,ACME,SKU-B,1,10,10\n")
    _rejects(data, "verschillende waarden voor 'po_number'")


# --- #21 formula injection ------------------------------------------------
@pytest.mark.parametrize("cell", ["=HYPERLINK(1)", "@SUM(A1)", "+1+1", "-2+3"])
def test_formula_in_text_field_rejected(cell):
    _rejects(_csv("1,SKU-A," + cell + ",2,10.00,20.00\n"), "formule")


# --- ambiguous alias columns ----------------------------------------------
def test_evasion_sample_rejected():
    data = (SAMPLES / "invoice_evasion.csv").read_bytes()
    _rejects(data, "geven verschillende waarden")


# --- end-to-end -----------------------------------------------------------
def test_api_returns_400_on_invalid_invoice():
    client = TestClient(app)
    files = {
        "po_file": ("po.csv", (SAMPLES / "po_sample.csv").read_bytes()),
        "grn_file": ("grn.csv", (SAMPLES / "grn_sample.csv").read_bytes()),
        "invoice_file": ("inv.csv", _csv("1,SKU-A100,Widget,50,nan,1225.00\n")),
    }
    resp = client.post("/api/match", files=files)
    assert resp.status_code == 400
    assert resp.json()["error"].startswith("'inv.csv': ")


def test_api_still_matches_valid_samples():
    client = TestClient(app)
    files = {
        "po_file": ("po.csv", (SAMPLES / "po_sample.csv").read_bytes()),
        "grn_file": ("grn.csv", (SAMPLES / "grn_sample.csv").read_bytes()),
        "invoice_file": ("inv.csv", (SAMPLES / "invoice_sample.csv").read_bytes()),
    }
    resp = client.post("/api/match", files=files)
    assert resp.status_code == 200
    assert resp.json()["result"] in {"MATCH", "WARNING"}


def test_invoice_without_po_reference_rejected():
    header = "field,value\ndocument_number,INV-1\nsupplier,ACME BV\n\n"
    _rejects(_csv("1,SKU-A,Widget,2,10.00,20.00\n", header=header), "Kop 'po_number': is leeg")


def test_po_may_use_document_number_as_po_number():
    header = "field,value\ndocument_number,PO-1\nsupplier,ACME BV\n\n"
    doc = parse_document(_csv("1,SKU-A,Widget,2,10.00,20.00\n", header=header), "po.csv", "PO")
    assert doc["po_number"] == "PO-1"
