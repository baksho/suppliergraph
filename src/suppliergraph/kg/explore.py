"""Standalone knowledge-graph explorer: writes one self-contained HTML file (vis-network from a CDN)."""
from __future__ import annotations

import json
from pathlib import Path

from ..namespaces import SPARQL_PREFIX_BLOCK
from .graphview import neighborhood

_PAGE = """<!doctype html><meta charset="utf-8"><title>SupplierGraph explorer</title>
<script src="https://unpkg.com/vis-network@9/standalone/umd/vis-network.min.js"></script>
<style>body{margin:0;font:13px system-ui}#n{height:100vh}#k{position:absolute;top:8px;left:8px;background:#fffd;padding:6px 10px;border:1px solid #ccd}</style>
<div id="k">__KEY__</div><div id="n"></div>
<script>
const g = __DATA__;
const colors = {LegalEntity:"#2b6cb0", Award:"#dd6b20", Tender:"#718096", Sanction:"#c53030", Country:"#38a169", Obligation:"#805ad5"};
const nodes = g.nodes.map(n => ({id:n.id, label:(n.label||n.id.split(/[\\/#]/).pop()).slice(0,28), title:(n.type||"")+"\\n"+n.id,
  color:colors[n.type]||"#a0aec0", shape:"dot", size:n.type==="LegalEntity"?14:8}));
const edges = g.edges.map(e => ({from:e.source, to:e.target, arrows:"to", title:e.label||""}));
new vis.Network(document.getElementById("n"), {nodes:new vis.DataSet(nodes), edges:new vis.DataSet(edges)},
  {physics:{solver:"forceAtlas2Based",stabilization:{iterations:200}},interaction:{hover:true}});
</script>"""


def top_entities(store, n: int = 15) -> list[str]:
    rows = store.select(SPARQL_PREFIX_BLOCK + f"""
        SELECT ?e (COUNT(DISTINCT ?a) AS ?k) WHERE {{ ?a sg:awardedTo ?e . ?e a sg:LegalEntity }}
        GROUP BY ?e ORDER BY DESC(?k) LIMIT {int(n)}""")
    return [str(r["e"]) for r in rows]


def render(store, out: Path, seeds: list[str] | None = None, hops: int = 2, max_nodes: int = 150) -> dict:
    seeds = seeds or top_entities(store)
    g = neighborhood(store, seeds, hops=hops, max_nodes=max_nodes)
    key = "blue supplier / orange award / grey tender / red sanction / green country - drag, zoom, hover"
    Path(out).write_text(_PAGE.replace("__DATA__", json.dumps(g)).replace("__KEY__", key), encoding="utf-8")
    return {"nodes": len(g["nodes"]), "edges": len(g["edges"]), "file": str(out)}
