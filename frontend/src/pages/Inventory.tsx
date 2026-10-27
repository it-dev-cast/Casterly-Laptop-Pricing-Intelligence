import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, download } from "../api";
import { Link } from "react-router-dom";
import { TemplateButton } from "../components/TemplateDownload";
import { Card, Drawer, Empty, ErrorBox, Grade, Loading, PageHead, StatusBadge, Synthetic, VerdictBadge } from "../components/ui";
import { useApp, useLoad } from "../context";
import { inr, inrShort, num, pct } from "../format";
import type { InventoryItem } from "../types";

interface LotSummary {
  id: number; lot_ref: string; supplier: string | null; is_synthetic: boolean; lines: number; units: number;
  lines_valued: number; lines_with_buy_price: number; recommended_buy_total: number | null; max_safe_buy_total: number | null;
  expected_contribution_total: number | null; total_lot_value: number | null; asking_total: number | null; note: string;
}

const NEW_FIELDS: [string, string, string?][] = [
  ["brand", "Brand *"], ["model", "Model *"], ["cpu", "Exact CPU", "e.g. i5-8350U"], ["ram_gb", "RAM (GB)"],
  ["storage_gb", "Storage (GB)"], ["storage_type", "Storage type", "SSD / HDD"], ["condition_grade", "Grade", "A+, A, B, C, D"],
  ["battery_health_pct", "Battery health %"], ["faults", "Faults", "'none' or e.g. display lines; keyboard"],
  ["charger_included", "Charger", "yes / no"], ["warranty_months", "Warranty (months)"], ["quantity", "Quantity *"],
  ["asking_price", "Supplier asking / unit"], ["asking_tax_basis", "Asking tax basis", "inclusive / exclusive"],
  ["refurbishment_cost", "Refurb cost / unit", "blank = unknown, 0 = none"], ["intended_channel", "Channel", "retail / wholesale / as_is"],
  ["target_margin_pct", "Target margin %"], ["expected_yield_pct", "Saleable yield %"], ["lot_ref", "Lot reference"],
  ["item_ref", "SKU / item ref"], ["region", "Location"],
];

export default function Inventory() {
  const { view, can, toast } = useApp();
  const nav = useNavigate();
  const synth = view === "demo";
  const [q, setQ] = useState("");
  const [lot, setLot] = useState<number | null>(null);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const items = useLoad(() => api.get<InventoryItem[]>(`/api/inventory?synthetic=${synth}${q ? `&q=${encodeURIComponent(q)}` : ""}${lot ? `&lot_id=${lot}` : ""}`), [synth, q, lot]);
  const lots = useLoad(() => api.get<LotSummary[]>("/api/lots"), [synth]);
  const myLots = (lots.data ?? []).filter((l) => l.is_synthetic === synth);

  const value = async (ids: number[], lotId?: number) => {
    setBusy(true);
    try {
      const r = await api.post<{ id: number }[]>("/api/valuations", lotId ? { lot_id: lotId } : { inventory_item_ids: ids });
      toast(`${r.length} valuation snapshot(s) created.`);
      setSel(new Set());
      items.reload();
      lots.reload();
      if (r.length === 1) nav(`/valuations/${r[0].id}`);
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  const all = items.data ?? [];
  const toggle = (id: number) => {
    const s = new Set(sel);
    if (s.has(id)) s.delete(id);
    else s.add(id);
    setSel(s);
  };

  return (
    <div className="stack fade-in">
      <PageHead title="Inventory & lots" sub="Every line priced from evidence. Select lines or a whole lot and run a valuation; each run is stored as an immutable snapshot."
        actions={<>
          <button className="btn" onClick={() => download(`/api/exports/valuations?format=xlsx&synthetic=${synth}${lot ? `&lot_id=${lot}` : ""}`, "valuations.xlsx")}>Export Excel</button>
          <button className="btn" onClick={() => download(`/api/exports/valuations?format=csv&synthetic=${synth}${lot ? `&lot_id=${lot}` : ""}`, "valuations.csv")}>CSV</button>
          {can("import_inventory") && !synth && <TemplateButton recordType="inventory" label="Inventory template" />}
          {can("import_inventory") && !synth && <Link className="btn" to="/import">Upload stock list</Link>}
          {can("edit_inventory") && !synth && <button className="btn" onClick={() => setAdding(true)}>Add item</button>}
          {can("run_valuation") && <button className="btn primary" disabled={busy || sel.size === 0} onClick={() => value([...sel])}>
            {busy ? <span className="spin" /> : `Value ${sel.size || ""} selected`}
          </button>}
        </>} />

      {myLots.length > 0 && (
        <div className="grid g3">
          {myLots.map((l) => {
            const gap = l.asking_total != null && l.recommended_buy_total != null ? l.asking_total - l.recommended_buy_total : null;
            return (
              <div key={l.id} className="card kpi accent" style={{ outline: lot === l.id ? "2px solid var(--brand)" : "none" }}>
                <div className="row">
                  <div className="label">Lot {l.lot_ref}</div>
                  <Synthetic on={l.is_synthetic} />
                  <div className="spacer" />
                  <button className="btn sm ghost" onClick={() => setLot(lot === l.id ? null : l.id)}>{lot === l.id ? "Show all" : "Filter"}</button>
                </div>
                <div className="value sm">{inrShort(l.recommended_buy_total)} <span className="muted small" style={{ fontWeight: 500 }}>recommended</span></div>
                <div className="small">
                  {l.lines} lines · {num(l.units)} units · {l.lines_with_buy_price}/{l.lines} with a buy price
                  {gap != null && <> · ask {inrShort(l.asking_total)} ({gap > 0 ? <span style={{ color: "var(--bad)" }}>{inrShort(gap)} over</span> : <span style={{ color: "var(--good)" }}>within</span>})</>}
                </div>
                <div className="row" style={{ marginTop: 6 }}>
                  <span className="small muted">Contribution {inrShort(l.expected_contribution_total)} · value {inrShort(l.total_lot_value)}</span>
                  <div className="spacer" />
                  {can("run_valuation") && <button className="btn sm" disabled={busy} onClick={() => value([], l.id)}>Value lot</button>}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <Card tight title={<input placeholder="Search brand, model, CPU or SKU" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 320 }} />}>
        {items.error && <ErrorBox error={items.error} />}
        {items.loading && !items.data ? <Loading /> : all.length === 0 ? (
          <Empty>No {synth ? "synthetic demo" : ""} inventory. Upload a stock list from <a href="/import">Upload & review</a>.</Empty>
        ) : (
          <div className="tablewrap">
            <table className="t">
              <thead>
                <tr>
                  <th><input type="checkbox" checked={sel.size === all.length} onChange={(e) => setSel(e.target.checked ? new Set(all.map((i) => i.id)) : new Set())} /></th>
                  <th>Item</th><th className="num">Qty</th><th>Faults</th><th className="num">Ask / unit</th><th>Status</th><th>Evidence</th>
                  <th className="num">Expected sale</th><th className="num">Recommended buy</th><th className="num">Max safe</th><th className="num">Margin</th><th>Ask verdict</th>
                </tr>
              </thead>
              <tbody>
                {all.map((i) => {
                  const v = i.latest_valuation;
                  return (
                    <tr key={i.id} className={sel.has(i.id) ? "sel" : ""}>
                      <td><input type="checkbox" checked={sel.has(i.id)} onChange={() => toggle(i.id)} /></td>
                      <td>
                        <div className="row" style={{ gap: 6 }}><b>{i.brand} {i.model}</b><Synthetic on={i.is_synthetic} /></div>
                        <div className="small muted">
                          {[i.cpu, i.ram_gb != null ? `${i.ram_gb} GB` : "RAM ?", i.storage_gb != null ? `${i.storage_gb} GB ${i.storage_type ?? ""}` : "storage ?", i.condition_grade ? `Grade ${i.condition_grade}` : "grade ?"].join(" · ")}
                        </div>
                        <div className="tiny muted">{i.item_ref}{i.lot_ref ? ` · lot ${i.lot_ref}` : ""}</div>
                      </td>
                      <td className="num">{num(i.quantity)}</td>
                      <td className="small">{i.faults == null ? <span className="muted">unknown</span> : i.faults.length ? i.faults.join("; ") : "none"}</td>
                      <td className="num">{inr(i.asking_price)}<div className="tiny muted">{i.asking_price != null ? i.asking_tax_basis : ""}</div></td>
                      <td><StatusBadge status={v?.status} /></td>
                      <td><Grade g={v?.rating} /></td>
                      <td className="num">{inr(v?.selling_p50)}</td>
                      <td className="num"><b>{inr(v?.recommended_buy)}</b>{v?.flags.includes("negative_ceiling") && <div className="tiny" style={{ color: "var(--bad)" }}>negative ceiling</div>}</td>
                      <td className="num">{inr(v?.max_safe_buy)}</td>
                      <td className="num">{pct(v?.expected_margin)}</td>
                      <td>
                        <VerdictBadge v={v?.asking_verdict} />
                        {v && <div><a className="tiny" href={`/valuations/${v.id}`} onClick={(e) => { e.preventDefault(); nav(`/valuations/${v.id}`); }}>Open valuation →</a></div>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {adding && <AddItem onClose={() => setAdding(false)} onSaved={() => { setAdding(false); items.reload(); lots.reload(); }} />}
    </div>
  );
}

function AddItem({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const { toast } = useApp();
  const [v, setV] = useState<Record<string, string>>({ intended_channel: "retail", asking_tax_basis: "exclusive", quantity: "1" });
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    try {
      await api.post("/api/inventory", { values: Object.fromEntries(Object.entries(v).filter(([, x]) => x !== "")) });
      toast("Item added.");
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <Drawer title="Add inventory item" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" onClick={save}>Add item</button></>}>
      <div className="stack">
        <div className="small muted">Leave a field blank if it is unknown. Enter 0 only when the value really is zero.</div>
        <ErrorBox error={err} />
        <div className="formgrid">
          {NEW_FIELDS.map(([k, label, hint]) => (
            <label key={k} className="field">{label}{hint && <span className="hint">{hint}</span>}
              <input value={v[k] ?? ""} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
            </label>
          ))}
        </div>
      </div>
    </Drawer>
  );
}
