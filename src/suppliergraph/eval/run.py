"""Evaluation harness: LLM-only vs vector RAG vs GraphRAG on gold-SPARQL competency questions.

Metrics (per question, then aggregated):
  valid_query       - a syntactically valid, schema-grounded query was produced (GraphRAG only)
  exec_accuracy     - result set of the generated query == result set of the gold query (order-insensitive)
  exec_recall       - share of gold result tuples contained in the generated result
  answer_recall     - share of gold values that appear in the final answer text (all systems)
  grounded          - answer has no invalid citation, unsupported number or unsupported known entity
  citation_coverage - share of answer sentences that carry a citation

Limitations are documented in docs/evaluation.md: answer_recall is a lexical proxy (no LLM judge),
and unsupported-entity detection only knows entities that exist in the graph.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

from ..namespaces import SPARQL_PREFIX_BLOCK
from ..rag.answer import AnswerEngine
from ..store.base import SparqlStore


def load_questions() -> dict:
    return yaml.safe_load(resources.files("suppliergraph.eval").joinpath("competency.yaml").read_text(encoding="utf-8"))


def resolve_slots(store: SparqlStore, spec: dict) -> dict[str, str | None]:
    out = {}
    for name, q in spec["slots"].items():
        rows = store.select(SPARQL_PREFIX_BLOCK + q)
        out[name] = str(rows[0]["label"]) if rows else None
    return out


def _norm(v) -> str:
    if isinstance(v, float):
        return f"{v:.2f}"
    s = str(v).strip().lower()
    return re.sub(r"\s+", " ", s)


def result_set(rows: list[dict]) -> set[tuple]:
    return {tuple(sorted(_norm(v) for v in r.values() if v is not None)) for r in rows}


def gold_values(rows: list[dict], cap: int = 10) -> list[str]:
    vals = []
    for r in rows[:cap]:
        for v in r.values():
            if v is not None and not str(v).startswith("http"):
                vals.append(f"{v:,.2f}" if isinstance(v, float) else str(v))
    return vals


def answer_recall(answer: str, vals: list[str]) -> float:
    if not vals:
        return float("nan")
    a = answer.lower()
    plain = a.replace(",", "")
    hit = sum(1 for v in vals if v.lower() in a or v.lower().replace(",", "") in plain)
    return hit / len(vals)


@dataclass
class QResult:
    id: str
    type: str
    system: str
    metrics: dict


def run_eval(engine: AnswerEngine, systems=("llm_only", "vector_rag", "graphrag"), only: list[str] | None = None) -> dict:
    spec = load_questions()
    slots = resolve_slots(engine.store, spec)
    results: list[dict] = []
    skipped = []
    for q in spec["questions"]:
        if only and q["id"] not in only:
            continue
        if any(slots.get(s) is None for s in q.get("slots", [])):
            skipped.append({"id": q["id"], "reason": "slot has no data in this graph"})
            continue
        fill = {f"{{{s}}}": slots[s] for s in q.get("slots", [])}
        question, gold_q = q["question"], q["gold"]
        for k, v in fill.items():
            question, gold_q = question.replace(k, v), gold_q.replace(k, v.replace('"', '\\"'))
        gold_rows = engine.store.select(SPARQL_PREFIX_BLOCK + gold_q)
        gold_set, gvals = result_set(gold_rows), gold_values(gold_rows)
        for system in systems:
            ans = engine.ask(question, system)
            m = {
                "answer_recall": answer_recall(ans.text, gvals),
                "grounded": bool(ans.grounding.get("grounded")),
                "citation_coverage": ans.grounding.get("citation_coverage"),
                "gold_rows": len(gold_rows),
            }
            if system == "graphrag":
                pred = result_set(ans.rows)
                m["valid_query"] = ans.query_ok
                m["attempts"] = len(ans.attempts)
                m["exec_accuracy"] = bool(ans.query_ok and pred == gold_set)
                m["exec_recall"] = (len(gold_set & pred) / len(gold_set)) if gold_set else float("nan")
            results.append({"id": q["id"], "type": q["type"], "system": system, "question": question,
                            "answer": ans.text, "sparql": ans.sparql, "metrics": m})
    return {"slots": slots, "skipped": skipped, "results": results, "summary": summarize(results)}


def summarize(results: list[dict]) -> dict:
    out: dict = {}
    for system in sorted({r["system"] for r in results}):
        rs = [r for r in results if r["system"] == system]

        def mean(key, items=rs):
            vals = [r["metrics"][key] for r in items if key in r["metrics"] and r["metrics"][key] == r["metrics"][key]]
            return round(sum(float(v) for v in vals) / len(vals), 3) if vals else None

        s = {"n": len(rs), "answer_recall": mean("answer_recall"),
             "grounded_rate": mean("grounded"), "citation_coverage": mean("citation_coverage"),
             "hallucination_rate": round(1 - mean("grounded"), 3) if mean("grounded") is not None else None}
        if system == "graphrag":
            s.update(valid_query_rate=mean("valid_query"), exec_accuracy=mean("exec_accuracy"),
                     exec_recall=mean("exec_recall"), mean_attempts=mean("attempts"))
            s["by_type"] = {t: {"n": len(sub), "exec_accuracy": mean("exec_accuracy", sub)}
                            for t in sorted({r["type"] for r in rs}) for sub in [[r for r in rs if r["type"] == t]]}
        out[system] = s
    return out


def to_markdown(report: dict) -> str:
    cols = ["answer_recall", "grounded_rate", "hallucination_rate", "citation_coverage", "valid_query_rate",
            "exec_accuracy", "exec_recall", "mean_attempts"]
    lines = ["| system | n | " + " | ".join(cols) + " |", "|---|---|" + "---|" * len(cols)]
    for system, s in report["summary"].items():
        lines.append(f"| {system} | {s['n']} | " + " | ".join("" if s.get(c) is None else str(s[c]) for c in cols) + " |")
    return "\n".join(lines)


def save(report: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "eval_report.json").write_text(json.dumps(report, indent=2, default=str))
    (out_dir / "eval_report.md").write_text(to_markdown(report) + "\n")
