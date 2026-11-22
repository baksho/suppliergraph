"""SHACL validation with pyshacl; reports are turned into plain dicts for the API and the UI."""
from __future__ import annotations

from collections import Counter

from rdflib import Graph
from rdflib.namespace import SH

from ..config import get_settings
from ..store.base import SparqlStore


def validate(store: SparqlStore, shapes: Graph | None = None, sample: int = 25) -> dict:
    from pyshacl import validate as shacl_validate

    settings = get_settings()
    data = store.as_graph()
    ont = Graph().parse(settings.ontology_path)
    shapes = shapes or Graph().parse(settings.shapes_path)
    conforms, report_graph, _ = shacl_validate(
        data, shacl_graph=shapes, ont_graph=ont, inference="rdfs", abort_on_first=False,
        allow_warnings=False, meta_shacl=False, advanced=True,
    )
    results = []
    for r in report_graph.subjects(SH.resultSeverity, None):
        def one(p):
            return next(report_graph.objects(r, p), None)  # noqa: B023
        results.append({
            "focus": str(one(SH.focusNode)),
            "path": str(one(SH.resultPath)) if one(SH.resultPath) else None,
            "message": str(one(SH.resultMessage)) if one(SH.resultMessage) else None,
            "severity": str(one(SH.resultSeverity)).rsplit("#", 1)[-1],
            "shape": str(one(SH.sourceShape)).rsplit("#", 1)[-1] if one(SH.sourceShape) else None,
            "value": str(one(SH.value)) if one(SH.value) is not None else None,
        })
    by_sev = Counter(r["severity"] for r in results)
    by_shape: Counter = Counter((r["shape"], r["severity"], r["message"]) for r in results)
    return {
        "conforms": bool(conforms),
        "violations": by_sev.get("Violation", 0),
        "warnings": by_sev.get("Warning", 0),
        "by_shape": [
            {"shape": s, "severity": sev, "message": m, "count": n}
            for (s, sev, m), n in by_shape.most_common()
        ],
        "samples": results[:sample],
    }
