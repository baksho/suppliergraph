"""Relation extraction: obligations in regulation text, with a verbatim-grounding check.

An LLM proposes (sentence, applies_to) pairs per article. We keep an obligation only if its
sentence occurs verbatim (whitespace-normalised) in the article text. That makes the extraction
auditable: every obligation in the graph points at a real sentence of a real article, and
hallucinated or paraphrased "obligations" are dropped before they can reach the graph.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from ..llm import LLM
from ..staging.db import replace_table

SYSTEM = (
    "You extract legal obligations from regulation text. Reply with JSON only. "
    "Never paraphrase: copy each obligation sentence exactly as it appears in the article."
)
PROMPT = """Article {article} of "{title}".

Text:
\"\"\"
{text}
\"\"\"

List only sentences that impose a binding duty on a contracting authority or an economic operator, i.e. sentences stating that someone must, shall, is required or is not allowed to do something.
Do NOT list definitions ("X means ..."), statements of scope, purpose or what a directive does not affect, permissions ("may", "can"), duties of Member States only, or fragments of a list that lack their own subject.
For each duty, give:
- "sentence": the sentence copied verbatim from the text
- "applies_to": "buyer" (contracting authority / purchaser), "supplier" (economic operator / company) or "both"

Reply as {{"obligations": [{{"sentence": "...", "applies_to": "buyer"}}]}}. If there is none, reply {{"obligations": []}}."""

PROMPT_VERSION = "obligations-v2"
ROLES = {"buyer", "supplier", "both"}
_ART = re.compile(r"^\s*(?:Article|Artikel|Art\.)\s+(\d+[a-z]?)\b\.?", re.IGNORECASE | re.MULTILINE)


_HEAD = re.compile(r"^[ \t]*(?:Article|Artikel)[ \t]+(\d+)([a-z]?)[ \t]*$", re.IGNORECASE | re.MULTILINE)
_ANNEX = re.compile(r"^[ \t]*(?:ANHANG|ANNEX)[ \t]+[IVX0-9]+[ \t]*$", re.MULTILINE)


def _article_chain(text: str):
    """Heading-only lines after the first 'Article 1': first occurrence per number, in text order.

    Heading-only (nothing else on the line) skips cross-references; ToC entries carry a colon and are skipped too.
    PDF reading order can swap neighbouring headings (8 before 7), so we do not require strict order.
    """
    marks = [(int(m.group(1)), m.group(2), m) for m in _HEAD.finditer(text)]
    start = next((i for i, (n, suf, _m) in enumerate(marks) if n == 1 and not suf), None)
    if start is None:
        return []
    seen, chain = set(), []
    for n, suf, m in marks[start:]:
        if (n, suf) not in seen:
            seen.add((n, suf))
            chain.append(m)
    return chain


def split_articles(text: str) -> list[tuple[str, str]]:
    """Split a regulation text into (article number, article text) chunks.

    Strict mode (heading alone on its line, consecutive numbering) is tried first because real OJ texts
    mention "Artikel 4" inside sentences and recitals; the loose line-start regex is the fallback.
    """
    chain = _article_chain(text)
    if len(chain) >= 3:
        out = []
        for i, m in enumerate(chain):
            end = chain[i + 1].start() if i + 1 < len(chain) else len(text)
            if i + 1 == len(chain):
                a = _ANNEX.search(text, m.end())
                end = a.start() if a else end
            out.append((m.group(1) + m.group(2), text[m.start():end].strip()))
        return out
    marks = list(_ART.finditer(text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1), text[m.start():end].strip()))
    return out


# A binding duty needs duty wording; definitions, scope statements and permissions do not have it.
_DUTY = re.compile(
    r"\b(?:shall|must|is required|are required|is obliged|are obliged|is prohibited|are prohibited|is not allowed|"
    r"muss|müssen|verpflichtet|verpflichtung|darf nicht|dürfen nicht|stellen? sicher|untersagt|ausgeschlossen)\b"
    r"|\b(?:ist|sind|hat|haben)\b[^.;]{0,160}\bzu\s+\w+",
    re.IGNORECASE,
)
_DEFINITIONS = re.compile(r"begriffsbestimmung|definitions?\b", re.IGNORECASE)


def has_duty_wording(sentence: str) -> bool:
    return bool(_DUTY.search(sentence))


def is_definitions_article(article_text: str) -> bool:
    """True when the article's own heading (its first lines) says it is a list of definitions."""
    head = "\n".join(article_text.strip().splitlines()[:3])
    return bool(_DEFINITIONS.search(head))


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not m:
            return {"obligations": []}
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {"obligations": []}


@dataclass
class ExtractionResult:
    kept: list[dict]
    rejected: list[dict]


def extract_from_article(llm: LLM, title: str, article: str, article_text: str) -> ExtractionResult:
    raw = llm.complete(SYSTEM, PROMPT.format(article=article, title=title, text=article_text), max_tokens=1500)
    items = _parse_json(raw).get("obligations", [])
    haystack = _squash(article_text)
    kept, rejected = [], []
    for it in items if isinstance(items, list) else []:
        sent = _squash(str(it.get("sentence", "")))
        role = str(it.get("applies_to", "")).lower()
        if not sent or role not in ROLES:
            rejected.append({**it, "reason": "malformed"})
        elif sent not in haystack:
            rejected.append({**it, "reason": "not verbatim in source"})
        elif not has_duty_wording(sent):
            rejected.append({**it, "reason": "no duty wording"})
        else:
            kept.append({"sentence": sent, "applies_to": role})
    return ExtractionResult(kept, rejected)


def extract_regulation(engine, llm: LLM, reg_id: str, title: str, text: str, celex: str | None = None,
                       url: str | None = None) -> dict:
    run_id = "R-" + hashlib.sha1(f"{reg_id}|{llm.name}|{PROMPT_VERSION}|{datetime.now(UTC)}".encode()).hexdigest()[:12]
    from sqlalchemy import text as sql

    with engine.begin() as conn:       # re-running a regulation replaces its previous extraction
        conn.execute(sql("DELETE FROM obligation WHERE reg_id = :r"), {"r": reg_id})
        conn.execute(sql("DELETE FROM regulation WHERE reg_id = :r"), {"r": reg_id})
    obligations, n_rej, seen = [], 0, set()
    for art, art_text in split_articles(text):
        if is_definitions_article(art_text):          # definitions are not duties; skip the LLM call as well
            continue
        res = extract_from_article(llm, title, art, art_text)
        n_rej += len(res.rejected)
        for it in res.kept:
            oid = "O-" + hashlib.sha1(f"{reg_id}|{art}|{it['sentence']}".encode()).hexdigest()[:16]
            if oid in seen:        # the model may return the same sentence twice for one article
                continue
            seen.add(oid)
            obligations.append({
                "obl_id": oid, "reg_id": reg_id, "run_id": run_id, "article": art, "text": it["sentence"],
                "applies_to_role": it["applies_to"], "confidence": 1.0,   # verbatim-verified
            })
    replace_table(engine, "regulation", pd.DataFrame([{"reg_id": reg_id, "title": title, "celex": celex, "url": url}]),
                  truncate=False)
    replace_table(engine, "extraction_run", pd.DataFrame([{
        "run_id": run_id, "started_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", ""),
        "model": llm.name, "method": "llm-obligations", "prompt_hash": hashlib.sha1((SYSTEM + PROMPT).encode()).hexdigest()[:12],
    }]), truncate=False)
    if obligations:
        replace_table(engine, "obligation", pd.DataFrame(obligations), truncate=False)
    return {"run_id": run_id, "kept": len(obligations), "rejected": n_rej}
