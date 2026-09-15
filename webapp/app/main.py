"""FastAPI application for the Three-way Match webapp."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.services.matcher import three_way_match
from app.services.parsers import ParseError, parse_document
from app.services.workpaper import (
    build_workpaper,
    source_meta,
    workpaper_filename,
)
import json

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
SAMPLE_DIR = BASE_DIR.parent / "sample_data"

app = FastAPI(title="Three-way Match Audit", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


async def _read_and_parse(uploads: dict[str, UploadFile]) -> tuple[dict, dict, dict]:
    """Read all three files ONCE, capture bytes + parsed shape for both the
    match and the workpaper."""
    raw: dict[str, bytes] = {}
    parsed: dict[str, dict] = {}
    sources: dict[str, dict] = {}
    doc_types = {"po": "PO", "grn": "GRN", "inv": "INVOICE"}
    for slot, file in uploads.items():
        raw[slot] = await file.read()
        sources[slot] = source_meta(raw[slot], file.filename or slot)
        parsed[slot] = parse_document(raw[slot], file.filename or slot, doc_types[slot])
    return sources, parsed, raw


def _tolerance_dict(price: float, qty: float, total: float) -> dict[str, float]:
    return {
        "price_tolerance": price,
        "qty_tolerance": qty,
        "total_tolerance": total,
    }


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
):
    try:
        sources, parsed, _ = await _read_and_parse(
            {"po": po_file, "grn": grn_file, "inv": invoice_file}
        )
    except ParseError as e:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": str(e)},
            status_code=400,
        )

    parameters = _tolerance_dict(price_tolerance, qty_tolerance, total_tolerance)
    report = three_way_match(
        parsed["po"], parsed["grn"], parsed["inv"],
        price_tolerance=price_tolerance,
        qty_tolerance=qty_tolerance,
        total_tolerance=total_tolerance,
    ).to_dict()

    workpaper = build_workpaper(
        sources=sources, parsed=parsed, report=report, parameters=parameters
    )

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "report": report,
            "filenames": {
                "po": po_file.filename,
                "grn": grn_file.filename,
                "invoice": invoice_file.filename,
            },
            "workpaper_json": json.dumps(workpaper, indent=2, ensure_ascii=False),
            "workpaper_filename": workpaper_filename(report),
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
):
    try:
        _, parsed, _ = await _read_and_parse(
            {"po": po_file, "grn": grn_file, "inv": invoice_file}
        )
    except ParseError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    return three_way_match(
        parsed["po"], parsed["grn"], parsed["inv"],
        price_tolerance=price_tolerance,
        qty_tolerance=qty_tolerance,
        total_tolerance=total_tolerance,
    ).to_dict()


@app.post("/workpaper")
async def workpaper_endpoint(
    po_file: UploadFile = File(...),
    grn_file: UploadFile = File(...),
    invoice_file: UploadFile = File(...),
    price_tolerance: float = Form(0.01),
    qty_tolerance: float = Form(0.0),
    total_tolerance: float = Form(0.05),
):
    """Return a downloadable JSON audit workpaper for the same three files.

    Suitable as the primary evidence file for an audit trail — records the
    SHA-256 of each source file, the tolerances used, and the full match
    outcome in a single reproducible document.
    """
    try:
        sources, parsed, _ = await _read_and_parse(
            {"po": po_file, "grn": grn_file, "inv": invoice_file}
        )
    except ParseError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    parameters = _tolerance_dict(price_tolerance, qty_tolerance, total_tolerance)
    report = three_way_match(
        parsed["po"], parsed["grn"], parsed["inv"],
        price_tolerance=price_tolerance,
        qty_tolerance=qty_tolerance,
        total_tolerance=total_tolerance,
    ).to_dict()

    workpaper = build_workpaper(
        sources=sources, parsed=parsed, report=report, parameters=parameters
    )
    filename = workpaper_filename(report)
    body = json.dumps(workpaper, indent=2, ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/sample/{name}")
async def sample(name: str):
    path = SAMPLE_DIR / name
    if not path.exists() or not path.is_file() or path.parent != SAMPLE_DIR:
        return JSONResponse({"error": "Voorbeeldbestand niet gevonden."}, status_code=404)
    media = "application/json" if name.endswith(".json") else "text/csv"
    return HTMLResponse(path.read_text(encoding="utf-8"), media_type=media)
