async function j(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* body is not JSON */ }
    throw new Error(`${r.status}: ${msg}`);
  }
  return r.json();
}
const q = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v != null && v !== "")).toString();
const S = typeof window !== "undefined" ? window.SG_STATIC : undefined;
const ent = (k) => S.entities[k] || (() => { throw new Error("404: not in this static snapshot"); })();
const staticApi = {
  health: async () => S.health,
  ask: async (question) => {
    const r = S.ask.find((a) => a.question === question);
    if (!r) throw new Error("Static demo: no LLM here. Pick one of the recorded example questions.");
    return { question, system: "static", text: `Static demo (no LLM): the competency query below ran against the fictional test graph and returned ${r.rows.length} row(s).`,
      sparql: r.sparql, evidence: Object.fromEntries(r.rows.map((x, i) => [`R${i + 1}`, Object.entries(x).map(([k, v]) => `${k}=${v}`).join("; ")])),
      grounding: {}, graph: {}, seconds: 0 };
  },
  search: async (s) => Object.values(S.entities).map((e) => e.hit).filter((h) => h && h.name.toLowerCase().includes(s.toLowerCase())).sort((a, b) => (b.flagged - a.flagged) || (b.awards - a.awards)),
  entity: async (k) => ent(k).detail, contracts: async (k) => ent(k).contracts, graph: async (k) => ent(k).graph, lineage: async (k) => ent(k).lineage,
  buyers: async () => S.buyers, categories: async () => S.categories,
  discover: async (p) => S.discover[p.buyer || p.category],
  shacl: async () => S.shacl, dq: async () => S.dq, er: async () => S.er, products: async () => S.products,
  models: async () => { throw new Error("no metrics in static demo"); },
};
const liveApi = {
  health: () => j("/api/health"),
  ask: (question, mode) => j("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, mode }) }),
  search: (s) => j(`/api/entities/search?${q({ q: s })}`),
  entity: (k) => j(`/api/entities/${k}`),
  contracts: (k) => j(`/api/entities/${k}/contracts`),
  graph: (k, hops = 2) => j(`/api/entities/${k}/graph?hops=${hops}`),
  lineage: (k) => j(`/api/entities/${k}/lineage`),
  buyers: () => j("/api/discover/buyers"),
  categories: () => j("/api/discover/categories"),
  discover: (p) => j(`/api/discover/suppliers?${q(p)}`),
  shacl: (refresh) => j(`/api/governance/shacl?refresh=${!!refresh}`),
  dq: () => j("/api/governance/dq"),
  er: () => j("/api/governance/er"),
  products: () => j("/api/governance/products"),
  models: () => j("/api/models"),
};

export const api = S ? staticApi : liveApi;
export const isStatic = !!S;
