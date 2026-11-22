from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from ..config import get_settings

COUNTRY_NAMES = {
    "austria": "AT", "österreich": "AT", "belgium": "BE", "belgien": "BE", "bulgaria": "BG",
    "bulgarien": "BG", "croatia": "HR", "kroatien": "HR", "cyprus": "CY", "zypern": "CY",
    "czechia": "CZ", "czech republic": "CZ", "tschechien": "CZ", "denmark": "DK", "dänemark": "DK",
    "estonia": "EE", "estland": "EE", "finland": "FI", "finnland": "FI", "france": "FR",
    "frankreich": "FR", "germany": "DE", "deutschland": "DE", "greece": "GR", "griechenland": "GR",
    "hungary": "HU", "ungarn": "HU", "ireland": "IE", "irland": "IE", "italy": "IT", "italien": "IT",
    "latvia": "LV", "lettland": "LV", "lithuania": "LT", "litauen": "LT", "luxembourg": "LU",
    "luxemburg": "LU", "malta": "MT", "netherlands": "NL", "niederlande": "NL", "poland": "PL",
    "polen": "PL", "portugal": "PT", "romania": "RO", "rumänien": "RO", "slovakia": "SK",
    "slowakei": "SK", "slovenia": "SI", "slowenien": "SI", "spain": "ES", "spanien": "ES",
    "sweden": "SE", "schweden": "SE", "switzerland": "CH", "schweiz": "CH",
    "united kingdom": "GB", "vereinigtes königreich": "GB", "norway": "NO", "norwegen": "NO",
    "united states": "US", "usa": "US", "turkey": "TR", "türkei": "TR", "china": "CN",
}


def norm_country(value: Any) -> str | None:
    """Map a country name or code to an upper-case ISO 3166-1 alpha-2 code (None if unknown)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    if len(s) == 2 and s.isalpha():
        return s.upper()
    return COUNTRY_NAMES.get(s.lower())


def stable_id(*parts: Any, prefix: str = "P-", length: int = 16) -> str:
    h = hashlib.sha1("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()
    return f"{prefix}{h[:length]}"


_LEI_RE = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")


def lei_valid(lei: str) -> bool:
    """ISO 17442 format plus ISO 7064 MOD 97-10 check."""
    if not lei or not _LEI_RE.match(lei):
        return False
    digits = "".join(str(int(c, 36)) for c in lei)
    return int(digits) % 97 == 1


def make_lei(base18: str) -> str:
    """Compute the two check digits for an 18 character base (used for test fixtures only)."""
    digits = "".join(str(int(c, 36)) for c in base18.upper()) + "00"
    check = 98 - (int(digits) % 97)
    return f"{base18.upper()}{check:02d}"


def load_sources(path: Path | None = None) -> dict:
    path = path or get_settings().sources_config
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def resolve_path(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else get_settings().root / p
