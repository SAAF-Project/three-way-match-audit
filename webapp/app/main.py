"""FastAPI application for the Three-way Match webapp."""
from __future__ import annotations

import base64
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.i18n import available as available_langs, default_lang, get_lang
from app.services.agent import ai_enabled, run_audit_agent
from app.services.audit_log import build as build_audit_log, to_json as audit_log_json
from app.security import (
    MAX_UPLOAD_BYTES,
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
    is_https,
)
from app.services.matcher import MAX_TOLERANCE, three_way_match, validate_tolerance
from app.services.parsers import ParseError, parse_document

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
SAMPLE_DIR = (BASE_DIR.parent / "sample_data").resolve()

LANG_COOKIE = "lang"
LANG_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # one year

THEME_COOKIE = "theme"  # written client-side by static/theme.js
THEMES = ("light", "dark")

# MIME types a browser or HTTP client may send for a .csv or .json upload.
# Windows labels CSV files as application/vnd.ms-excel; a re-posted File()
# without a type arrives as application/octet-stream. The type is only a
# claim: parsers.parse_document() also checks the bytes themselves.
ALLOWED_UPLOAD_TYPES = frozenset({
    "", "text/csv", "application/csv", "text/comma-separated-values",
    "application/vnd.ms-excel", "text/plain", "application/json", "text/json",
    "application/octet-stream",
})

MAX_FILENAME_LENGTH = 255

app = FastAPI(title="Three-way Match Audit", version="0.2.0",
              docs_url=None, redoc_url=None, openapi_url=None)
# The last one added runs first: headers wrap everything, including a 413.
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


class UploadRejected(Exception):
    """An upload or form value failed validation; the message is shown to the user."""


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
    theme = request.cookies.get(THEME_COOKIE)
    return {"request": request, "lang": lang, "t": get_lang(lang),
            "languages": languages, "theme": theme if theme in THEMES else None,
            "ai_enabled": ai_enabled(), **extra}


def _safe_filename(upload: UploadFile, fallback: str) -> str:
    """The client-supplied name, reduced to its last path part and a sane
    length. It is only displayed (escaped) and used for the extension."""
    name = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = "".join(c for c in name if c.isprintable())
    return name[-MAX_FILENAME_LENGTH:] or fallback


async def _read_upload(upload: UploadFile, fallback: str, t: dict) -> tuple[bytes, str]:
    name = _safe_filename(upload, fallback)
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_UPLOAD_TYPES:
        raise UploadRejected(t["ui"]["error_file_type"].format(name=name, type=content_type))
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected(t["ui"]["error_too_large"].format(
            name=name, max_mb=f"{MAX_UPLOAD_BYTES / 1024 / 1024:g}"))
    return data, name


def _tolerances(t: dict, **raw: str) -> dict[str, float]:
    try:
        return {name: validate_tolerance(name, value) for name, value in raw.items()}
    except ValueError:
        raise UploadRejected(t["ui"]["error_tolerance"].format(max=f"{MAX_TOLERANCE:g}"))


async def _run_match(request: Request, lang_code: str, files: dict[str, UploadFile],
                     tolerance_form: dict[str, str]):
    """Validate the request, parse the three documents and match them.
    Raises UploadRejected or ParseError with a message for the user."""
    t = get_lang(lang_code)
    tolerances = _tolerances(t, **tolerance_form)
    uploads = {}
    for doc_type, (field, upload) in zip(("PO", "GRN", "INVOICE"), files.items()):
        data, name = await _read_upload(upload, field, t)
        uploads[doc_type] = (field, data, name)
    docs = {doc_type: parse_document(data, name, doc_type)
            for doc_type, (_, data, name) in uploads.items()}
    report = three_way_match(docs["PO"], docs["GRN"], docs["INVOICE"],
                             messages=t.get("msg"), **tolerances)
    return report, uploads, tolerances, docs


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", _ctx(request))


@app.get("/lang/{code}")
async def set_lang(code: str, request: Request, next: str = "/"):
    """Persist the language choice in a cookie and bounce back where the
    user came from. Rejects unknown codes and keeps `next` a local path so an
    attacker-controlled URL can't be used as an open redirect."""
    if code not in available_langs():
        return JSONResponse({"error": "Unknown language."}, status_code=400)
    local = (next.startswith("/") and not next.startswith("//")
             and "\\" not in next and all(c.isprintable() for c in next))
    resp = RedirectResponse(next if local else "/", status_code=303)
    resp.set_cookie(
        LANG_COOKIE, code,
        max_age=LANG_COOKIE_MAX_AGE, path="/",
        # Not HttpOnly: static/result_lang.js sets it too. It holds only a
        # language code, which the server validates on every read.
        httponly=False, samesite="lax", secure=is_https(request),
    )
    return resp


@app.get("/match")
async def match_get():
    """Results only exist as the response to a POST; a GET (refresh of the
    URL, language switch without JavaScript) starts over at the upload page."""
    return RedirectResponse("/", status_code=303)


@app.post("/match", response_class=HTMLResponse)
async def match(
    request: Request,
    po_file: UploadFile = File(...),
    grn_file: UploadFile = File(...),
    invoice_file: UploadFile = File(...),
    price_tolerance: str = Form("0.01"),
    qty_tolerance: str = Form("0"),
    total_tolerance: str = Form("0.05"),
    line_total_tolerance: str = Form("0.01"),
):
    lang_code = _lang_from(request)
    try:
        report, uploads, tolerances, _ = await _run_match(
            request, lang_code,
            {"po_file": po_file, "grn_file": grn_file, "invoice_file": invoice_file},
            {"price_tolerance": price_tolerance, "qty_tolerance": qty_tolerance,
             "total_tolerance": total_tolerance, "line_total_tolerance": line_total_tolerance},
        )
    except (UploadRejected, ParseError) as e:
        return templates.TemplateResponse(
            request, "index.html", _ctx(request, error=str(e)), status_code=400,
        )

    return templates.TemplateResponse(
        request,
        "result.html",
        _ctx(request,
             report=report.to_dict(),
             filenames={"po": uploads["PO"][2], "grn": uploads["GRN"][2],
                        "invoice": uploads["INVOICE"][2]},
             # Sent back by static/result_lang.js to re-run the match in
             # another language; nothing is kept on the server.
             rerun_files=[
                 {"field": field, "filename": name,
                  "content": base64.b64encode(data).decode("ascii")}
                 for field, data, name in uploads.values()
             ],
             rerun_tolerances=tolerances),
    )


@app.post("/api/match")
async def match_api(
    request: Request,
    po_file: UploadFile = File(...),
    grn_file: UploadFile = File(...),
    invoice_file: UploadFile = File(...),
    price_tolerance: str = Form("0.01"),
    qty_tolerance: str = Form("0"),
    total_tolerance: str = Form("0.05"),
    line_total_tolerance: str = Form("0.01"),
    lang: str = Form(None),
):
    lang_code = lang if lang in available_langs() else _lang_from(request)
    try:
        report, _, _, _ = await _run_match(
            request, lang_code,
            {"po_file": po_file, "grn_file": grn_file, "invoice_file": invoice_file},
            {"price_tolerance": price_tolerance, "qty_tolerance": qty_tolerance,
             "total_tolerance": total_tolerance, "line_total_tolerance": line_total_tolerance},
        )
    except (UploadRejected, ParseError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse(report.to_dict())


async def _explain(request: Request, lang_code: str, files: dict[str, UploadFile],
                   tolerance_form: dict[str, str]) -> dict:
    """Rule-based match plus the advisory AI review (services/agent.py).

    Run 1 is the same Python match as /match and stays authoritative. The
    parsed documents are sent to the AI provider only when ai_enabled();
    the result and the audit trail always say whether that happened.
    """
    _, uploads, tolerances, docs = await _run_match(request, lang_code, files, tolerance_form)
    agent_result = run_audit_agent(
        docs["PO"], docs["GRN"], docs["INVOICE"],
        tolerances["price_tolerance"], tolerances["qty_tolerance"], tolerances["total_tolerance"],
        line_total_tolerance=tolerances["line_total_tolerance"],
        messages=get_lang(lang_code).get("msg"),
    )
    log = build_audit_log(
        po_bytes=uploads["PO"][1], grn_bytes=uploads["GRN"][1], invoice_bytes=uploads["INVOICE"][1],
        po_filename=uploads["PO"][2], grn_filename=uploads["GRN"][2],
        invoice_filename=uploads["INVOICE"][2],
        price_tolerance=tolerances["price_tolerance"],
        qty_tolerance=tolerances["qty_tolerance"],
        total_tolerance=tolerances["total_tolerance"],
        line_total_tolerance=tolerances["line_total_tolerance"],
        match_report=agent_result["report"],
        audit_narrative=agent_result["narrative"],
        tool_calls=agent_result["tool_calls"],
        ai=agent_result,
    )
    return {"agent": agent_result, "log": log, "uploads": uploads, "tolerances": tolerances}


@app.post("/match/explain", response_class=HTMLResponse)
async def match_explain(
    request: Request,
    po_file: UploadFile = File(...),
    grn_file: UploadFile = File(...),
    invoice_file: UploadFile = File(...),
    price_tolerance: str = Form("0.01"),
    qty_tolerance: str = Form("0"),
    total_tolerance: str = Form("0.05"),
    line_total_tolerance: str = Form("0.01"),
):
    lang_code = _lang_from(request)
    try:
        out = await _explain(
            request, lang_code,
            {"po_file": po_file, "grn_file": grn_file, "invoice_file": invoice_file},
            {"price_tolerance": price_tolerance, "qty_tolerance": qty_tolerance,
             "total_tolerance": total_tolerance, "line_total_tolerance": line_total_tolerance},
        )
    except (UploadRejected, ParseError) as e:
        return templates.TemplateResponse(
            request, "index.html", _ctx(request, error=str(e)), status_code=400,
        )

    agent_result, uploads, tolerances = out["agent"], out["uploads"], out["tolerances"]
    return templates.TemplateResponse(
        request,
        "result.html",
        _ctx(request,
             report=agent_result["report"],
             ai_report=agent_result["ai_report"],
             narrative=agent_result["narrative"],
             ai=agent_result,
             user_tolerances=tolerances,
             audit_log_json=audit_log_json(out["log"]),
             filenames={"po": uploads["PO"][2], "grn": uploads["GRN"][2],
                        "invoice": uploads["INVOICE"][2]},
             rerun_action="/match/explain",
             rerun_files=[
                 {"field": field, "filename": name,
                  "content": base64.b64encode(data).decode("ascii")}
                 for field, data, name in uploads.values()
             ],
             rerun_tolerances=tolerances),
    )


@app.post("/api/match/explain")
async def match_explain_api(
    request: Request,
    po_file: UploadFile = File(...),
    grn_file: UploadFile = File(...),
    invoice_file: UploadFile = File(...),
    price_tolerance: str = Form("0.01"),
    qty_tolerance: str = Form("0"),
    total_tolerance: str = Form("0.05"),
    line_total_tolerance: str = Form("0.01"),
    lang: str = Form(None),
):
    lang_code = lang if lang in available_langs() else _lang_from(request)
    try:
        out = await _explain(
            request, lang_code,
            {"po_file": po_file, "grn_file": grn_file, "invoice_file": invoice_file},
            {"price_tolerance": price_tolerance, "qty_tolerance": qty_tolerance,
             "total_tolerance": total_tolerance, "line_total_tolerance": line_total_tolerance},
        )
    except (UploadRejected, ParseError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse(out["log"])  # ai_report is inside ai_tool_calls[1]


@app.get("/sample/{name}")
async def sample(name: str):
    """Serve one of the bundled sample files, and nothing else."""
    allowed = {p.name: p for p in SAMPLE_DIR.iterdir()
               if p.is_file() and p.suffix in (".csv", ".json")}
    path = allowed.get(name)
    if path is None or not path.resolve().is_relative_to(SAMPLE_DIR):
        return JSONResponse({"error": "Voorbeeldbestand niet gevonden."}, status_code=404)
    media = "application/json" if path.suffix == ".json" else "text/csv"
    return Response(path.read_bytes(), media_type=f"{media}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{path.name}"'})
