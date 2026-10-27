import { useState } from "react";
import { api, download } from "../api";
import { Icon } from "../components/Icons";
import { TemplateButton } from "../components/TemplateDownload";
import { Card, Drawer, Empty, ErrorBox, Loading, PageHead, Synthetic } from "../components/ui";
import { useApp, useLoad } from "../context";
import { date, inr } from "../format";

type Kind = "transactions" | "listings" | "quotes";
const TEMPLATE_KEY: Record<Kind, string> = { transactions: "transaction", listings: "listing", quotes: "quote" };
interface Rec {
  id: number; label: string; brand: string; model: string; cpu: string | null; ram_gb: number | null; storage_gb: number | null;
  condition_grade: string | null; price: number | null; currency: string | null; tax_basis: string; channel: string | null;
  seller: string | null; counterparty?: string | null; platform: string | null; source_url: string | null; source_document: string | null;
  source_record_id: string | null; source_type: string; availability: string | null; kind?: string; listing_date?: string;
  quote_date?: string; transaction_date?: string; valid_until?: string | null; observed_at: string | null; is_synthetic: boolean;
  age_days: number | null; stale: boolean | null; stale_limit_days?: number; corrections: Record<string, unknown> | null;
}

const TABS: { key: Kind; label: string; note: string }[] = [
  { key: "transactions", label: "Completed sales & purchases", note: "Realised prices. Completed sales are the primary basis for expected selling prices." },
  { key: "listings", label: "Advertised listings", note: "Asking prices. Used for listing-price guidance; never treated as completed sales." },
  { key: "quotes", label: "Supplier quotations", note: "As-is procurement prices. Shown beside buy prices; never used for selling prices." },
];

const FORM: Record<Kind, [string, string, string?][]> = {
  transactions: [["kind", "Type *", "sale / purchase"], ["transaction_date", "Date *", "YYYY-MM-DD or DD/MM/YYYY"], ["price", "Unit price *"],
    ["tax_basis", "Tax basis", "inclusive / exclusive"], ["channel", "Channel", "retail / wholesale / as_is (required for sales)"], ["quantity", "Quantity"],
    ["counterparty", "Counterparty"], ["source_record_id", "Invoice / reference"], ["fees_paid", "Fees paid / unit"]],
  listings: [["price", "Asking price *"], ["listing_date", "Listing date *"], ["channel", "Channel *", "retail / wholesale / as_is"],
    ["tax_basis", "Tax basis", "inclusive / exclusive / unknown"], ["seller", "Seller"], ["platform", "Platform / site"],
    ["source_url", "Source URL", "only a real URL you observed"], ["source_record_id", "Listing ID"], ["availability", "Availability", "in_stock / out_of_stock / sold"], ["title", "Listing title"]],
  quotes: [["seller", "Supplier *"], ["price", "Quoted unit price *"], ["quote_date", "Quote date *"], ["valid_until", "Valid until"],
    ["tax_basis", "Tax basis", "inclusive / exclusive"], ["source_record_id", "Quote reference"], ["quantity_available", "Quantity available"], ["moq", "MOQ"]],
};
const SPEC: [string, string, string?][] = [["brand", "Brand *"], ["model", "Model *"], ["cpu", "Exact CPU", "e.g. i5-8350U"], ["ram_gb", "RAM (GB)"],
  ["storage_gb", "Storage (GB)"], ["storage_type", "Storage type"], ["condition_grade", "Grade"], ["battery_health_pct", "Battery %"],
  ["charger_included", "Charger", "yes / no"], ["warranty_months", "Warranty (months)"], ["region", "Region"]];

export default function Evidence() {
  const { view, can } = useApp();
  const synth = view === "demo";
  const [tab, setTab] = useState<Kind>("transactions");
  const [q, setQ] = useState("");
  const [channel, setChannel] = useState("");
  const [txn, setTxn] = useState("");
  const [adding, setAdding] = useState(false);
  const data = useLoad(() => api.get<Rec[]>(`/api/evidence/${tab}?synthetic=${synth}${q ? `&q=${encodeURIComponent(q)}` : ""}${channel ? `&channel=${channel}` : ""}${txn && tab === "transactions" ? `&txn_kind=${txn}` : ""}`), [tab, synth, q, channel, txn]);
  const rows = data.data ?? [];
  const canAdd = tab === "listings" ? can("add_listing") : tab === "quotes" ? can("edit_evidence") : can("record_sale") || can("record_purchase");
  const stale = rows.filter((r) => r.stale).length;

  return (
    <div className="stack fade-in">
      <PageHead title="Market evidence" sub="Every observation the engine can draw on, with its source, date, tax basis and freshness. Evidence types are stored separately and never pooled."
        actions={<>
          <button className="btn" onClick={() => download(`/api/evidence/${tab}/export?format=xlsx&synthetic=${synth}`, `${tab}.xlsx`)}>Export Excel</button>
          <button className="btn" onClick={() => download(`/api/evidence/${tab}/export?format=csv&synthetic=${synth}`, `${tab}.csv`)}>CSV</button>
          {can("import_evidence") && !synth && <TemplateButton recordType={TEMPLATE_KEY[tab]} label="Upload template" />}
          {canAdd && !synth && <button className="btn primary" onClick={() => setAdding(true)}>Add manually</button>}
        </>} />
      <div className="tabs">{TABS.map((t) => <button key={t.key} className={tab === t.key ? "on" : ""} onClick={() => setTab(t.key)}>{t.label}</button>)}</div>
      <div className="banner info small">{TABS.find((t) => t.key === tab)!.note}{stale > 0 && <> · <b>{stale}</b> record(s) shown are older than the freshness limit and are excluded from valuations as stale.</>}</div>
      <Card tight title={<div className="row wrap">
        <input placeholder="Search brand, model, CPU, seller" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 260 }} />
        {tab !== "quotes" && <select value={channel} onChange={(e) => setChannel(e.target.value)}><option value="">All channels</option><option>retail</option><option>wholesale</option><option value="as_is">as-is</option></select>}
        {tab === "transactions" && <select value={txn} onChange={(e) => setTxn(e.target.value)}><option value="">Sales and purchases</option><option value="sale">Sales</option><option value="purchase">Purchases</option></select>}
        <span className="muted small">{rows.length} records</span>
      </div>}>
        <ErrorBox error={data.error} />
        {data.loading && !data.data ? <Loading /> : !rows.length ? <Empty>No {synth ? "synthetic" : "real"} records of this type yet.</Empty> : (
          <div className="tablewrap" style={{ maxHeight: "70vh" }}>
            <table className="t">
              <thead><tr><th>Date</th>{tab === "transactions" && <th>Type</th>}<th>Laptop</th><th className="num">Price</th><th>Tax</th><th>Channel</th><th>Seller / party</th><th>Source</th><th>Freshness</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="nowrap small">{date(r.transaction_date ?? r.listing_date ?? r.quote_date)}{r.valid_until && <div className="tiny muted">valid to {date(r.valid_until)}</div>}</td>
                    {tab === "transactions" && <td><span className={`badge ${r.kind === "sale" ? "good" : "info"}`}>{r.kind}</span></td>}
                    <td>
                      <div className="small"><b>{r.brand} {r.model}</b> <Synthetic on={r.is_synthetic} /></div>
                      <div className="tiny muted">{[r.cpu ?? "CPU ?", r.ram_gb != null ? `${r.ram_gb}GB` : "RAM ?", r.storage_gb != null ? `${r.storage_gb}GB` : "storage ?", r.condition_grade ? `Grade ${r.condition_grade}` : "grade ?"].join(" · ")}</div>
                      {r.corrections && <div className="tiny" style={{ color: "var(--warn)" }}>corrected: {Object.keys(r.corrections).join(", ")}</div>}
                    </td>
                    <td className="num">{inr(r.price)}<div className="tiny muted">{r.currency}</div></td>
                    <td className="small">{r.tax_basis}</td>
                    <td className="small">{r.channel ?? "—"}{r.availability && <div className="tiny muted">{r.availability.replace(/_/g, " ")}</div>}</td>
                    <td className="small">{r.counterparty ?? r.seller ?? <span className="muted">unknown</span>}{r.platform && <div className="tiny muted">{r.platform}</div>}</td>
                    <td className="small" style={{ maxWidth: 260 }}>
                      <span className="badge">{r.source_type}</span>{" "}
                      {r.source_url ? <a href={r.source_url} target="_blank" rel="noopener noreferrer nofollow" className="tiny">link <Icon.external /></a> : null}
                      <div className="tiny muted">{r.source_document}</div>
                      {r.source_record_id && <div className="tiny muted mono">{r.source_record_id}</div>}
                    </td>
                    <td>{r.age_days == null ? "—" : r.stale ? <span className="badge warn" title={`Limit ${r.stale_limit_days} days`}>stale · {r.age_days} d</span> : <span className="badge good">{r.age_days} d</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {adding && <AddEvidence kind={tab} onClose={() => setAdding(false)} onSaved={() => { setAdding(false); data.reload(); }} />}
    </div>
  );
}

function AddEvidence({ kind, onClose, onSaved }: { kind: Kind; onClose: () => void; onSaved: () => void }) {
  const { toast } = useApp();
  const [v, setV] = useState<Record<string, string>>({ currency: "INR" });
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    try {
      const r = await api.post<{ warnings: { message: string }[] }>(`/api/evidence/${kind}`, { values: Object.fromEntries(Object.entries(v).filter(([, x]) => x !== "")) });
      toast(r.warnings.length ? `Saved with ${r.warnings.length} warning(s): ${r.warnings[0].message}` : "Evidence saved.");
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <Drawer title={`Add ${TABS.find((t) => t.key === kind)!.label.toLowerCase()}`} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" onClick={save}>Save evidence</button></>}>
      <div className="stack">
        <div className="small muted">Blank means unknown. Record the price exactly as observed and state its tax basis; the engine normalises it. Only enter a source URL you actually visited.</div>
        <ErrorBox error={err} />
        <h3>Price & provenance</h3>
        <div className="formgrid">{FORM[kind].map(([k, l, h]) => <label key={k} className="field">{l}{h && <span className="hint">{h}</span>}<input value={v[k] ?? ""} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></label>)}</div>
        <h3>Laptop specification</h3>
        <div className="formgrid">{SPEC.map(([k, l, h]) => <label key={k} className="field">{l}{h && <span className="hint">{h}</span>}<input value={v[k] ?? ""} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></label>)}</div>
      </div>
    </Drawer>
  );
}
