"""Time the gold competency queries against the configured store (run before/after switching stores)."""
import statistics
import time

from suppliergraph.eval.run import load_questions, resolve_slots
from suppliergraph.namespaces import SPARQL_PREFIX_BLOCK as P
from suppliergraph.store import open_store

store = open_store()
spec = load_questions()
slots = resolve_slots(store, spec)
print(f"{'id':32s} {'median ms':>10s} {'rows':>6s}")
for q in spec["questions"]:
    if any(slots.get(s) is None for s in q.get("slots", [])):
        continue
    gold = q["gold"]
    for s in q.get("slots", []):
        gold = gold.replace(f"{{{s}}}", slots[s].replace('"', '\\"'))
    times, n = [], 0
    for _ in range(5):
        t0 = time.perf_counter()
        n = len(store.select(P + gold))
        times.append((time.perf_counter() - t0) * 1000)
    print(f"{q['id']:32s} {statistics.median(times):10.1f} {n:6d}")
