import React, { useEffect, useState } from "react";
import { api, isStatic } from "./api.js";
import GraphView from "./GraphView.jsx";

const LIVE_EXAMPLES = ["Which suppliers won the most awards?", "Which suppliers are flagged for possible sanction exposure through a parent company?", "Which obligations apply to suppliers?"];
const MODES = { graphrag: "Graph and documents", vector_rag: "Documents only", llm_only: "Model only, no retrieval" };

export default function AskTab() {
  const examples = isStatic ? window.SG_STATIC.ask.map((a) => a.question).slice(0, 6) : LIVE_EXAMPLES;
  const [question, setQuestion] = useState(examples[0]);
  const [mode, setMode] = useState("graphrag");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const go = async (qq = question) => {
    setBusy(true); setErr(null);
    try { setRes(await api.ask(qq, mode)); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  useEffect(() => { if (isStatic) go(); }, []);
  const g = res?.grounding || {};
  const issues = ["invalid_citations", "unsupported_numbers", "unsupported_entities"].filter((k) => g[k]?.length > 0);
  return (
    <div>
      <div className="view-head"><h1>Ask the graph</h1><p>Questions are turned into SPARQL, run against the knowledge graph, and answered with the rows they return.</p></div>
      <div className="askbar">
        <input aria-label="Question" value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => e.key === "Enter" && go()} />
        {!isStatic && <select aria-label="Retrieval mode" value={mode} onChange={(e) => setMode(e.target.value)}>{Object.entries(MODES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>}
        <button className="btn" onClick={() => go()} disabled={busy}>{busy ? "Asking" : "Ask"}</button>
      </div>
      <div className="suggest">{examples.map((e) => <button key={e} onClick={() => { setQuestion(e); go(e); }}>{e}</button>)}</div>
      {err && <div className="alert err">{err}</div>}
      {res && (
        <>
          <p className="answer">{res.text}</p>
          {!isStatic && (
            <p>
              <span className={`tag ${g.grounded ? "ok" : "warn"}`}>{g.grounded ? "Checks passed" : "Check findings"}</span>{" "}
              {g.citation_coverage != null && <span className="muted small">Citation coverage {Math.round(g.citation_coverage * 100)}%. These checks look for missing citations, numbers and names; they do not prove an answer is correct.</span>}
            </p>
          )}
          {issues.map((k) => <div key={k} className="alert err small" style={{ marginBottom: 8 }}>{k.replaceAll("_", " ")}: {g[k].join(", ")}</div>)}
          <div className="twocol">
            <div className="stack">
              <section className="panel"><h3>{isStatic ? "Recorded query" : "Generated query"}</h3><div className="pad"><pre className="code">{res.sparql}</pre>{res.attempts?.length > 1 && <p className="muted small">Needed {res.attempts.length} attempts before the query validated.</p>}</div></section>
            </div>
            <section className="panel"><h3>Rows returned</h3>
              <ul className="ev">{Object.entries(res.evidence || {}).map(([k, v]) => <li key={k}><b>{k}</b>{v}</li>)}</ul>
              {!Object.keys(res.evidence || {}).length && <div className="empty">The query returned no rows.</div>}
            </section>
          </div>
          {!isStatic && res.graph?.nodes?.length > 0 && <section className="panel" style={{ marginTop: 20 }}><h3>Graph context</h3><div className="pad"><GraphView data={res.graph} /></div></section>}
        </>
      )}
    </div>
  );
}
