import json
from pathlib import Path
from typing import Optional

from fastapi import Request

_translations: dict[str, dict[str, str]] = {}


def _load_translations():
    i18n_dir = Path(__file__).parent / "i18n"
    for f in i18n_dir.glob("*.json"):
        lang = f.stem
        with open(f, encoding="utf-8") as fh:
            _translations[lang] = json.load(fh)


def get_translator(request: Request) -> callable:
    if not _translations:
        _load_translations()
    lang = request.session.get("lang", "fr")
    if lang not in _translations:
        lang = "fr"
    tr = _translations[lang]

    def t(key: str, default: Optional[str] = None) -> str:
        return tr.get(key, default or key)

    return t
