import { useEffect, useState } from "react";
import { api } from "../../api";
import { Card, ErrorBox, Loading, PageHead } from "../../components/ui";
import { useApp, useLoad } from "../../context";
import { dateTime } from "../../format";
import { Field } from "./shared";

type V = string | number | null;
interface Band { min_qty: number; max_qty: number | null; discount_pct: V }
interface Cat { label: string; keywords: string[]; conversion: Record<string, V>; grade_adjustment_pct: Record<string, V>; quantity_bands: Band[];
  resale_realisation: Record<string, V>; purchase_cost_per_unit: V; min_margin_pct: V; opening_discount_pct: V; large_lot_threshold: number | null }
interface Rules {
  name: string; gst_pct: V; half_life_days: number; prefer_top_tier: boolean; max_total_discount_pct: V; provisional_max_age_days: number;
  freshness_days: Record<string, number>; rounding: { step: V; mode: string }; categories: Record<string, Cat>;
  risk_rules: { flag: string; label: string; group: string; discount_pct: V }[];
  research: { auto_accept_confirmed: boolean; auto_accept_identical: boolean; queries_per_product: number; max_results_per_query: number; cache_days: number; max_attempts: number; concurrency: number };
  quantity_columns: string[]; [k: string]: unknown;
}
interface Version { id: number; version: number; name: string; note: string | null; is_active: boolean; hash: string; created_at: string }
interface Res { active: Version & { rules: Rules }; gaps: { category: string; item: string; detail: string }[]; price_types: Record<string, string>; versions: Version[] }

const num = (v: string): V => (v.trim() === "" ? null : v.trim());
const show = (v: V | undefined) => (v === null || v === undefined ? "" : String(v));

export default function PiRules() {
  const { can, toast } = useApp();
  const r = useLoad(() => api.get<Res>("/api/pi/rules"), []);
  const [rules, setRules] = useState<Rules | null>(null);
  const [cat, setCat] = useState("server_ram");
  const [note, setNote] = useState("");
  const [json, setJson] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ro = !can("pi_rules");
  useEffect(() => {
    if (r.data) setRules(structuredClone(r.data.active.rules));
  }, [r.data]);
  if (r.loading && !r.data) return <Loading />;
  if (r.error || !r.data) return <ErrorBox error={r.error} />;
  if (!rules) return <Loading />;
  const up = (fn: (x: Rules) => void) => { const c = structuredClone(rules); fn(c); setRules(c); };
  const c = rules.categories[cat];
  const pts = r.data.price_types;

  const save = async () => {
    setErr(null);
    try {
      const body = json !== null ? JSON.parse(json) : rules;
      await api.post("/api/pi/rules", { rules: body, note, activate: true });
      toast("New rules version saved and activated. Recalculate batches to apply it.");
      setNote("");
      setJson(null);
      r.reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const act = async (path: string, msg: string) => {
    try {
      await api.post(path);
      toast(msg);
      r.reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <div className="stack fade-in">
      <PageHead title="Pricing rules & configuration" sub={<>Active: <b>v{r.data.active.version}</b> · {r.data.active.name}. Every save creates a new version; each estimate records the version it used. Blank = not configured (no value is invented).</>}
        actions={!ro && <>
          <button className="btn" onClick={() => act("/api/pi/rules/presets/historical_reference", "Historical-reference preset saved as an inactive version.")}>Add historical reference preset</button>
          <button className="btn" onClick={() => setJson(json === null ? JSON.stringify(rules, null, 2) : null)}>{json === null ? "Advanced (JSON)" : "Structured editor"}</button>
        </>} />
      <ErrorBox error={err} />
      {typeof rules.policy_basis === "string" && <div className="banner info">{rules.policy_basis}</div>}
      {r.data.gaps.length > 0 && <div className="banner warn"><div><b>{r.data.gaps.length} configuration gaps.</b> Unconfigured retail/second-hand conversions mean listings cannot become buy prices; unconfigured adjustments apply 0%.</div></div>}
      {json !== null ? (
        <Card title="Rules JSON"><textarea className="mono" style={{ width: "100%", minHeight: 520, fontSize: 12 }} value={json} onChange={(e) => setJson(e.target.value)} readOnly={ro} /></Card>
      ) : (
        <>
          <Card title="General">
            <div className="formgrid">
              <Field label="Rule set name"><input disabled={ro} value={rules.name} onChange={(e) => up((x) => (x.name = e.target.value))} /></Field>
              <Field label="GST %" hint="confirm with your tax advisor"><input disabled={ro} value={show(rules.gst_pct)} onChange={(e) => up((x) => (x.gst_pct = num(e.target.value)))} /></Field>
              <Field label="Rounding step (₹)"><input disabled={ro} value={show(rules.rounding.step)} onChange={(e) => up((x) => (x.rounding.step = num(e.target.value)))} /></Field>
              <Field label="Rounding mode"><select disabled={ro} value={rules.rounding.mode} onChange={(e) => up((x) => (x.rounding.mode = e.target.value))}><option value="down">down (conservative)</option><option value="nearest">nearest</option></select></Field>
              <Field label="Max combined discount %" hint="blank = no cap"><input disabled={ro} value={show(rules.max_total_discount_pct)} onChange={(e) => up((x) => (x.max_total_discount_pct = num(e.target.value)))} /></Field>
              <Field label="Recency half-life (days)"><input disabled={ro} value={rules.half_life_days} onChange={(e) => up((x) => (x.half_life_days = Number(e.target.value) || 60))} /></Field>
              <Field label="Historical evidence max age (days)"><input disabled={ro} value={rules.provisional_max_age_days} onChange={(e) => up((x) => (x.provisional_max_age_days = Number(e.target.value) || 0))} /></Field>
              <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}><input type="checkbox" disabled={ro} checked={rules.prefer_top_tier} onChange={(e) => up((x) => (x.prefer_top_tier = e.target.checked))} />Prefer buy-side evidence when present</label>
            </div>
            <h3 className="small" style={{ margin: "14px 0 6px" }}>Freshness window per evidence type (days)</h3>
            <div className="formgrid">{Object.keys(pts).map((t) => (
              <Field key={t} label={pts[t]}><input disabled={ro} value={rules.freshness_days[t] ?? ""} onChange={(e) => up((x) => (x.freshness_days[t] = Number(e.target.value) || 0))} /></Field>
            ))}</div>
          </Card>
          <Card title={<div className="row" style={{ gap: 8 }}><h2>Category rules</h2>
            <select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Category">{Object.entries(rules.categories).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></div>}>
            <div className="grid g2">
              <div>
                <h3 className="small">Source-type conversion to buy price (× ex-GST price)</h3>
                <table className="t"><tbody>{Object.keys(pts).map((t) => (
                  <tr key={t}><td className="small">{pts[t]}</td><td style={{ width: 120 }}><input disabled={ro} style={{ width: 100 }} value={show(c.conversion[t])} placeholder="not set"
                    onChange={(e) => up((x) => (x.categories[cat].conversion[t] = num(e.target.value)))} /></td></tr>
                ))}</tbody></table>
                <div className="tiny muted">Example: 0.55 converts a refurbished retail asking price into a wholesale buy benchmark. Set from your own purchase history.</div>
              </div>
              <div>
                <h3 className="small">Condition / grade adjustment (% discount)</h3>
                <table className="t"><tbody>{Object.keys(c.grade_adjustment_pct).map((g) => (
                  <tr key={g}><td>Grade {g}</td><td style={{ width: 120 }}><input disabled={ro} style={{ width: 100 }} value={show(c.grade_adjustment_pct[g])} placeholder="not set"
                    onChange={(e) => up((x) => (x.categories[cat].grade_adjustment_pct[g] = num(e.target.value)))} /></td></tr>
                ))}</tbody></table>
                <h3 className="small" style={{ marginTop: 12 }}>Quantity bands (% discount)</h3>
                <table className="t"><tbody>{c.quantity_bands.map((b, i) => (
                  <tr key={i}><td>{b.min_qty}–{b.max_qty ?? "∞"} units</td><td style={{ width: 120 }}><input disabled={ro} style={{ width: 100 }} value={show(b.discount_pct)} placeholder="not set"
                    onChange={(e) => up((x) => (x.categories[cat].quantity_bands[i].discount_pct = num(e.target.value)))} /></td></tr>
                ))}</tbody></table>
              </div>
            </div>
            <h3 className="small" style={{ margin: "14px 0 6px" }}>Resale & margin</h3>
            <div className="formgrid">
              {Object.keys(c.resale_realisation).map((t) => (
                <Field key={t} label={`Resale realisation from ${pts[t]}`} hint="× ex-GST asking price"><input disabled={ro} value={show(c.resale_realisation[t])} placeholder="not set"
                  onChange={(e) => up((x) => (x.categories[cat].resale_realisation[t] = num(e.target.value)))} /></Field>
              ))}
              <Field label="Purchase-related cost / unit (₹)" hint="logistics, testing, QC"><input disabled={ro} value={show(c.purchase_cost_per_unit)} onChange={(e) => up((x) => (x.categories[cat].purchase_cost_per_unit = num(e.target.value)))} /></Field>
              <Field label="Minimum margin %"><input disabled={ro} value={show(c.min_margin_pct)} onChange={(e) => up((x) => (x.categories[cat].min_margin_pct = num(e.target.value)))} /></Field>
              <Field label="Negotiation opening discount %"><input disabled={ro} value={show(c.opening_discount_pct)} onChange={(e) => up((x) => (x.categories[cat].opening_discount_pct = num(e.target.value)))} /></Field>
              <Field label="Large-lot flag threshold (units)"><input disabled={ro} value={c.large_lot_threshold ?? ""} onChange={(e) => up((x) => (x.categories[cat].large_lot_threshold = e.target.value ? Number(e.target.value) : null))} /></Field>
              <Field label="Detection keywords" hint="comma-separated"><input disabled={ro} value={c.keywords.join(", ")} onChange={(e) => up((x) => (x.categories[cat].keywords = e.target.value.split(",").map((s) => s.trim()).filter(Boolean)))} /></Field>
            </div>
          </Card>
          <Card title="Risk adjustments" tight>
            <table className="t"><thead><tr><th>Risk</th><th>Flag</th><th>Group (never stacks)</th><th>Discount %</th></tr></thead>
              <tbody>{rules.risk_rules.map((rr, i) => (
                <tr key={rr.flag}><td>{rr.label}</td><td className="mono small">{rr.flag}</td><td className="small">{rr.group}</td>
                  <td><input disabled={ro} style={{ width: 100 }} value={show(rr.discount_pct)} placeholder="not set" onChange={(e) => up((x) => (x.risk_rules[i].discount_pct = num(e.target.value)))} /></td></tr>
              ))}</tbody>
            </table>
          </Card>
          <Card title="Market research">
            <div className="formgrid">
              <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}><input type="checkbox" disabled={ro} checked={rules.research.auto_accept_confirmed}
                onChange={(e) => up((x) => (x.research.auto_accept_confirmed = e.target.checked))} />Automatically validate exact confirmed product offers (never snippets alone)</label>
              <Field label="Queries per product"><input disabled={ro} value={rules.research.queries_per_product} onChange={(e) => up((x) => (x.research.queries_per_product = Number(e.target.value) || 1))} /></Field>
              <Field label="Results per query"><input disabled={ro} value={rules.research.max_results_per_query} onChange={(e) => up((x) => (x.research.max_results_per_query = Number(e.target.value) || 10))} /></Field>
              <Field label="Cache (days)"><input disabled={ro} value={rules.research.cache_days} onChange={(e) => up((x) => (x.research.cache_days = Number(e.target.value) || 0))} /></Field>
              <Field label="Max attempts"><input disabled={ro} value={rules.research.max_attempts} onChange={(e) => up((x) => (x.research.max_attempts = Number(e.target.value) || 1))} /></Field>
              <Field label="Concurrency"><input disabled={ro} value={rules.research.concurrency} onChange={(e) => up((x) => (x.research.concurrency = Number(e.target.value) || 1))} /></Field>
              <Field label="Quantity column names" hint="comma-separated, priority order"><input disabled={ro} value={rules.quantity_columns.join(", ")} onChange={(e) => up((x) => (x.quantity_columns = e.target.value.split(",").map((s) => s.trim()).filter(Boolean)))} /></Field>
            </div>
          </Card>
        </>
      )}
      {!ro && (
        <div className="row" style={{ gap: 8 }}>
          <input placeholder="What changed and why (required)" value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1 }} aria-label="Change note" />
          <button className="btn" onClick={() => { setRules(structuredClone(r.data!.active.rules)); setJson(null); }}>Discard</button>
          <button className="btn primary" disabled={note.trim().length < 3} onClick={save}>Save as new version</button>
        </div>
      )}
      <Card title="Versions" tight>
        <table className="t"><thead><tr><th>Version</th><th>Name</th><th>Note</th><th>Created</th><th /></tr></thead>
          <tbody>{r.data.versions.map((v) => (
            <tr key={v.id}><td><b>v{v.version}</b> {v.is_active && <span className="badge good">active</span>}</td><td className="small">{v.name}</td><td className="small">{v.note}</td><td className="small">{dateTime(v.created_at)}</td>
              <td>{!v.is_active && !ro && <button className="btn sm" onClick={() => act(`/api/pi/rules/versions/${v.id}/activate`, `v${v.version} activated.`)}>Activate</button>}</td></tr>
          ))}</tbody>
        </table>
      </Card>
    </div>
  );
}
