"""Build a one-file static demo of the UI from the FICTIONAL test fixtures (no server, no LLM).

Usage: python scripts/make_static_demo.py out.html      (run `cd ui && npm run build` first)
The snapshot is injected as window.SG_STATIC; the UI then answers from it instead of calling /api.
"""
import json
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from fastapi.testclient import TestClient  # noqa: E402

from suppliergraph.api.main import create_app  # noqa: E402
from suppliergraph.config import Settings  # noqa: E402
from suppliergraph.eval.run import load_questions, resolve_slots  # noqa: E402
from suppliergraph.ingest.common import load_sources  # noqa: E402
from suppliergraph.kg.build import build_kg  # noqa: E402
from suppliergraph.llm import ScriptedLLM  # noqa: E402
from suppliergraph.namespaces import SPARQL_PREFIX_BLOCK as P  # noqa: E402
from suppliergraph.pipeline import extract_all, ingest_all, resolve_all  # noqa: E402
from suppliergraph.store.local import LocalStore  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def build(tmp: Path):
    cfg = load_sources()
    cfg["gleif"].update(level1_path=str(FIX / "gleif/level1.csv"), level2_path=str(FIX / "gleif/level2.csv"), countries=None)
    cfg["cpv"]["path"] = str(FIX / "cpv/cpv.csv")
    cfg["ocds"]["paths"] = [str(FIX / "ocds")]
    cfg["sanctions"]["path"] = str(FIX / "sanctions/targets.simple.csv")
    s = Settings()
    s.staging_url, s.local_kg_path, s.data_dir, s.models_dir = f"sqlite:///{tmp/'s.db'}", tmp / "kg.nq", tmp, tmp / "m"
    ingest_all(s, cfg)
    resolve_all(s, cfg)
    g1 = "Contracting authorities shall publish every award notice within thirty days of the award decision."
    g2 = "Suppliers shall document the results of each assessment and make them available on request."

    def script(system, prompt):
        if "Article 1 " in prompt:
            return json.dumps({"obligations": [{"sentence": g1, "applies_to": "buyer"}]})
        if "Article 2 " in prompt:
            return json.dumps({"obligations": [{"sentence": g2, "applies_to": "supplier"}]})
        return json.dumps({"obligations": []})

    extract_all(s, ScriptedLLM(script), [{"id": "TEST-REG", "title": "Test Regulation", "path": str(FIX / "regulation/test_regulation.txt")}])
    store = LocalStore()
    build_kg(store, s, persist=True)
    return s, store


def main(out: Path):
    tmp = Path(tempfile.mkdtemp())
    s, store = build(tmp)
    c = TestClient(create_app(store=store, settings=s, ui_dir=tmp / "none"))
    get = lambda u: c.get(u).json()  # noqa: E731
    snap = {"health": get("/api/health"), "entities": {}, "buyers": get("/api/discover/buyers"),
            "categories": get("/api/discover/categories"), "discover": {}, "shacl": get("/api/governance/shacl"),
            "dq": get("/api/governance/dq"), "er": get("/api/governance/er"), "products": get("/api/governance/products"),
            "models": None, "ask": []}
    snap["health"].update(model_artifact=False, llm_configured=False, store="static snapshot")
    keys = [str(r["e"]).rsplit("/", 1)[-1] for r in store.select(P + "SELECT DISTINCT ?e WHERE { ?e a sg:LegalEntity ; sg:legalName ?n }")]
    for k in keys:
        det = get(f"/api/entities/{k}")
        if "name" not in det:
            continue
        s_ = get(f"/api/entities/search?q={quote(det['name'][:12])}")
        snap["entities"][k] = {"detail": det, "graph": get(f"/api/entities/{k}/graph?hops=2"),
                               "contracts": get(f"/api/entities/{k}/contracts"), "lineage": get(f"/api/entities/{k}/lineage"),
                               "hit": next((dict(h, flagged=bool(det.get("exposure_flags"))) for h in s_ if h["key"] == k), None)}
    for b in snap["buyers"]:
        snap["discover"][b["e"]] = get(f"/api/discover/suppliers?buyer={quote(b['e'], safe='')}&k=10")
    for cat in snap["categories"]:
        snap["discover"][cat["c"]] = get(f"/api/discover/suppliers?category={quote(cat['c'], safe='')}&k=10")
    spec = load_questions()
    slots = resolve_slots(store, spec)
    for q in spec["questions"]:
        if any(slots.get(x) is None for x in q.get("slots", [])):
            continue
        question, gold = q["question"], q["gold"]
        for x in q.get("slots", []):
            question, gold = question.replace(f"{{{x}}}", slots[x]), gold.replace(f"{{{x}}}", slots[x].replace('"', '\\"'))
        snap["ask"].append({"question": question, "sparql": gold.strip(), "rows": store.select(P + gold)[:25]})
    html = (ROOT / "ui" / "dist" / "index.html").read_text()
    js = next((ROOT / "ui" / "dist" / "assets").glob("*.js")).read_text()
    css = next((ROOT / "ui" / "dist" / "assets").glob("*.css")).read_text()
    data = json.dumps(snap, default=str).replace("</", "<\\/")
    html = re.sub(r'<script type="module"[^>]*></script>', "", html)
    html = re.sub(r'<link rel="stylesheet"[^>]*>', "", html)
    html = html.replace("</head>", f"<style>{css}</style></head>")
    html = html.replace("</body>", f"<script>window.SG_STATIC={data};</script><script type=\"module\">{js.replace('</script', '<\\/script')}</script></body>")
    out.write_text(html, encoding="utf-8")
    print(out, f"{out.stat().st_size/1e6:.2f} MB;", len(keys), "entities,", len(snap["ask"]), "recorded queries")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
