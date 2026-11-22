import React, { useEffect, useState } from "react";
import { api, isStatic } from "./api.js";
import GraphView from "./GraphView.jsx";

const money = (v) => (v == null ? "n/a" : Number(v).toLocaleString("en", { maximumFractionDigits: 0 }));

function Ladder({ d }) {
  const lead = new Set((d.exposure_flags || []).map((f) => f.vname));
  const merged = Object.values(d.parents.reduce((m, p) => { (m[p.p] ||= { ...p, kinds: [] }).kinds.push(p.kind); return m; }, {}));
  const steps = [{ name: d.name, k: "This entity", self: true, lead: lead.has(d.name) }, ...merged.map((p) => ({ name: p.name, k: p.kinds.join(", "), lead: lead.has(p.name) }))];
  if (d.parents.length === 0) return <p className="muted">No parent company is recorded for this entity.</p>;
  return (
    <div className="ladder">
      {steps.map((s, i) => (
        <React.Fragment key={i}>
          {i > 0 && <div className="link-sep"><span>owned by</span></div>}
          <div className={`step ${s.self ? "self" : ""} ${s.lead ? "lead" : ""}`}><div className="k">{s.k}{s.lead ? ", sanction lead" : ""}</div><div className="n">{s.name}</div></div>
        </React.Fragment>
      ))}
    </div>
  );
}

export default function SupplierTab() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState([]);
  const [key, setKey] = useState(null);
  const [d, setD] = useState(null);
  const [graph, setGraph] = useState(null);
  const [contracts, setContracts] = useState([]);
  const [lineage, setLineage] = useState([]);
  const [err, setErr] = useState(null);

  const search = async (s) => { try { setErr(null); setHits(s.length >= (isStatic ? 0 : 2) ? await api.search(s) : []); } catch (e) { setErr(e.message); } };
  useEffect(() => { search(""); }, []);
  useEffect(() => {
    if (isStatic && hits.length && !key) {            // open with the most instructive record: a sanction lead if any
      setKey((hits.find((h) => h.flagged) || hits[0]).key);
    }
  }, [hits]);
  useEffect(() => {
    if (!key) return;
    setErr(null);
    Promise.all([api.entity(key), api.graph(key, 2), api.contracts(key), api.lineage(key)])
      .then(([a, b, c, l]) => { setD(a); setGraph(b); setContracts(c); setLineage(l); })
      .catch((e) => setErr(e.message));
  }, [key]);
  const open = (iri) => iri && setKey(iri.split("/").pop());
  const byProduct = Object.values(lineage.reduce((m, l) => { (m[l.graph] ||= { ...l, triples: 0 }).triples += Number(l.triples); return m; }, {}));

  return (
    <div>
      <div className="view-head"><h1>Supplier 360</h1><p>Ownership, awards, sanction leads and data sources for one company.</p></div>
      <div className="split">
        <section className="panel finder">
          <input aria-label="Search suppliers" placeholder={isStatic ? "Filter by name" : "Search by legal name"} value={q} onChange={(e) => { setQ(e.target.value); search(e.target.value); }} />
          <div className="results">
            {hits.map((h) => (
              <button key={h.key} aria-current={h.key === key} onClick={() => setKey(h.key)}>
                <span className="nm">{h.name}</span><span className="sub">{[h.country, `${h.awards} ${h.awards === 1 ? "award" : "awards"}`].filter(Boolean).join(", ")}</span>
              </button>
            ))}
            {!hits.length && <div className="empty">{isStatic ? "No match." : "Type at least two characters."}</div>}
          </div>
        </section>
        <section className="panel">
          {err && <div className="alert err" style={{ margin: 16 }}>{err}</div>}
          {!d && !err && <div className="empty">Select a company to see its profile.</div>}
          {d && (
            <>
              <div className="dossier-head">
                <div style={{ flex: 1 }}>
                  <h2>{d.name}</h2>
                  <div className="muted">{[d.types.filter((t) => t !== "LegalEntity").join(", "), d.country].filter(Boolean).join(" in ")} <span className="faint">&nbsp;LEI&nbsp;</span><span className="mono">{d.lei || "not recorded"}</span></div>
                  {d.recorded_names.length > 0 && <div className="faint small" style={{ marginTop: 4 }}>Also recorded as {d.recorded_names.join("; ")}</div>}
                </div>
                <a className="link small" href={`/api/entities/${key}?format=jsonld`} target="_blank" rel="noreferrer" style={{ display: isStatic ? "none" : "block" }}>JSON-LD</a>
              </div>
              {d.exposure_flags.length > 0 && (
                <div className="pad">
                  <div className="alert">
                    <b>Possible sanction exposure, to be reviewed</b>
                    {d.exposure_flags.map((f, i) => (
                      <div key={i} style={{ marginTop: 4 }}>{f.hops === 0 ? "The company itself" : <>Parent <b>{f.vname}</b>, {f.hops} {f.hops === 1 ? "step" : "steps"} up the ownership chain,</>} resembles list entry <b>{f.ename}</b> (name similarity {Number(f.score).toFixed(2)}, status {f.status}).</div>
                    ))}
                    <div className="small muted" style={{ marginTop: 6 }}>{d.note}</div>
                  </div>
                </div>
              )}
              <dl className="facts" style={{ margin: 0 }}>
                <div><dt>Awards won</dt><dd>{d.awards.count}</dd></div>
                <div><dt>Awarded value</dt><dd>{money(d.awards.total_value)} <small>currencies not converted</small></dd></div>
                <div><dt>Tenders issued</dt><dd>{d.tenders_issued}</dd></div>
              </dl>
              <div className="pad" style={{ borderBottom: "1px solid var(--line)" }}>
                <div className="sect"><h3>Ownership chain</h3><Ladder d={d} /></div>
                {d.children.length > 0 && <p className="small muted" style={{ marginBottom: 0 }}>Subsidiaries: {d.children.map((c, i) => <span key={i}>{i > 0 && ", "}<a className="link" onClick={() => open(c.c)}>{c.name}</a></span>)}</p>}
              </div>
              <div className="body2">
                <div>
                  <div className="sect"><h3>Connections within two steps</h3><GraphView data={graph} onNodeClick={(n) => open(n.id)} height={360} /></div>
                </div>
                <div className="stack">
                  <div className="sect"><h3>Product categories</h3>
                    <ul className="plain">{d.categories.map((c, i) => <li key={i}>{c.label || c.code} <span className="faint small mono">&nbsp;{c.code}</span><span className="faint small"> &middot; {c.n}</span></li>)}{d.categories.length === 0 && <li className="muted">None linked</li>}</ul></div>
                  <div className="sect"><h3>Buyers</h3>
                    <ul className="plain">{d.buyers.map((b, i) => <li key={i}><a className="link" onClick={() => open(b.b)}>{b.name}</a> <span className="faint small">&middot; {b.n} {b.n === 1 ? "award" : "awards"}</span></li>)}{d.buyers.length === 0 && <li className="muted">None</li>}</ul></div>
                </div>
              </div>
              <div style={{ borderTop: "1px solid var(--line)" }}>
                <div className="body2">
                  <div className="sect"><h3>Contracts</h3>
                    <table><thead><tr><th>Date</th><th>Tender</th><th>Buyer</th><th className="num">Value</th></tr></thead>
                      <tbody>{contracts.slice(0, 12).map((c, i) => <tr key={i}><td className="mono" style={{ whiteSpace: "nowrap" }}>{c.date}</td><td>{c.title}</td><td>{c.bname}</td><td className="num" style={{ whiteSpace: "nowrap" }}>{money(c.amount)} {c.currency}</td></tr>)}</tbody></table></div>
                  <div className="sect"><h3>Where this record comes from</h3>
                    <table><thead><tr><th>Data product</th><th className="num">Facts</th></tr></thead>
                      <tbody>{byProduct.map((l, i) => <tr key={i}><td>{l.product}<div className="faint small">{l.source_note}</div></td><td className="num">{l.triples}</td></tr>)}</tbody></table></div>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
