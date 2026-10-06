"""FastAPI application for the Three-way Match webapp."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.services.matcher import three_way_match
from app.services.parsers import ParseError, parse_document

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
SAMPLE_DIR = BASE_DIR.parent / "sample_data"

app = FastAPI(title="Three-way Match Audit", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/match", response_class=HTMLResponse)
async def match(
    request: Request,
    po_file: UploadFile = File(...),
    grn_file: UploadFile = File(...),
    invoice_file: UploadFile = File(...),
    price_tolerance: float = Form(0.01),
    qty_tolerance: float = Form(0.0),
    total_tolerance: float = Form(0.05),
    line_total_tolerance: float = Form(0.01),
):
    try:
        po = parse_document(await po_file.read(), po_file.filename or "po", "PO")
        grn = parse_document(await grn_file.read(), grn_file.filename or "grn", "GRN")
        inv = parse_document(await invoice_file.read(), invoice_file.filename or "invoice", "INVOICE")
    except ParseError as e:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": str(e)},
            status_code=400,
        )

    report = three_way_match(
        po, grn, inv,
        price_tolerance=price_tolerance,
        qty_tolerance=qty_tolerance,
        total_tolerance=total_tolerance,
        line_total_tolerance=line_total_tolerance,
    )

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "report": report.to_dict(),
            "filenames": {
                "po": po_file.filename,
                "grn": grn_file.filename,
                "invoice": invoice_file.filename,
            },
        },
    )


@app.post("/api/match")
async def match_api(
    po_file: UploadFile = File(...),
    grn_file: UploadFile = File(...),
    invoice_file: UploadFile = File(...),
    price_tolerance: float = Form(0.01),
    qty_tolerance: float = Form(0.0),
    total_tolerance: float = Form(0.05),
    line_total_tolerance: float = Form(0.01),
):
    try:
        po = parse_document(await po_file.read(), po_file.filename or "po", "PO")
        grn = parse_document(await grn_file.read(), grn_file.filename or "grn", "GRN")
        inv = parse_document(await invoice_file.read(), invoice_file.filename or "invoice", "INVOICE")
    except ParseError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    report = three_way_match(
        po, grn, inv,
        price_tolerance=price_tolerance,
        qty_tolerance=qty_tolerance,
        total_tolerance=total_tolerance,
        line_total_tolerance=line_total_tolerance,
    )
    return report.to_dict()


@app.get("/sample/{name}")
async def sample(name: str):
    path = SAMPLE_DIR / name
    if not path.exists() or not path.is_file() or path.parent != SAMPLE_DIR:
        return JSONResponse({"error": "Voorbeeldbestand niet gevonden."}, status_code=404)
    media = "application/json" if name.endswith(".json") else "text/csv"
    return HTMLResponse(path.read_text(encoding="utf-8"), media_type=media)
