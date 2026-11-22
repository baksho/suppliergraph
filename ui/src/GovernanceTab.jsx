import React, { useEffect, useState } from "react";
import { api } from "./api.js";

const Status = ({ ok, children }) => <span className="status"><span className={`dot ${ok ? "" : "bad"}`} />{children}</span>;

export default function GovernanceTab() {
  const [shacl, setShacl] = useState(null);
  const [dq, setDq] = useState(null);
  const [er, setEr] = useState(null);
  const [products, setProducts] = useState([]);
  const [err, setErr] = useState(null);
  useEffect(() => {
    api.shacl().then(setShacl).catch((e) => setErr(e.message));
    api.dq().then(setDq).catch((e) => setErr(e.message));
    api.er().then(setEr).catch((e) => setErr(e.message));
    api.products().then(setProducts).catch((e) => setErr(e.message));
  }, []);
  return (
    <div>
      <div className="view-head"><h1>Data quality</h1><p>Schema validation, consistency checks, matching results and the data products behind the graph.</p></div>
      {err && <div className="alert err">{err}</div>}
      <div className="stack">
        <section className="panel"><h3>Checks</h3>
          <table><thead><tr><th>Check</th><th>Result</th><th className="num">Findings</th></tr></thead><tbody>
            {shacl && <tr><td>Schema rules (SHACL)</td><td><Status ok={shacl.conforms}>{shacl.conforms ? "Passed" : "Violations found"}</Status></td><td className="num">{shacl.violations} violations, {shacl.warnings} warnings</td></tr>}
            {dq && Object.entries(dq.checks).map(([k, v]) => <tr key={k}><td>{k.replaceAll("_", " ")}</td><td><Status ok={v.length === 0}>{v.length === 0 ? "Passed" : "Review"}</Status></td><td className="num">{v.length}</td></tr>)}
          </tbody></table>
          {shacl?.samples?.length > 0 && <div className="pad"><pre className="code">{JSON.stringify(shacl.samples, null, 2)}</pre></div>}
        </section>
        <section className="panel"><h3>Company matching</h3>
          {er?.parties?.length > 0 ? (
            <table><thead><tr><th>Outcome</th><th>Method</th><th className="num">Parties</th></tr></thead><tbody>{er.parties.map((r, i) => <tr key={i}><td>{r.status}</td><td>{r.method}</td><td className="num">{r.n}</td></tr>)}</tbody></table>
          ) : <div className="empty">{er?.staging_unavailable ? "The staging database is not available here." : "No matching results yet."}</div>}
          <div className="pad small muted" style={{ borderTop: "1px solid var(--line)" }}>Accuracy is measured on companies that publish an LEI, which is easier than the typical record. Treat it as an upper bound.</div>
        </section>
        <section className="panel"><h3>Data products</h3>
          <table><thead><tr><th>Name</th><th>Description</th><th>Source and licence note</th></tr></thead><tbody>{products.map((p, i) => <tr key={i}><td><b>{p.title}</b></td><td>{p.description}</td><td className="small muted">{p.note}</td></tr>)}</tbody></table>
        </section>
      </div>
    </div>
  );
}
