import React, { useEffect, useState } from "react";
import { api } from "./api.js";

export default function DiscoverTab() {
  const [by, setBy] = useState("buyer");
  const [buyers, setBuyers] = useState([]);
  const [cats, setCats] = useState([]);
  const [sel, setSel] = useState("");
  const [res, setRes] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    api.buyers().then(setBuyers).catch((e) => setErr(e.message));
    api.categories().then(setCats).catch((e) => setErr(e.message));
    api.models().then(setMetrics).catch(() => setMetrics(null));
  }, []);
  const go = async () => { setErr(null); try { setRes(await api.discover(by === "buyer" ? { buyer: sel, k: 10 } : { category: sel, k: 10 })); } catch (e) { setErr(e.message); } };
  const opts = by === "buyer" ? buyers.map((b) => [b.e, `${b.name} (${b.tenders} tenders)`]) : cats.map((c) => [c.c, `${c.code} ${c.label || ""} (${c.tenders})`]);
  const scores = res ? res.candidates.map((c) => c.score) : [];
  const lo = Math.min(...scores), hi = Math.max(...scores);
  const w = (s) => 8 + (hi === lo ? 1 : (s - lo) / (hi - lo)) * 72;
  const embedding = res?.ranker?.startsWith("embedding");
  return (
    <div>
      <div className="view-head"><h1>Find suppliers</h1><p>Suppliers a buyer has not used yet, or suppliers that could cover a product category.</p></div>
      <div className="controls">
        <select aria-label="Search by" value={by} onChange={(e) => { setBy(e.target.value); setSel(""); setRes(null); }}><option value="buyer">For a buyer</option><option value="category">For a category</option></select>
        <select aria-label="Choose" value={sel} onChange={(e) => setSel(e.target.value)} style={{ flex: 1, maxWidth: 520 }}><option value="">Choose one</option>{opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <button className="btn" onClick={go} disabled={!sel}>Show suppliers</button>
      </div>
      {err && <div className="alert err">{err}</div>}
      {!res && <div className="panel"><div className="empty">Choose a buyer or a category to rank candidate suppliers.</div></div>}
      {res && (
        <section className="panel">
          <h3>{embedding ? "Ranked by a trained graph-embedding model" : "Ranked by simple rules: shared categories, same corporate group, award count"}</h3>
          <table><thead><tr><th>Supplier</th><th>Country</th><th>Score</th><th>Why it appears</th></tr></thead>
            <tbody>{res.candidates.map((c) => (
              <tr key={c.iri}><td><b>{c.name}</b></td><td>{c.country}</td>
                <td style={{ whiteSpace: "nowrap" }}><span className="bar" style={{ width: w(c.score) }} />{c.score}</td>
                <td className="small">{Object.entries(c.evidence).filter(([, v]) => (Array.isArray(v) ? v.length : v)).map(([k, v]) => <div key={k}><span className="faint">{k.replaceAll("_", " ")}</span> {Array.isArray(v) ? v.join(", ") : v}</div>)}</td></tr>))}</tbody></table>
          <div className="pad small muted" style={{ borderTop: "1px solid var(--line)" }}>Scores rank candidates against each other and are not probabilities. The reasons are graph facts, not an explanation of the model.</div>
        </section>
      )}
      {metrics && <section className="panel" style={{ marginTop: 20 }}><h3>Offline evaluation on held-out later awards</h3><div className="pad"><pre className="code">{JSON.stringify(metrics, null, 2)}</pre></div></section>}
    </div>
  );
}
