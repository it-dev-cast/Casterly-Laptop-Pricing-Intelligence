import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, Empty, ErrorBox, Loading, PageHead, Synthetic } from "../components/ui";
import { useApp, useLoad } from "../context";
import { date, inr } from "../format";
import type { InventoryItem, ValuationSummary } from "../types";

interface Outcome {
  id: number; label: string; kind: string; transaction_date: string; price: number; tax_basis: string; quantity: number | null;
  channel: string | null; counterparty: string | null; inventory_item_id: number; valuation: ValuationSummary | null;
  predicted: number | null; actual_comparable: number | null; difference: number | null; within_p25_p75: boolean | null; is_synthetic: boolean;
}

export default function Outcomes() {
  const { view, can, toast } = useApp();
  const synth = view === "demo";
  const items = useLoad(() => api.get<InventoryItem[]>(`/api/inventory?synthetic=${synth}`), [synth]);
  const outcomes = useLoad(() => api.get<Outcome[]>("/api/outcomes"), [synth]);
  const [f, setF] = useState<Record<string, string>>({ kind: "sale", tax_basis: "inclusive", quantity: "1", transaction_date: new Date().toISOString().slice(0, 10) });
  const [err, setErr] = useState<string | null>(null);
  const allowed = f.kind === "sale" ? can("record_sale") : can("record_purchase");

  const save = async () => {
    setErr(null);
    try {
      await api.post("/api/outcomes", { ...f, inventory_item_id: Number(f.inventory_item_id) });
      toast("Outcome recorded and linked to the latest valuation.");
      setF({ ...f, price: "", counterparty: "", reference: "" });
      outcomes.reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const list = (outcomes.data ?? []).filter((o) => o.is_synthetic === synth);

  return (
    <div className="stack fade-in">
      <PageHead title="Transaction outcomes" sub="Record what an item actually sold or was bought for. Outcomes become completed-sales evidence and are compared with the valuation that was current at the time." />
      <Card title="Record an outcome">
        <ErrorBox error={err} />
        <div className="formgrid">
          <label className="field">Inventory item *
            <select value={f.inventory_item_id ?? ""} onChange={(e) => setF({ ...f, inventory_item_id: e.target.value })}>
              <option value="">Select…</option>
              {(items.data ?? []).map((i) => <option key={i.id} value={i.id}>{i.item_ref ? `${i.item_ref} · ` : ""}{i.brand} {i.model}{i.ram_gb ? ` ${i.ram_gb}GB` : ""}</option>)}
            </select></label>
          <label className="field">Type<select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="sale">Sale</option><option value="purchase">Purchase</option></select></label>
          <label className="field">Unit price *<input value={f.price ?? ""} onChange={(e) => setF({ ...f, price: e.target.value })} /></label>
          <label className="field">Tax basis<select value={f.tax_basis} onChange={(e) => setF({ ...f, tax_basis: e.target.value })}><option>inclusive</option><option>exclusive</option></select></label>
          <label className="field">Date *<input type="date" value={f.transaction_date} onChange={(e) => setF({ ...f, transaction_date: e.target.value })} /></label>
          <label className="field">Quantity<input value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value })} /></label>
          <label className="field">Channel<span className="hint">defaults to the item's channel</span><select value={f.channel ?? ""} onChange={(e) => setF({ ...f, channel: e.target.value })}><option value="">—</option><option>retail</option><option>wholesale</option><option value="as_is">as-is</option></select></label>
          <label className="field">Counterparty<input value={f.counterparty ?? ""} onChange={(e) => setF({ ...f, counterparty: e.target.value })} /></label>
          <label className="field">Invoice / reference<input value={f.reference ?? ""} onChange={(e) => setF({ ...f, reference: e.target.value })} /></label>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn primary" disabled={!f.inventory_item_id || !f.price || !allowed} onClick={save}>Record outcome</button>
          {!allowed && <span className="small muted">Your role cannot record {f.kind}s.</span>}
        </div>
      </Card>
      <Card title="Outcomes against predictions" tight>
        {outcomes.loading && !outcomes.data ? <Loading /> : !list.length ? <Empty>No outcomes recorded yet.</Empty> : (
          <div className="tablewrap">
            <table className="t">
              <thead><tr><th>Date</th><th>Item</th><th>Type</th><th className="num">Actual</th><th className="num">Predicted</th><th className="num">Difference</th><th>In P25–P75?</th><th>Valuation</th></tr></thead>
              <tbody>
                {list.map((o) => (
                  <tr key={o.id}>
                    <td className="small nowrap">{date(o.transaction_date)}</td>
                    <td className="small">{o.label} <Synthetic on={o.is_synthetic} /></td>
                    <td><span className={`badge ${o.kind === "sale" ? "good" : "info"}`}>{o.kind}</span></td>
                    <td className="num">{inr(o.actual_comparable)}<div className="tiny muted">{o.kind === "sale" ? "incl. GST" : "purchase basis"}</div></td>
                    <td className="num">{inr(o.predicted)}<div className="tiny muted">{o.kind === "sale" ? "expected sale" : "recommended buy"}</div></td>
                    <td className="num" style={{ color: o.difference == null ? undefined : o.difference >= 0 ? "var(--good)" : "var(--bad)" }}>{o.difference == null ? "—" : `${o.difference >= 0 ? "+" : ""}${inr(o.difference)}`}</td>
                    <td>{o.within_p25_p75 == null ? "—" : o.within_p25_p75 ? <span className="badge good">yes</span> : <span className="badge warn">no</span>}</td>
                    <td>{o.valuation ? <Link to={`/valuations/${o.valuation.id}`}>#{o.valuation.id}</Link> : <span className="muted small">none at the time</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
