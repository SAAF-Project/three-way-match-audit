"""FastAPI application for the Three-way Match webapp."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.i18n import available as available_langs, default_lang, get_lang
from app.services.matcher import three_way_match
from app.services.parsers import ParseError, parse_document

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
SAMPLE_DIR = BASE_DIR.parent / "sample_data"

LANG_COOKIE = "lang"
LANG_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # one year

app = FastAPI(title="Three-way Match Audit", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def _lang_from(request: Request) -> str:
    """Return the active language code. Cookie wins, then Accept-Language,
    then the default. Unknown codes fall back to the default."""
    cookie = request.cookies.get(LANG_COOKIE, "").lower()
    if cookie in available_langs():
        return cookie
    accept = request.headers.get("accept-language", "")
    for part in accept.split(","):
        code = part.split(";")[0].strip().split("-")[0].lower()
        if code in available_langs():
            return code
    return default_lang()


def _ctx(request: Request, **extra) -> dict:
    """Base template context — always carries the i18n dict and lang code."""
    lang = _lang_from(request)
    languages = [{"code": c, "label": get_lang(c)["lang_label"]} for c in available_langs()]
    return {"request": request, "lang": lang, "t": get_lang(lang),
            "languages": languages, **extra}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", _ctx(request))


@app.get("/lang/{code}")
async def set_lang(code: str, request: Request, next: str = "/"):
    """Persist the language choice in a cookie and bounce back where the
    user came from. Rejects unknown codes and keeps `next` relative so an
    attacker-controlled URL can't be used as an open redirect."""
    if code not in available_langs():
        return JSONResponse({"error": "Unknown language."}, status_code=400)
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    resp = RedirectResponse(target, status_code=303)
    resp.set_cookie(
        LANG_COOKIE, code,
        max_age=LANG_COOKIE_MAX_AGE,
        httponly=False, samesite="lax",
    )
    return resp


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
            _ctx(request, error=str(e)),
            status_code=400,
        )

    lang_dict = get_lang(_lang_from(request))
    report = three_way_match(
        po, grn, inv,
        price_tolerance=price_tolerance,
        qty_tolerance=qty_tolerance,
        total_tolerance=total_tolerance,
        line_total_tolerance=line_total_tolerance,
        messages=lang_dict.get("msg"),
    )

    return templates.TemplateResponse(
        "result.html",
        _ctx(request,
             report=report.to_dict(),
             filenames={
                "po": po_file.filename,
                "grn": grn_file.filename,
                "invoice": invoice_file.filename,
            }),
    )


@app.post("/api/match")
async def match_api(
    request: Request,
    po_file: UploadFile = File(...),
    grn_file: UploadFile = File(...),
    invoice_file: UploadFile = File(...),
    price_tolerance: float = Form(0.01),
    qty_tolerance: float = Form(0.0),
    total_tolerance: float = Form(0.05),
    line_total_tolerance: float = Form(0.01),
    lang: str = Form(None),
):
    try:
        po = parse_document(await po_file.read(), po_file.filename or "po", "PO")
        grn = parse_document(await grn_file.read(), grn_file.filename or "grn", "GRN")
        inv = parse_document(await invoice_file.read(), invoice_file.filename or "invoice", "INVOICE")
    except ParseError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    lang_code = lang if lang in available_langs() else _lang_from(request)
    report = three_way_match(
        po, grn, inv,
        price_tolerance=price_tolerance,
        qty_tolerance=qty_tolerance,
        total_tolerance=total_tolerance,
        line_total_tolerance=line_total_tolerance,
        messages=get_lang(lang_code).get("msg"),
    )
    return report.to_dict()


@app.get("/sample/{name}")
async def sample(name: str):
    path = SAMPLE_DIR / name
    if not path.exists() or not path.is_file() or path.parent != SAMPLE_DIR:
        return JSONResponse({"error": "Voorbeeldbestand niet gevonden."}, status_code=404)
    media = "application/json" if name.endswith(".json") else "text/csv"
    return HTMLResponse(path.read_text(encoding="utf-8"), media_type=media)
