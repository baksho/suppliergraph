"""Entity resolution: procurement parties -> LEIs, and legal entities -> sanction-list entries."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pandas as pd

from ..config import Settings, get_settings
from ..staging.db import read_sql, replace_table
from .matcher import NameMatcher, Scorer

MARGIN = 0.03   # best candidate must beat the runner-up by this much to be auto-accepted


@dataclass
class Decision:
    lei: str | None
    score: float
    method: str
    status: str


def decide(cands, accept: float, review: float, margin: float = MARGIN) -> Decision:
    if not cands:
        return Decision(None, 0.0, "fuzzy", "none")
    s1 = cands[0].score
    s2 = cands[1].score if len(cands) > 1 else 0.0
    if s1 >= accept and (s1 - s2) >= margin:
        return Decision(cands[0].target_id, s1, "fuzzy", "accepted")
    if s1 >= review:
        return Decision(cands[0].target_id, s1, "fuzzy", "review")
    return Decision(None, s1, "fuzzy", "none")


def build_gleif_matcher(engine, scorer: Scorer | None = None) -> NameMatcher:
    g = read_sql(engine, "SELECT lei, legal_name, legal_country FROM gleif_entity")
    return NameMatcher(
        g["lei"].tolist(), g["legal_name"].tolist(),
        [({c} if c else set()) for c in g["legal_country"].tolist()], scorer=scorer,
    )


def resolve_parties(engine, lei_scheme: str = "XI-LEI", settings: Settings | None = None,
                    scorer: Scorer | None = None, use_identifiers: bool = True) -> pd.DataFrame:
    """Resolve every party. Deterministic path first (published LEI), fuzzy name match otherwise."""
    settings = settings or get_settings()
    parties = read_sql(engine, "SELECT party_id, scheme, identifier, name, country FROM party")
    known = set(read_sql(engine, "SELECT lei FROM gleif_entity")["lei"])
    matcher = build_gleif_matcher(engine, scorer)
    rows, todo = [], []
    for r in parties.itertuples(index=False):
        if use_identifiers and r.scheme == lei_scheme and r.identifier in known:
            rows.append((r.party_id, r.identifier, 1.0, "identifier", "accepted"))
        else:
            todo.append(r)
    cands = matcher.candidates_batch([r.name for r in todo], [r.country for r in todo], k=5)
    for r, c in zip(todo, cands):
        d = decide(c, settings.er_accept, settings.er_review)
        rows.append((r.party_id, d.lei, d.score, d.method, d.status))
    df = pd.DataFrame(rows, columns=["party_id", "lei", "score", "method", "status"])
    replace_table(engine, "party_resolution", df)
    return df


def resolve_sanctions(engine, settings: Settings | None = None, scorer: Scorer | None = None,
                      store_threshold: float = 0.85) -> int:
    """Score entities against sanction names and aliases. Every stored match needs human review."""
    settings = settings or get_settings()
    entries = read_sql(engine, "SELECT entry_id, name, aliases, countries FROM sanction_entry")
    if entries.empty:
        replace_table(engine, "sanction_match", pd.DataFrame())
        return 0
    ids, names, countries = [], [], []
    for r in entries.itertuples(index=False):
        cs = {c.strip().upper() for c in (r.countries or "").split(";") if c.strip()}
        variants = [r.name] + [a.strip() for a in (r.aliases or "").split(";") if a.strip()]
        for v in dict.fromkeys(variants):
            ids.append(r.entry_id)
            names.append(v)
            countries.append(cs)
    matcher = NameMatcher(ids, names, countries, scorer=scorer)
    ents = read_sql(engine, "SELECT entity_key, legal_name, country FROM v_entity")
    cands = matcher.candidates_batch(ents["legal_name"].tolist(), ents["country"].tolist(), k=3)
    rows = []
    for e, cs in zip(ents.itertuples(index=False), cands):
        seen = set()
        for c in cs:
            if c.score >= store_threshold and c.target_id not in seen:
                seen.add(c.target_id)
                mid = "M-" + hashlib.sha1(f"{e.entity_key}|{c.target_id}".encode()).hexdigest()[:16]
                rows.append((mid, e.entity_key, c.target_id, round(c.score, 4), "fuzzy-name", "needs_review"))
    df = pd.DataFrame(rows, columns=["match_id", "entity_key", "entry_id", "score", "method", "review_status"])
    replace_table(engine, "sanction_match", df)
    return len(df)


def build_scope(engine) -> int:
    """Restrict the graph to entities that matter: resolved LEIs plus all their ancestors."""
    seed = set(read_sql(engine, "SELECT lei FROM party_resolution WHERE status='accepted' AND lei IS NOT NULL")["lei"])
    rel = read_sql(engine, "SELECT child_lei, parent_lei FROM gleif_relationship")
    parents: dict[str, set[str]] = {}
    for c, p in zip(rel["child_lei"], rel["parent_lei"]):
        parents.setdefault(c, set()).add(p)
    scope, frontier = set(seed), set(seed)
    while frontier:
        nxt = set()
        for e in frontier:
            for p in parents.get(e, ()):
                if p not in scope:
                    scope.add(p)
                    nxt.add(p)
        frontier = nxt
    replace_table(engine, "kg_scope", pd.DataFrame({"lei": sorted(scope)}))
    return len(scope)
