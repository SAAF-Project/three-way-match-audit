"""FastAPI application for the Three-way Match webapp."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.services.agent import run_audit_agent
from app.services.audit_log import build as build_audit_log
from app.services.matcher import three_way_match
from app.services.parsers import ParseError, parse_document

_MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB per file


async def _read_limited(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"{file.filename}: bestand te groot (max 5 MB).")
    return data

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
SAMPLE_DIR = BASE_DIR.parent / "sample_data"

app = FastAPI(title="Three-way Match Audit", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.post("/match", response_class=HTMLResponse)
async def match(
    request: Request,
    po_file: UploadFile = File(...),
    grn_file: UploadFile = File(...),
    invoice_file: UploadFile = File(...),
    price_tolerance: float = Form(0.01, ge=0, le=1),
    qty_tolerance: float = Form(0.0, ge=0, le=1),
    total_tolerance: float = Form(0.05, ge=0, le=1),
):
    try:
        po = parse_document(await _read_limited(po_file), po_file.filename or "po", "PO")
        grn = parse_document(await _read_limited(grn_file), grn_file.filename or "grn", "GRN")
        inv = parse_document(await _read_limited(invoice_file), invoice_file.filename or "invoice", "INVOICE")
    except ParseError as e:
        return templates.TemplateResponse(
            request, "index.html", {"error": str(e)}, status_code=400,
        )

    report = three_way_match(
        po, grn, inv,
        price_tolerance=price_tolerance,
        qty_tolerance=qty_tolerance,
        total_tolerance=total_tolerance,
    )

    return templates.TemplateResponse(
        request, "result.html",
        {
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
    price_tolerance: float = Form(0.01, ge=0, le=1),
    qty_tolerance: float = Form(0.0, ge=0, le=1),
    total_tolerance: float = Form(0.05, ge=0, le=1),
):
    try:
        po = parse_document(await _read_limited(po_file), po_file.filename or "po", "PO")
        grn = parse_document(await _read_limited(grn_file), grn_file.filename or "grn", "GRN")
        inv = parse_document(await _read_limited(invoice_file), invoice_file.filename or "invoice", "INVOICE")
    except ParseError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    report = three_way_match(
        po, grn, inv,
        price_tolerance=price_tolerance,
        qty_tolerance=qty_tolerance,
        total_tolerance=total_tolerance,
    )
    return report.to_dict()


@app.get("/sample/{name}")
async def sample(name: str):
    path = (SAMPLE_DIR / name).resolve()
    if not path.exists() or not path.is_file() or not path.is_relative_to(SAMPLE_DIR.resolve()):
        return JSONResponse({"error": "Voorbeeldbestand niet gevonden."}, status_code=404)
    media = "application/json" if name.endswith(".json") else "text/csv"
    return HTMLResponse(path.read_text(encoding="utf-8"), media_type=media)


@app.post("/match/explain", response_class=HTMLResponse)
async def match_explain(
    request: Request,
    po_file: UploadFile = File(...),
    grn_file: UploadFile = File(...),
    invoice_file: UploadFile = File(...),
    price_tolerance: float = Form(0.01, ge=0, le=1),
    qty_tolerance: float = Form(0.0, ge=0, le=1),
    total_tolerance: float = Form(0.05, ge=0, le=1),
):
    try:
        po_bytes = await _read_limited(po_file)
        grn_bytes = await _read_limited(grn_file)
        inv_bytes = await _read_limited(invoice_file)
        po = parse_document(po_bytes, po_file.filename or "po", "PO")
        grn = parse_document(grn_bytes, grn_file.filename or "grn", "GRN")
        inv = parse_document(inv_bytes, invoice_file.filename or "invoice", "INVOICE")
    except ParseError as e:
        return templates.TemplateResponse(
            request, "index.html", {"error": str(e)}, status_code=400,
        )

    # The AI agent calls the matcher as a tool — it drives the entire workflow
    agent_result = run_audit_agent(
        po, grn, inv, price_tolerance, qty_tolerance, total_tolerance,
    )
    if agent_result:
        report_dict = agent_result["report"]
        narrative   = agent_result["narrative"]
        tool_calls  = agent_result["tool_calls"]
    else:
        # Fallback: rule-based only (no API key or agent error)
        report_dict = three_way_match(
            po, grn, inv,
            price_tolerance=price_tolerance,
            qty_tolerance=qty_tolerance,
            total_tolerance=total_tolerance,
        ).to_dict()
        narrative  = None
        tool_calls = []

    log = build_audit_log(
        po_bytes=po_bytes, grn_bytes=grn_bytes, invoice_bytes=inv_bytes,
        po_filename=po_file.filename or "po",
        grn_filename=grn_file.filename or "grn",
        invoice_filename=invoice_file.filename or "invoice",
        price_tolerance=price_tolerance,
        qty_tolerance=qty_tolerance,
        total_tolerance=total_tolerance,
        match_report=report_dict,
        audit_narrative=narrative,
        tool_calls=tool_calls,
    )

    return templates.TemplateResponse(
        request, "result.html",
        {
            "report": report_dict,
            "narrative": narrative,
            "audit_log_json": json.dumps(log, indent=2, ensure_ascii=False),
            "filenames": {
                "po": po_file.filename,
                "grn": grn_file.filename,
                "invoice": invoice_file.filename,
            },
        },
    )


@app.post("/api/match/explain")
async def match_explain_api(
    po_file: UploadFile = File(...),
    grn_file: UploadFile = File(...),
    invoice_file: UploadFile = File(...),
    price_tolerance: float = Form(0.01, ge=0, le=1),
    qty_tolerance: float = Form(0.0, ge=0, le=1),
    total_tolerance: float = Form(0.05, ge=0, le=1),
):
    try:
        po_bytes = await _read_limited(po_file)
        grn_bytes = await _read_limited(grn_file)
        inv_bytes = await _read_limited(invoice_file)
        po = parse_document(po_bytes, po_file.filename or "po", "PO")
        grn = parse_document(grn_bytes, grn_file.filename or "grn", "GRN")
        inv = parse_document(inv_bytes, invoice_file.filename or "invoice", "INVOICE")
    except ParseError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    agent_result = run_audit_agent(
        po, grn, inv, price_tolerance, qty_tolerance, total_tolerance,
    )
    if agent_result:
        report_dict = agent_result["report"]
        narrative   = agent_result["narrative"]
        tool_calls  = agent_result["tool_calls"]
    else:
        report_dict = three_way_match(
            po, grn, inv,
            price_tolerance=price_tolerance,
            qty_tolerance=qty_tolerance,
            total_tolerance=total_tolerance,
        ).to_dict()
        narrative  = None
        tool_calls = []

    log = build_audit_log(
        po_bytes=po_bytes, grn_bytes=grn_bytes, invoice_bytes=inv_bytes,
        po_filename=po_file.filename or "po",
        grn_filename=grn_file.filename or "grn",
        invoice_filename=invoice_file.filename or "invoice",
        price_tolerance=price_tolerance,
        qty_tolerance=qty_tolerance,
        total_tolerance=total_tolerance,
        match_report=report_dict,
        audit_narrative=narrative,
        tool_calls=tool_calls,
    )
    return JSONResponse(log)
