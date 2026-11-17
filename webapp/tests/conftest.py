import sys
from pathlib import Path

import pytest

WEBAPP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEBAPP))

SAMPLES = WEBAPP / "sample_data"

PO_HEADER = """field,value
document_number,PO-2025-0142
po_number,PO-2025-0142
supplier,ACME Industrial BV
date,2025-08-14
"""
GRN_HEADER = PO_HEADER.replace("document_number,PO-2025-0142", "document_number,GRN-2025-2317")
INV_HEADER = PO_HEADER.replace("document_number,PO-2025-0142", "document_number,INV-2025-8891")

LINES_COLS = "line_number,sku,description,quantity,unit_price,line_total"


def csv_doc(header: str, lines: list[str], cols: str = LINES_COLS) -> bytes:
    return (header + "\n" + cols + "\n" + "\n".join(lines) + "\n").encode()


@pytest.fixture
def sample_bytes():
    return {
        "po": (SAMPLES / "po_sample.csv").read_bytes(),
        "grn": (SAMPLES / "grn_sample.csv").read_bytes(),
        "inv": (SAMPLES / "invoice_sample.csv").read_bytes(),
    }
