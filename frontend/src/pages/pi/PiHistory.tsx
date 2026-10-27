import { useState } from "react";
import { api } from "../../api";
import { Card, Empty, ErrorBox, Loading, PageHead } from "../../components/ui";
import { useApp, useLoad } from "../../context";
import { date, dateTime, inr } from "../../format";
import { ExtLink, Field, usePiMeta } from "./shared";
import type { PiEstimate, PiObservation } from "./types";
import { n } from "./types";

interface Prod { id: number; label: string; category: string; product_key: string; observations: number; latest_estimate: PiEstimate | null }
interface Outcome { id: number; kind: string; unit_price: string; quantity: number; outcome_date: string; vendor: string | null; condition: string | null; notes: string | null }
interface Detail { product: { id: number; label: string; category: string; spec: Record<string, unknown> }; estimates: PiEstimate[]; observations: PiObservation[]; outcomes: Outcome[] }

export default function PiHistory() {
  const meta = usePiMeta();
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [sel, setSel] = useState<number | null>(null);
  const prods = useLoad(() => api.get<Prod[]>(`/api/pi/products?${new URLSearchParams({ ...(q ? { q } : {}), ...(cat ? { category: cat } : {}) })}`), [q, cat]);
  return (
    <div className="stack fade-in">
      <PageHead title="Price history" sub="Every normalised product keeps its estimates, observed market prices and actual purchase/resale outcomes across valuations." />
      <div className="grid g2" style={{ alignItems: "start" }}>
        <Card tight title={<div className="row" style={{ gap: 8 }}>
          <input placeholder="Search products" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search products" />
          <select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Category"><option value="">All categories</option>{Object.entries(meta.data?.categories ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        </div>}>
          {prods.loading && !prods.data ? <Loading /> : (prods.data ?? []).length === 0 ? <Empty>No products yet.</Empty> : (
            <div className="tablewrap" style={{ maxHeight: 640, overflow: "auto" }}>
              <table className="t"><thead><tr><th>Product</th><th className="num">Evidence</th><th className="num">Latest price</th></tr></thead>
                <tbody>{prods.data!.map((p) => (
                  <tr key={p.id} className={`clickable ${sel === p.id ? "sel" : ""}`} onClick={() => setSel(p.id)}>
                    <td><b>{p.label}</b><div className="tiny muted">{meta.data?.categories[p.category] ?? p.category}</div></td>
                    <td className="num">{p.observations}</td><td className="num">{inr(n(p.latest_estimate?.recommended_unit ?? null))}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </Card>
        {sel ? <ProductHistory id={sel} /> : <Card><Empty>Select a product.</Empty></Card>}
      </div>
      <Accuracy />
    </div>
  );
}

function ProductHistory({ id }: { id: number }) {
  const { can, toast } = useApp();
  const meta = usePiMeta();
  const d = useLoad(() => api.get<Detail>(`/api/pi/products/${id}`), [id]);
  const [f, setF] = useState({ kind: "purchase", unit_price: "", quantity: "1", outcome_date: new Date().toISOString().slice(0, 10), vendor: "", condition: "" });
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    try {
      await api.post("/api/pi/outcomes", { ...f, product_id: id, quantity: Number(f.quantity) || 1, vendor: f.vendor || null, condition: f.condition || null });
      toast("Outcome recorded.");
      setF({ ...f, unit_price: "" });
      d.reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  if (d.loading && !d.data) return <Loading />;
  if (d.error) return <ErrorBox error={d.error} />;
  const x = d.data!;
  return (
    <div className="stack">
      <Card title={x.product.label}>
        <h3 className="small">Estimates</h3>
        {x.estimates.length === 0 ? <div className="small muted">Never priced.</div> : (
          <table className="t"><thead><tr><th>As of</th><th>Batch</th><th>Grade</th><th className="num">Benchmark</th><th className="num">Recommended</th><th>Confidence</th><th>Status</th></tr></thead>
            <tbody>{x.estimates.map((e) => <tr key={e.id}><td className="small">{dateTime(e.as_of)}</td><td>#{e.batch_id}</td><td>{e.grade || "—"}</td><td className="num">{inr(n(e.benchmark))}</td><td className="num"><b>{inr(n(e.recommended_unit))}</b></td><td className="small">{e.confidence ?? "—"}</td><td className="small">{e.status}{e.is_current ? "" : " (superseded)"}</td></tr>)}</tbody>
          </table>
        )}
        <h3 className="small" style={{ marginTop: 14 }}>Observed market prices</h3>
        {x.observations.length === 0 ? <div className="small muted">No evidence.</div> : (
          <table className="t"><thead><tr><th>Observed</th><th>Type</th><th className="num">Price</th><th>Source</th><th>Status</th></tr></thead>
            <tbody>{x.observations.slice(0, 100).map((o) => <tr key={o.id}><td className="small">{date(o.observed_at)}</td><td className="small">{meta.data?.price_types[o.price_type] ?? o.price_type}</td>
              <td className="num">{inr(n(o.price))}<div className="tiny muted">{o.tax_basis}</div></td><td className="small">{o.url ? <ExtLink href={o.url} /> : (o.seller ?? o.provider)}</td><td className="small">{o.status}</td></tr>)}</tbody>
          </table>
        )}
        <h3 className="small" style={{ marginTop: 14 }}>Actual outcomes</h3>
        {x.outcomes.length === 0 ? <div className="small muted">No recorded purchases or resales.</div> : (
          <table className="t"><thead><tr><th>Date</th><th>Kind</th><th className="num">Unit price</th><th className="num">Qty</th><th>Vendor</th></tr></thead>
            <tbody>{x.outcomes.map((o) => <tr key={o.id}><td className="small">{date(o.outcome_date)}</td><td>{o.kind}</td><td className="num">{inr(n(o.unit_price))}</td><td className="num">{o.quantity}</td><td className="small">{o.vendor ?? "—"}</td></tr>)}</tbody>
          </table>
        )}
      </Card>
      {can("pi_outcomes") && (
        <Card title="Record actual outcome">
          <ErrorBox error={err} />
          <div className="formgrid">
            <Field label="Kind"><select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="purchase">Purchase (from vendor)</option><option value="resale">Resale</option></select></Field>
            <Field label="Unit price (₹, ex-GST)"><input inputMode="decimal" value={f.unit_price} onChange={(e) => setF({ ...f, unit_price: e.target.value })} /></Field>
            <Field label="Quantity"><input inputMode="numeric" value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value })} /></Field>
            <Field label="Date"><input type="date" value={f.outcome_date} onChange={(e) => setF({ ...f, outcome_date: e.target.value })} /></Field>
            <Field label="Vendor / buyer"><input value={f.vendor} onChange={(e) => setF({ ...f, vendor: e.target.value })} /></Field>
            <Field label="Condition"><input value={f.condition} onChange={(e) => setF({ ...f, condition: e.target.value })} /></Field>
          </div>
          <div className="small muted" style={{ marginTop: 6 }}>A purchase is also stored as verified-transaction evidence for future valuations.</div>
          <div className="row" style={{ marginTop: 8 }}><div className="spacer" /><button className="btn primary" disabled={!f.unit_price} onClick={save}>Record</button></div>
        </Card>
      )}
    </div>
  );
}

interface Metrics { n: number; mae: number | null; mape: number | null; median_ape: number | null; bias_pct: number | null }
interface Acc { purchase: { overall: Metrics; by_category: Record<string, Metrics> }; resale: { overall: Metrics; by_category: Record<string, Metrics> }; note: string;
  suggestions: { category: string; price_type: string; current: string; proposed: string; median_bias_pct: number; n: number; reason: string }[] }

export function Accuracy() {
  const a = useLoad(() => api.get<Acc>("/api/pi/accuracy"), []);
  if (!a.data) return null;
  const rows = (k: "purchase" | "resale"): [string, Metrics][] => [["All categories", a.data![k].overall], ...Object.entries(a.data![k].by_category)];
  return (
    <Card title="Prediction accuracy (recorded outcomes)">
      <div className="small muted" style={{ marginBottom: 8 }}>{a.data.note}</div>
      <div className="grid g2">
        {(["purchase", "resale"] as const).map((k) => (
          <div key={k}>
            <h3 className="small">{k === "purchase" ? "Recommended buy vs actual purchase" : "Expected resale vs actual resale"}</h3>
            {a.data![k].overall.n === 0 ? <div className="small muted">No outcomes recorded yet.</div> : (
              <table className="t"><thead><tr><th>Category</th><th className="num">n</th><th className="num">MAE</th><th className="num">MAPE</th><th className="num">Bias</th></tr></thead>
                <tbody>{rows(k).map(([c, m]) => <tr key={c}><td>{c}</td><td className="num">{m.n}</td><td className="num">{inr(m.mae)}</td><td className="num">{m.mape == null ? "—" : `${m.mape}%`}</td><td className="num">{m.bias_pct == null ? "—" : `${m.bias_pct > 0 ? "+" : ""}${m.bias_pct}%`}</td></tr>)}</tbody>
              </table>
            )}
          </div>
        ))}
      </div>
      {a.data.suggestions.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <h3 className="small">Suggested rule adjustments (require administrator approval in Pricing Rules)</h3>
          <ul className="small">{a.data.suggestions.map((s, i) => <li key={i}><b>{s.category}</b> · {s.price_type}: conversion {s.current} → {s.proposed}. {s.reason}.</li>)}</ul>
        </div>
      )}
    </Card>
  );
}
