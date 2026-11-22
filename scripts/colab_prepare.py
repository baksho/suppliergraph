"""Find the source files anywhere under a (Google Drive) folder and stage them where config/sources.yaml expects them.

    python scripts/colab_prepare.py --drive /content/drive/MyDrive [--root .]

Looks for (case-insensitive, first match wins):
  GLEIF level 1   *lei2*golden*copy*.zip | *lei2*.csv      (name taken from the files you uploaded; verify with `sg data check`)
  GLEIF level 2   *-rr-*golden*copy*.zip | *rr-golden*.csv
  OCDS bulk       full.jsonl.gz (or any *.jsonl.gz / *.jsonl)        <- the registry's JSONL download
  CPV             *cpv_2008*.zip | *cpv*2008*.xlsx
  Sanctions       targets.simple.csv | targets_simple.csv
  Regulation      *CELEX*.pdf (any number of them)
Prints a report and exits non-zero if a required source is missing.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys
import zipfile
from pathlib import Path

import pandas as pd

from suppliergraph.extract.pdf_text import pdf_to_text


def walk(root: Path):
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            yield Path(dp) / f


def find(files: list[Path], *patterns: str, exclude: tuple[str, ...] = ()) -> list[Path]:
    hits = [f for f in files if any(fnmatch.fnmatch(f.name.lower(), p.lower()) for p in patterns)
            and not any(fnmatch.fnmatch(f.name.lower(), e.lower()) for e in exclude)]
    return sorted(hits, key=lambda p: -p.stat().st_size)


def unzip_single_csv(zpath: Path, dest: Path) -> Path:
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise RuntimeError(f"{zpath.name}: expected exactly one CSV, found {names}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with z.open(names[0]) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out, 1 << 22)
    return dest


def stage(drive: Path, root: Path) -> dict:
    files = list(walk(drive))
    raw = root / "data" / "raw"
    rep: dict = {}

    rep["gleif_level1"] = _one(find(files, "*lei2*golden*copy*.zip", "*lei2*.csv"), lambda p: (
        unzip_single_csv(p, raw / "gleif" / "level1.csv") if p.suffix == ".zip" else _copy(p, raw / "gleif" / "level1.csv")))
    rep["gleif_level2"] = _one(find(files, "*-rr-*golden*copy*.zip", "*rr*golden*copy*.zip", "*rr-golden*.csv"), lambda p: (
        unzip_single_csv(p, raw / "gleif" / "level2.csv") if p.suffix == ".zip" else _copy(p, raw / "gleif" / "level2.csv")))
    rep["ocds"] = _one(find(files, "full.jsonl.gz", "*.jsonl.gz", "*.jsonl"), lambda p: _copy(p, raw / "ocds" / p.name))
    if not rep["ocds"]["found"]:
        csvs = find(files, "*full.csv.tar.gz", "*.csv.tar.gz")
        rep["ocds"]["hint"] = (f"Found {csvs[0].name} (the CSV export) but the loader reads the JSON export. Download "
                               "`full.jsonl.gz` from the same page (data.open-contracting.org/en/publication/136) into your Drive."
                               if csvs else "No OCDS file found.")
    rep["sanctions"] = _one(find(files, "targets.simple*.csv", "targets_simple*.csv"), lambda p: _copy(p, raw / "sanctions" / "targets.simple.csv"))
    rep["cpv"] = _one(find(files, "*cpv*2008*.zip", "*cpv*2008*.xlsx"), lambda p: _stage_cpv(p, raw / "cpv" / "cpv.csv"))
    regs = find(files, "*celex*.pdf")
    rep["regulations"] = {"found": [p.name for p in regs]}
    for p in regs:
        name = "dir_2014_24_de.txt" if "32014l0024" in p.name.lower() else p.stem[-40:] + ".txt"   # name registered in config/regulations.yaml
        pdf_to_text(p, raw / "regulation" / name)
    rep["regulations"]["note"] = "register each text in config/regulations.yaml"
    return rep


def _copy(p: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(p, dest)
    return dest


def _stage_cpv(p: Path, dest: Path) -> Path:
    xlsx = p
    if p.suffix == ".zip":
        with zipfile.ZipFile(p) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".xlsx")]
            if not names:
                raise RuntimeError(f"{p.name}: no .xlsx inside")
            xlsx = dest.parent / Path(names[0]).name
            xlsx.parent.mkdir(parents=True, exist_ok=True)
            with z.open(names[0]) as src, open(xlsx, "wb") as out:
                shutil.copyfileobj(src, out)
    df = pd.read_excel(xlsx, sheet_name="CPV codes", dtype=str)
    df[["CODE", "EN", "DE"]].to_csv(dest, index=False)
    return dest


def _one(hits: list[Path], action) -> dict:
    if not hits:
        return {"found": None}
    out = action(hits[0])
    return {"found": str(hits[0]), "staged": str(out), "size_mb": round(Path(out).stat().st_size / 1e6, 1),
            "other_candidates": [h.name for h in hits[1:4]]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", required=True)
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    rep = stage(Path(a.drive), Path(a.root))
    import json
    print(json.dumps(rep, indent=2))
    missing = [k for k in ("gleif_level1", "gleif_level2", "ocds", "sanctions", "cpv") if not rep[k].get("found")]
    if missing:
        print("\nMISSING:", ", ".join(missing), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
