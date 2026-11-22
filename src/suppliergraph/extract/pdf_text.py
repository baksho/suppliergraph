"""PDF -> plain text in reading order with soft hyphens removed (needs poppler's `pdftotext`)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def pdf_to_text(pdf: Path, out: Path) -> Path:
    raw = subprocess.run(["pdftotext", str(pdf), "-"], check=True, capture_output=True, text=True).stdout
    t = raw.replace("­\n", "").replace("­", "")          # soft hyphen: the word continues
    t = re.sub(r"(?<=[a-zäöüß])-\n(?=[a-zäöüß])", "-", t)           # real hyphen at a line end: keep it
    t = re.sub(r"[ \t]+\n", "\n", t)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(t, encoding="utf-8")
    return out
