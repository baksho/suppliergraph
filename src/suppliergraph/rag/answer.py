"""The three answering systems compared by the evaluation harness:

* GraphRAG   - text-to-SPARQL result rows + graph-expanded retrieval + grounded answer
* vector RAG - text retrieval only (no graph query)
* LLM only   - no evidence at all
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..kg.graphview import neighborhood
from ..llm import LLM
from ..store.base import IRI, SparqlStore
from . import factcheck
from .retrieval import DocIndex, expand_doc
from .text2sparql import Text2Sparql

ANSWER_SYSTEM = """You answer questions about public procurement, suppliers and ownership using ONLY the evidence given.
- Cite the evidence id in square brackets after every statement, e.g. [R1] or [F3] or [D2].
- Use only numbers and names that appear in the evidence. Do not compute new numbers.
- If the evidence does not contain the answer, say exactly: "The knowledge graph does not contain enough information to answer."
- Be concise. Matches against sanction lists are leads for human review, never findings; say so when relevant."""

NO_EVIDENCE_SYSTEM = "You are a procurement analyst. Answer concisely. If you are not sure, say so."

REFUSAL = "The knowledge graph does not contain enough information to answer."


@dataclass
class Answer:
    question: str
    system: str
    text: str
    sparql: str | None = None
    attempts: list[dict] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    evidence: dict[str, str] = field(default_factory=dict)
    grounding: dict = field(default_factory=dict)
    graph: dict = field(default_factory=dict)
    query_ok: bool = False

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _fmt_value(v) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def rows_to_evidence(rows: list[dict], boolean: bool | None, limit: int = 25) -> dict[str, str]:
    ev: dict[str, str] = {}
    if boolean is not None:
        ev["R1"] = f"ASK query result: {boolean}"
    for i, r in enumerate(rows[:limit], start=1):
        ev[f"R{i}"] = "; ".join(f"{k}={_fmt_value(v)}" for k, v in r.items() if v is not None)
    if len(rows) > limit:
        ev[f"R{limit}"] += f"  (+{len(rows) - limit} more rows not shown)"
    return ev


class AnswerEngine:
    def __init__(self, llm: LLM, store: SparqlStore, index: DocIndex | None = None,
                 labels: factcheck.LabelIndex | None = None, **t2s_kw):
        self.llm, self.store = llm, store
        self.index = index or DocIndex.from_store(store)
        self.labels = labels or factcheck.LabelIndex.from_store(store)
        self.t2s = Text2Sparql(llm, store, **t2s_kw)

    # -- evidence builders ------------------------------------------------------------------
    def _doc_evidence(self, question: str, k: int, expand: bool) -> tuple[dict[str, str], list[str], list[str]]:
        ev, iris = {}, []
        docs = self.index.search(question, k=k)
        for i, d in enumerate(docs, start=1):
            ev[f"D{i}"] = f"[{d.kind}] {d.text[:400]}"
            iris.append(d.iri)
        facts_iris = []
        if expand:
            n = 0
            for d in docs:
                for f in expand_doc(self.store, d.iri)[:8]:
                    n += 1
                    ev[f"F{n}"] = f.text
                    facts_iris += [f.triple[0], f.triple[2]]
        return ev, iris, facts_iris

    def _generate(self, question: str, evidence: dict[str, str], system: str) -> str:
        if not evidence:
            return self.llm.complete(system, question, max_tokens=500).strip()
        ev = "\n".join(f"[{k}] {v}" for k, v in evidence.items())
        return self.llm.complete(system, f"EVIDENCE\n{ev}\n\nQUESTION\n{question}", max_tokens=600).strip()

    def _finish(self, a: Answer, seeds: list[str]) -> Answer:
        a.grounding = factcheck.check(a.text, a.evidence, self.labels).as_dict()
        if seeds:
            try:
                a.graph = neighborhood(self.store, seeds, hops=1)
            except Exception:                              # visualisation must never break an answer
                a.graph = {"nodes": [], "edges": []}
        return a

    # -- systems ----------------------------------------------------------------------------
    def graphrag(self, question: str, k_docs: int = 3) -> Answer:
        r = self.t2s.run(question)
        ev = rows_to_evidence(r.rows, r.boolean if r.kind == "ask" else None)
        dev, _, fact_iris = self._doc_evidence(question, k_docs, expand=True)
        ev.update(dev)
        a = Answer(question, "graphrag", "", sparql=r.query, rows=r.rows, evidence=ev, query_ok=r.ok,
                   attempts=[{"query": x.query, "error": x.error, "n_rows": x.n_rows} for x in r.attempts])
        a.text = self._generate(question, ev, ANSWER_SYSTEM) if ev else REFUSAL
        seeds = [v for row in r.rows for v in row.values() if isinstance(v, IRI)] + fact_iris
        return self._finish(a, seeds)

    def vector_rag(self, question: str, k_docs: int = 4) -> Answer:
        ev, iris, _ = self._doc_evidence(question, k_docs, expand=False)
        a = Answer(question, "vector_rag", "", evidence=ev)
        a.text = self._generate(question, ev, ANSWER_SYSTEM) if ev else REFUSAL
        return self._finish(a, iris)

    def llm_only(self, question: str) -> Answer:
        a = Answer(question, "llm_only", "")
        a.text = self._generate(question, {}, NO_EVIDENCE_SYSTEM)
        return self._finish(a, [])

    def ask(self, question: str, mode: str = "graphrag") -> Answer:
        return {"graphrag": self.graphrag, "vector_rag": self.vector_rag, "llm_only": self.llm_only}[mode](question)
