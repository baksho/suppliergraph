import React, { useEffect, useState } from "react";
import { api, isStatic } from "./api.js";
import AskTab from "./AskTab.jsx";
import SupplierTab from "./SupplierTab.jsx";
import DiscoverTab from "./DiscoverTab.jsx";
import GovernanceTab from "./GovernanceTab.jsx";

const I = (d) => <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>;
const VIEWS = {
  ask: ["Ask the graph", AskTab, I(<><path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z" /></>)],
  supplier: ["Supplier 360", SupplierTab, I(<><circle cx="8" cy="8" r="2" /><circle cx="3" cy="3.5" r="1.3" /><circle cx="13" cy="4" r="1.3" /><circle cx="12" cy="13" r="1.3" /><path d="M6.5 6.8 4 4.5M9.8 7l2.2-2M9 9.6l2.2 2.4" /></>)],
  discover: ["Find suppliers", DiscoverTab, I(<><circle cx="7" cy="7" r="4" /><path d="m10 10 3.5 3.5" /></>)],
  gov: ["Data quality", GovernanceTab, I(<><path d="M8 2 3 4v4c0 3 2 5 5 6 3-1 5-3 5-6V4z" /><path d="m6 8 1.5 1.5L10.5 6.5" /></>)],
};

export default function App() {
  const fromHash = () => (VIEWS[location.hash.slice(1)] ? location.hash.slice(1) : "supplier");
  const [view, setView] = useState(fromHash());
  useEffect(() => { const f = () => setView(fromHash()); window.addEventListener("hashchange", f); return () => window.removeEventListener("hashchange", f); }, []);
  const [health, setHealth] = useState(null);
  useEffect(() => { api.health().then(setHealth).catch((e) => setHealth({ error: e.message })); }, []);
  const View = VIEWS[view][1];
  return (
    <div className="shell">
      <nav className="rail" aria-label="Views">
        <div className="brand">
          <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true"><g stroke="#6ea2ff" strokeWidth="1.6" fill="none"><path d="M12 6 5.5 17M12 6l6.5 11M5.5 17h13" /></g><g fill="#fff"><circle cx="12" cy="6" r="3" /><circle cx="5.5" cy="17" r="3" /><circle cx="18.5" cy="17" r="3" /></g></svg>
          <span>SupplierGraph</span>
        </div>
        {Object.entries(VIEWS).map(([k, [label, , icon]]) => (
          <button key={k} aria-current={view === k ? "page" : undefined} onClick={() => { location.hash = k; setView(k); }}>{icon}{label}</button>
        ))}
        <div className="foot">
          {health?.error ? "API unreachable" : health ? <>{health.triples.toLocaleString()} triples<br />{isStatic ? "Static snapshot" : `Store: ${health.store}`}</> : "Connecting"}
        </div>
      </nav>
      <div className="main">
        {isStatic && <div className="notice"><b>Demo with fictional test data.</b> It runs without a server or an LLM, and Ask replays recorded queries. None of the names or numbers are real.</div>}
        <main className="view"><View /></main>
      </div>
    </div>
  );
}
