"""Usage: python scripts/prepare_regulation.py in.pdf out.txt"""
import sys
from pathlib import Path

from suppliergraph.extract.pdf_text import pdf_to_text

pdf_to_text(Path(sys.argv[1]), Path(sys.argv[2]))
