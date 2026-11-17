"""Data-quality validation of parsed documents with pandera.

Runs after parsing and before the three-way match. A document that fails
any rule is rejected with a ParseError, so the matcher never sees data
that could slip past its checks. The rules are declared as pandera
schemas so they can be read and reviewed as audit evidence.

Covered (see GitHub issues):
  #16  blank / NaN / infinite quantity or unit price
  #17  quantity x unit price != line total; one SKU with several prices
  #19  empty header fields; conflicting header values in a flat CSV
  #21  spreadsheet formula injection (=, +, -, @, tab, CR at cell start)
  plus: ambiguous columns (two aliases for the same field, e.g. both
        `quantity` and `quantity_billed`), see sample_data/invoice_evasion.csv
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaErrors

# Rounding slack for quantity x unit price vs. line total. This is not the
# user-facing tolerance: a document must be internally consistent.
ARITHMETIC_TOLERANCE = 0.01
# Upper bound against absurd or overflow-like values.
MAX_AMOUNT = 1e12
# Cells starting with these characters are run as formulas by Excel and
# LibreOffice (OWASP "CSV injection").
FORMULA_PATTERN = r"^[=+\-@\t\r]"
MAX_REPORTED_ERRORS = 10

# Field -> accepted column aliases. Must match parsers._LINE_*_KEYS.
LINE_ALIASES: dict[str, tuple[str, ...]] = {
    "quantity": ("quantity", "qty", "quantity_received", "quantity_billed"),
    "unit_price": ("unit_price", "price", "unitprice"),
    "line_total": ("line_total", "total", "amount", "line_amount"),
    "sku": ("sku", "item", "item_code", "article", "material"),
    "description": ("description", "desc", "text", "item_description"),
}
HEADER_COLUMNS_IN_LINES = ("document_number", "po_number", "supplier")


class ValidationFailed(ValueError):
    """Raised with a list of human-readable (Dutch) validation messages."""

    def __init__(self, messages: list[str]):
        self.messages = messages
        super().__init__("; ".join(messages))


# ---------------------------------------------------------------------------
# Reusable checks
# ---------------------------------------------------------------------------
def _no_formula() -> pa.Check:
    return pa.Check(
        lambda s: ~s.fillna("").astype(str).str.match(FORMULA_PATTERN),
        element_wise=False,
        error="begint met =, +, -, @ of een tab (mogelijke formule-injectie)",
    )


def _finite_amount() -> list[pa.Check]:
    # in_range rejects +/-inf (and 1e309, which parses to inf) as well.
    return [pa.Check.in_range(0, MAX_AMOUNT, error="moet een eindig getal tussen 0 en 10^12 zijn")]


def _not_empty() -> pa.Check:
    return pa.Check(lambda s: s.fillna("").astype(str).str.strip() != "",
                    error="is leeg")


def _line_arithmetic(df: pd.DataFrame) -> pd.Series:
    complete = df[["quantity", "unit_price", "line_total"]].notna().all(axis=1)
    diff = (df["quantity"] * df["unit_price"] - df["line_total"]).abs()
    return ~complete | (diff <= ARITHMETIC_TOLERANCE)


def _one_price_per_sku(df: pd.DataFrame) -> pd.Series:
    with_sku = df["sku"].fillna("").str.strip().str.upper()
    prices = df.assign(_k=with_sku)[with_sku != ""].groupby("_k")["unit_price"].nunique()
    conflicting = set(prices[prices > 1].index)
    return ~with_sku.isin(conflicting)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
def _lines_schema(doc_type: str) -> pa.DataFrameSchema:
    priced = doc_type in ("PO", "INVOICE")
    return pa.DataFrameSchema(
        {
            "sku": pa.Column(str, [_no_formula()], nullable=True),
            "description": pa.Column(str, [_no_formula()], nullable=True),
            "quantity": pa.Column(float, _finite_amount(), nullable=False),
            "unit_price": pa.Column(float, _finite_amount(), nullable=not priced),
            "line_total": pa.Column(float, _finite_amount(), nullable=True),
        },
        checks=[
            pa.Check(_line_arithmetic,
                     error="aantal x stukprijs komt niet overeen met regeltotaal"),
            pa.Check(_one_price_per_sku,
                     error="zelfde SKU komt voor met verschillende stukprijzen"),
        ] if priced else [],
        coerce=True,
    )


_HEADER_SCHEMA = pa.DataFrameSchema(
    {
        "document_number": pa.Column(str, [_not_empty(), _no_formula()]),
        "po_number": pa.Column(str, [_not_empty(), _no_formula()]),
        "supplier": pa.Column(str, [_not_empty(), _no_formula()]),
    },
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def validate_document(raw: dict[str, Any], doc: dict[str, Any], doc_type: str) -> None:
    """Validate the raw parser output and the normalised document.

    Raises ValidationFailed with up to MAX_REPORTED_ERRORS messages.
    """
    errors: list[str] = []
    raw_lines = raw.get("lines") or raw.get("items") or []
    if isinstance(raw_lines, list) and raw_lines and all(isinstance(r, dict) for r in raw_lines):
        errors += _check_raw_lines(pd.DataFrame(raw_lines))

    if not doc["lines"]:
        errors.append("Document bevat geen regels.")
    else:
        lines = pd.DataFrame(doc["lines"])
        errors += _run(_lines_schema(doc_type), lines, row_offset=1, prefix="Regel")

    header_values = {k: doc.get(k, "") for k in ("document_number", "po_number", "supplier")}
    if doc_type in ("GRN", "INVOICE"):
        # The parser falls back to the document's own number when po_number
        # is missing; a GRN or invoice must carry an explicit PO reference.
        header_values["po_number"] = str(raw.get("po_number") or "").strip()
    header = pd.DataFrame([header_values])
    errors += _run(_HEADER_SCHEMA, header, prefix="Kop")

    if errors:
        extra = len(errors) - MAX_REPORTED_ERRORS
        msgs = errors[:MAX_REPORTED_ERRORS]
        if extra > 0:
            msgs.append(f"... en nog {extra} andere fout(en).")
        raise ValidationFailed(msgs)


def _check_raw_lines(df: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    filled = df.apply(lambda s: s.notna() & (s.astype(str).str.strip() != ""))

    # Two aliases for one field on the same row: the parser would silently
    # pick one, so a crafted file could show the matcher other numbers than
    # a human reads.
    for field, aliases in LINE_ALIASES.items():
        present = [a for a in aliases if a in df.columns]
        if len(present) > 1 and (filled[present].sum(axis=1) > 1).any():
            errors.append(
                f"Dubbelzinnige kolommen voor '{field}': {', '.join(present)}. "
                "Gebruik er één."
            )

    # Header fields repeated per line (flat CSV) must agree on every row.
    for col in HEADER_COLUMNS_IN_LINES:
        if col in df.columns:
            values = df.loc[filled[col], col].astype(str).str.strip()
            if values.nunique() > 1:
                errors.append(
                    f"Kolom '{col}' heeft verschillende waarden per regel: "
                    f"{', '.join(sorted(values.unique())[:5])}."
                )
    return errors


def _run(schema: pa.DataFrameSchema, df: pd.DataFrame, *, prefix: str,
         row_offset: int | None = None) -> list[str]:
    try:
        schema.validate(df, lazy=True)
        return []
    except SchemaErrors as exc:
        cases = exc.failure_cases.copy()
        cases["row"] = pd.to_numeric(cases["index"], errors="coerce")
        out: list[str] = []
        for case in cases.sort_values("row", na_position="first").itertuples(index=False):
            where = prefix
            if row_offset is not None and pd.notna(case.row):
                where = f"{prefix} {int(case.row) + row_offset}"
            msg = _message(case.check)
            if case.schema_context == "Column":
                # Column check: name the column and the offending value.
                value = "" if pd.isna(case.failure_case) else f" (waarde: {case.failure_case})"
                out.append(f"{where} '{case.column}': {msg}{value}")
            elif case.check == "column_in_dataframe":
                out.append(f"{where}: kolom '{case.failure_case}' ontbreekt")
            else:
                # Row-wide check: pandera reports one case per cell, keep one per row.
                out.append(f"{where}: {msg}")
        return list(dict.fromkeys(out))


def _message(check: Any) -> str:
    text = str(check)
    if text == "not_nullable":
        return "ontbreekt of is geen geldig getal"
    if text.startswith(("coerce_dtype", "dtype")):
        return "heeft een ongeldig type"
    return text
