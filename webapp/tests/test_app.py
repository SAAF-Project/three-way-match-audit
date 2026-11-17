"""HTTP-level tests: upload limits, MIME types, headers, cookies, redirects."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security import MAX_UPLOAD_BYTES

client = TestClient(app)


def files(sample_bytes, **override):
    out = {
        "po_file": ("po.csv", sample_bytes["po"], "text/csv"),
        "grn_file": ("grn.csv", sample_bytes["grn"], "text/csv"),
        "invoice_file": ("invoice.csv", sample_bytes["inv"], "text/csv"),
    }
    out.update(override)
    return out


def test_api_match_returns_match(sample_bytes):
    r = client.post("/api/match", files=files(sample_bytes))
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "MATCH"
    assert r.headers["cache-control"] == "no-store"


def test_html_match_renders_result(sample_bytes):
    r = client.post("/match", files=files(sample_bytes))
    assert r.status_code == 200
    assert "Match" in r.text


def test_oversized_file_is_rejected(sample_bytes):
    big = sample_bytes["po"] + b"#" * (MAX_UPLOAD_BYTES + 10)
    r = client.post("/api/match", files=files(sample_bytes, po_file=("po.csv", big, "text/csv")))
    assert r.status_code in (400, 413)


def test_oversized_request_is_rejected_before_parsing():
    r = client.post("/api/match", content=b"x" * (4 * MAX_UPLOAD_BYTES),
                    headers={"content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 413
    assert "content-security-policy" in r.headers


def test_chunked_oversized_request_is_rejected():
    def body():  # a valid multipart start, then a file that never ends
        yield (b'--x\r\nContent-Disposition: form-data; name="po_file"; filename="po.csv"\r\n'
               b"Content-Type: text/csv\r\n\r\n")
        for _ in range(5):
            yield b"x" * MAX_UPLOAD_BYTES
    r = client.post("/api/match", content=body(),
                    headers={"content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 413


@pytest.mark.parametrize("ctype", [
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/html", "image/svg+xml", "application/x-msdownload",
])
def test_disallowed_mime_types_are_rejected(sample_bytes, ctype):
    r = client.post("/api/match", files=files(sample_bytes, po_file=("po.csv", sample_bytes["po"], ctype)))
    assert r.status_code == 400
    assert "error" in r.json()


def test_windows_csv_mime_type_is_accepted(sample_bytes):
    r = client.post("/api/match", files=files(
        sample_bytes, po_file=("po.csv", sample_bytes["po"], "application/vnd.ms-excel")))
    assert r.status_code == 200


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "1000", "abc"])
def test_bad_tolerances_are_rejected(sample_bytes, value):
    r = client.post("/api/match", files=files(sample_bytes), data={"total_tolerance": value})
    assert r.status_code == 400


def test_security_headers_on_pages():
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "'unsafe-inline'" not in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "strict-transport-security" not in r.headers  # plain HTTP here


def test_hsts_behind_https_proxy():
    r = client.get("/", headers={"x-forwarded-proto": "https"})
    assert "max-age" in r.headers["strict-transport-security"]


def test_pages_have_no_inline_script_or_style(sample_bytes):
    for page in (client.get("/").text, client.post("/match", files=files(sample_bytes)).text):
        assert "<script>" not in page
        assert "style=" not in page


def test_xss_in_document_fields_is_escaped(sample_bytes):
    evil = sample_bytes["inv"].replace(b"Widget A - roestvrij", b"<script>alert(1)</script>")
    r = client.post("/match", files=files(sample_bytes, invoice_file=("<img src=x onerror=alert(1)>.csv", evil, "text/csv")))
    assert "<script>alert(1)" not in r.text
    assert "<img src=x" not in r.text


def test_lang_cookie_is_secure_over_https():
    r = client.get("/lang/en?next=/", headers={"x-forwarded-proto": "https"}, follow_redirects=False)
    cookie = r.headers["set-cookie"].lower()
    assert "secure" in cookie and "samesite=lax" in cookie and "path=/" in cookie


@pytest.mark.parametrize("target", ["//evil.example", "/\\evil.example", "https://evil.example"])
def test_lang_redirect_stays_local(target):
    r = client.get(f"/lang/nl?next={target}", follow_redirects=False)
    assert r.headers["location"] == "/"


@pytest.mark.parametrize("name", ["../app/main.py", "..%2Fapp%2Fmain.py", "nope.csv", ".gitkeep"])
def test_sample_endpoint_serves_only_samples(name):
    assert client.get(f"/sample/{name}").status_code == 404


def test_sample_endpoint_serves_csv():
    r = client.get("/sample/po_sample.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")


def test_api_docs_are_disabled():
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
