"""Minimal i18n loader for the 3-way match webapp.

Translations live in JSON files alongside this module — one file per
language, same schema. The loader caches the parsed JSON per process so
each request is a dict lookup, not a file read.

Public API:
    get_lang(code)   -> parsed translation dict for the language code
    available()      -> list of language codes present on disk
    default_lang()   -> fallback code ("nl")
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

I18N_DIR = Path(__file__).resolve().parent
DEFAULT_LANG = "nl"


def available() -> list[str]:
    return sorted(p.stem for p in I18N_DIR.glob("*.json"))


def default_lang() -> str:
    return DEFAULT_LANG


@lru_cache(maxsize=8)
def get_lang(code: str) -> dict:
    code = (code or "").strip().lower()
    if code not in available():
        code = DEFAULT_LANG
    with (I18N_DIR / f"{code}.json").open(encoding="utf-8") as f:
        return json.load(f)
