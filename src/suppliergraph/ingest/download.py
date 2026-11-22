"""Download raw files from URLs configured in config/sources.yaml (all null by default).

URLs are deliberately NOT hard-coded: they could not be verified when the repository was generated.
Fill them in after checking each publisher's landing page and licence.
"""
from __future__ import annotations

import shutil
import urllib.request
import zipfile
from pathlib import Path

from .common import load_sources, resolve_path

TARGETS = {  # source -> (url key, path key, section)
    "gleif1": ("level1_url", "level1_path", "gleif"), "gleif2": ("level2_url", "level2_path", "gleif"),
    "cpv": ("url", "path", "cpv"), "sanctions": ("url", "path", "sanctions"),
}


def download(source: str) -> Path:
    if source not in TARGETS:
        raise ValueError(f"source must be one of {sorted(TARGETS)}")
    ukey, pkey, sec = TARGETS[source]
    cfg = load_sources()[sec]
    url, dest = cfg.get(ukey), resolve_path(cfg[pkey])
    if not url:
        raise RuntimeError(f"No URL configured for {source}: set {sec}.{ukey} in config/sources.yaml "
                           f"(check the publisher's landing page and licence first) or place the file at {dest}.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as fh:
        shutil.copyfileobj(r, fh)
    if zipfile.is_zipfile(tmp):
        with zipfile.ZipFile(tmp) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                raise RuntimeError(f"expected exactly one CSV in the archive, found {names}")
            with z.open(names[0]) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        tmp.unlink()
    else:
        tmp.replace(dest)
    return dest
