"""Text-to-SPARQL with schema grounding, validation, execution guard and an error-driven repair loop."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rdflib.plugins.sparql import prepareQuery

from ..llm import LLM
from ..namespaces import ONT_BASE, PREFIXES
from ..store.base import SparqlStore
from ..store.local import RDFLIB_LOCK
from .schema_context import direction_hints, known_terms, schema_text

SYSTEM = """You translate questions into SPARQL 1.1 queries over the SupplierGraph knowledge graph.
Rules:
- Use ONLY the classes and properties listed in the schema. Never invent terms.
- Return exactly one query in a ```sparql code block and nothing else.
- Use SELECT (or ASK). Use DISTINCT where duplicates are possible. Do not use SERVICE, LOAD or updates.
- Find entities by name with sg:legalName (or sg:recordedName) and a case-insensitive CONTAINS filter."""

PROMPT = """SCHEMA
{schema}

QUESTION
{question}
{feedback}"""

FORBIDDEN = re.compile(r"\b(SERVICE|LOAD|INSERT|DELETE|CLEAR|DROP|CREATE|COPY|MOVE|ADD)\b", re.IGNORECASE)
_FENCE = re.compile(r"```(?:sparql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_SG_TERM = re.compile(r"\bsg:([A-Za-z_][A-Za-z0-9_]*)")
_SG_FULL = re.compile(re.escape(ONT_BASE) + r"([A-Za-z_][A-Za-z0-9_]*)")
_PREFIX_DECL = re.compile(r"^\s*PREFIX\s+([A-Za-z0-9_\-]*):", re.IGNORECASE | re.MULTILINE)


class QueryError(Exception):
    pass


_OPEN_FENCE = re.compile(r"^\s*```(?:sparql)?\s*", re.IGNORECASE)


def extract_query(raw: str) -> str:
    m = _FENCE.search(raw)
    if m:
        return m.group(1).strip()
    # models often forget the closing fence: drop an opening one (and a stray closing one) instead of failing to parse
    return _OPEN_FENCE.sub("", raw).replace("```", "").strip()


_CONTAINS_LIT = re.compile(r'CONTAINS\s*\(\s*LCASE\s*\(\s*STR\s*\(\s*\?\w+\s*\)\s*\)\s*,\s*"([^"]+)"', re.IGNORECASE)


GENERIC_WORDS = {"company", "companies", "parent", "parents", "subsidiary", "subsidiaries", "supplier", "suppliers", "buyer",
                 "buyers", "entity", "entities", "firm", "firms", "organisation", "organization", "owner", "owners",
                 "contractor", "contractors", "group", "groups", "authority", "authorities", "the", "a", "an", "of", "any"}


def generic_name_filters(query: str, question: str = "") -> list[str]:
    """Name-filter strings made only of generic words ('parent company', 'suppliers'): they name no entity."""
    return [lit for lit in dict.fromkeys(_CONTAINS_LIT.findall(query))
            if lit.strip() and all(w in GENERIC_WORDS for w in re.findall(r"\w+", lit.lower()))]


def with_prefixes(query: str) -> str:
    declared = {p.lower() for p in _PREFIX_DECL.findall(query)}
    missing = "".join(f"PREFIX {k}: <{v}>\n" for k, v in PREFIXES.items() if k.lower() not in declared)
    return missing + query


def validate_query(query: str, limit: int = 200) -> tuple[str, str]:
    """Returns (checked_query, kind). Raises QueryError with a message the LLM can act on."""
    if FORBIDDEN.search(re.sub(r'"[^"]*"|\'[^\']*\'', "", query)):
        raise QueryError("Forbidden keyword (updates, SERVICE and LOAD are not allowed).")
    if len(re.findall(r"[\s\w>]\.(?=\s|$|\})", re.sub(r'"[^"]*"', "", query))) > 25:
        raise QueryError("Query is too long. Rewrite it with at most about 8 triple patterns; for ownership chains use "
                         "the transitive sg:hasAncestor instead of repeating sg:hasDirectParent.")
    q = with_prefixes(query)
    try:
        with RDFLIB_LOCK:
            prepared = prepareQuery(q)
    except Exception as exc:                                   # rdflib raises several exception types
        raise QueryError(f"SPARQL syntax error: {str(exc)[:300]}") from exc
    kind = {"SelectQuery": "select", "AskQuery": "ask", "ConstructQuery": "construct"}.get(prepared.algebra.name)
    if kind is None:
        raise QueryError("Only SELECT, ASK and CONSTRUCT queries are allowed.")
    terms = known_terms()
    used = set(_SG_TERM.findall(query)) | set(_SG_FULL.findall(query))
    unknown = sorted(t for t in used if t not in terms)
    if unknown:
        raise QueryError(
            f"Unknown schema term(s): {', '.join('sg:' + t for t in unknown)}. "
            f"Use only terms from the schema (available: {', '.join(sorted(terms))})."
        )
    if kind == "select" and not re.search(r"\bLIMIT\s+\d+", q, re.IGNORECASE):
        q = q.rstrip() + f"\nLIMIT {limit}"
    return q, kind


@dataclass
class Attempt:
    query: str
    error: str | None = None
    n_rows: int | None = None


@dataclass
class Text2SparqlResult:
    ok: bool
    query: str | None
    kind: str | None
    rows: list[dict] = field(default_factory=list)
    boolean: bool | None = None
    attempts: list[Attempt] = field(default_factory=list)


class Text2Sparql:
    def __init__(self, llm: LLM, store: SparqlStore, max_attempts: int = 3, timeout: float = 30.0,
                 row_limit: int = 200, retry_on_empty: bool = True):
        self.llm, self.store = llm, store
        self.max_attempts, self.timeout, self.row_limit, self.retry_on_empty = max_attempts, timeout, row_limit, retry_on_empty
        self._schema = schema_text()

    def run(self, question: str) -> Text2SparqlResult:
        result = Text2SparqlResult(ok=False, query=None, kind=None)
        feedback = ""
        for attempt in range(self.max_attempts):
            raw = self.llm.complete(SYSTEM, PROMPT.format(schema=self._schema, question=question, feedback=feedback),
                                    max_tokens=800)
            query = extract_query(raw)
            a = Attempt(query=query)
            result.attempts.append(a)
            bad = generic_name_filters(query, question)
            if bad:                                        # never executed: it can only return nothing
                a.error = f"Name filter {bad} names no entity."
                feedback = (f"\nYour previous query:\n{query}\nwas rejected: the filter text {bad} is generic wording, "
                            "not an entity name. Delete that name filter completely (and the variables only it used) and keep "
                            "the remaining conditions, such as the sg:hops condition.")
                continue
            try:
                checked, kind = validate_query(query, self.row_limit)
                if kind == "ask":
                    result.boolean, rows = self.store.ask(checked, timeout=self.timeout), []
                elif kind == "construct":
                    g = self.store.construct(checked, timeout=self.timeout)
                    rows = [{"s": str(s), "p": str(p), "o": str(o)} for s, p, o in list(g)[: self.row_limit]]
                else:
                    rows = self.store.select(checked, timeout=self.timeout)
            except QueryError as exc:
                a.error = str(exc)
                feedback = f"\nYour previous query:\n{query}\nwas rejected: {exc}\nFix it and return the corrected query."
                continue
            except Exception as exc:                          # execution failure or timeout
                a.error = f"Execution error: {str(exc)[:300]}"
                feedback = f"\nYour previous query:\n{query}\nfailed: {a.error}\nReturn a simpler, corrected query."
                continue
            a.n_rows = len(rows)
            if not rows and kind == "select" and self.retry_on_empty and attempt < self.max_attempts - 1 \
                    and not any(x.n_rows == 0 for x in result.attempts[:-1]):
                bad = generic_name_filters(query, question)
                hint = (f' The filter text {bad} are ordinary words from the question, not an entity name: remove that '
                        "filter." if bad else "")
                feedback = (f"\nYour previous query:\n{query}\nreturned no rows. Check entity-name filters "
                            f"(use lower-case CONTAINS on a distinctive word) and property directions, then retry.{hint}"
                            + (f"\nProperty directions: {dh}." if (dh := direction_hints(query)) else ""))
                result.query, result.kind, result.rows, result.ok = checked, kind, rows, True
                continue
            result.query, result.kind, result.rows, result.ok = checked, kind, rows, True
            return result
        return result
