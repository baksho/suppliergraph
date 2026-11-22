import React, { useEffect, useRef } from "react";
import cytoscape from "cytoscape";

const COLORS = { Supplier: "#1d5fd1", Buyer: "#1f7a4d", LegalEntity: "#7a869a", Tender: "#c27d0e", Award: "#8a6d3b",
  ProductCategory: "#6b4fbb", SanctionEntry: "#b4410e", ExposureFlag: "#b4410e", Country: "#2b8aa0", Obligation: "#a23b72" };

export default function GraphView({ data, onNodeClick, height = 420 }) {
  const ref = useRef(null);
  const cyRef = useRef(null);
  useEffect(() => {
    if (!ref.current || !data) return;
    const els = [
      ...data.nodes.map((n) => ({ data: { ...n } })),
      ...data.edges.map((e, i) => ({ data: { id: `e${i}`, ...e } })),
    ];
    const cy = cytoscape({
      container: ref.current, elements: els,
      style: [
        { selector: "node", style: { label: (n) => (["Award", "Tender"].includes(n.data("type")) && !n.data("seed") ? "" : n.data("label")), "font-size": 10, "text-wrap": "ellipsis", "text-max-width": 110, "text-valign": "bottom", "text-margin-y": 4, "min-zoomed-font-size": 6,
            "background-color": (n) => COLORS[n.data("type")] || "#aab5c8", width: 24, height: 24, "border-width": 2, "border-color": "#ffffff", color: "#172033" } },
        { selector: "node[?seed]", style: { width: 34, height: 34, "border-width": 4, "border-color": "#9db8ea" } },
        { selector: "edge", style: { width: 1.2, "line-color": "#c7d0e3", "target-arrow-color": "#aab5c8",
            "target-arrow-shape": "triangle", "curve-style": "bezier", label: "" } },
      ],
      layout: { name: "cose", animate: false, nodeRepulsion: 22000, idealEdgeLength: 110, nodeOverlap: 20, gravity: 0.3 },
    });
    cy.on("tap", "node", (ev) => onNodeClick && onNodeClick(ev.target.data()));
    cyRef.current = cy;
    return () => cy.destroy();
  }, [data]);
  if (!data) return null;
  return (
    <div>
      <div ref={ref} style={{ height, border: "1px solid #dde2ea", borderRadius: 4, background: "#fbfcfd" }} />
      <div className="legend">{Object.entries(COLORS).map(([k, c]) => <span key={k}><i style={{ background: c }} />{k}</span>)}</div>
    </div>
  );
}
