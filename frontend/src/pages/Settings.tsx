import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, ErrorBox, Loading, PageHead } from "../components/ui";
import { useApp, useLoad } from "../context";
import { dateTime } from "../format";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Cfg = any;

const DIMENSIONS: [string, string][] = [
  ["cpu_key", "CPU"], ["ram_gb", "RAM (GB)"], ["storage_gb", "Storage (GB)"], ["storage_type", "Storage type"],
  ["condition_grade", "Condition grade"], ["gpu_key", "GPU"], ["display_size_in", "Display size"],
  ["display_resolution", "Resolution"], ["charger_included", "Charger (yes/no)"], ["warranty_months", "Warranty (months)"],
];

/** Number input where blank means "not configured" (null), distinct from an explicit 0. */
function Num({ value, onChange, disabled, step = "any", w = 110 }: { value: number | null | undefined; onChange: (v: number | null) => void; disabled?: boolean; step?: string; w?: number }) {
  const [text, setText] = useState(value == null ? "" : String(value));
  useEffect(() => setText(value == null ? "" : String(value)), [value]);
  return (
    <input type="number" step={step} disabled={disabled} className={value == null ? "unset" : ""} placeholder="not set" style={{ width: w }}
      value={text} onChange={(e) => { setText(e.target.value); onChange(e.target.value === "" ? null : Number(e.target.value)); }} />
  );
}

export default function Settings() {
  const { can, toast } = useApp();
  const editable = can("edit_settings");
  const s = useLoad(() => api.get<{ version: number; note: string | null; created_at: string; hash: string; config: Cfg }>("/api/settings/pricing"), []);
  const versions = useLoad(() => api.get<{ id: number; version: number; note: string | null; is_active: boolean; created_at: string; hash: string }[]>("/api/settings/pricing/versions"), []);
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (s.data) setCfg(structuredClone(s.data.config)); }, [s.data]);
  if (s.loading && !s.data) return <Loading />;
  if (!cfg) return <ErrorBox error={s.error} />;

  const up = (fn: (c: Cfg) => void) => { const c = structuredClone(cfg); fn(c); setCfg(c); };
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.put<{ version: number }>("/api/settings/pricing", { config: cfg, note: note || null });
      toast(`Saved as settings version ${r.version}. Existing valuations keep the version they used.`);
      setNote("");
      s.reload();
      versions.reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const dis = !editable;

  return (
    <div className="stack fade-in">
      <PageHead title="Cost & margin settings"
        sub={<>Version {s.data!.version} · {dateTime(s.data!.created_at)}{s.data!.note ? ` · “${s.data!.note}”` : ""}. Every valuation records the exact settings it used. Striped fields are not configured: the engine reports them, it never invents a value.</>}
        actions={editable ? <>
          <input placeholder="What changed and why" value={note} onChange={(e) => setNote(e.target.value)} style={{ width: 260 }} />
          <button className="btn primary" disabled={busy} onClick={save}>{busy ? <span className="spin" /> : "Save new version"}</button>
        </> : <span className="badge">Read-only for your role</span>} />
      <ErrorBox error={err} />

      <div className="grid g2">
        <Card title="Margin & tax">
          <div className="formgrid">
            <label className="field">Default target margin %<span className="hint">contribution ÷ sale revenue</span><Num disabled={dis} value={cfg.default_target_margin_pct} onChange={(v) => up((c) => (c.default_target_margin_pct = v))} /></label>
            <label className="field">Minimum margin for safe ceiling %<span className="hint">at the P25 sale price; 0 = break-even</span><Num disabled={dis} value={cfg.minimum_margin_pct_for_ceiling} onChange={(v) => up((c) => (c.minimum_margin_pct_for_ceiling = v ?? 0))} /></label>
            <label className="field">Default channel<select disabled={dis} value={cfg.default_channel} onChange={(e) => up((c) => (c.default_channel = e.target.value))}><option>retail</option><option>wholesale</option><option value="as_is">as_is</option></select></label>
            <label className="field">Tax mode<span className="hint">how output GST is computed</span>
              <select disabled={dis} value={cfg.tax.mode} onChange={(e) => up((c) => (c.tax.mode = e.target.value))}>
                <option value="standard">Standard GST (ITC on purchases)</option><option value="margin_scheme">Margin scheme (GST on margin)</option><option value="none">Not charging GST</option>
              </select></label>
            <label className="field">GST rate %<Num disabled={dis} value={cfg.tax.gst_rate_pct} onChange={(v) => up((c) => (c.tax.gst_rate_pct = v ?? 0))} /></label>
            <label className="field" style={{ gridColumn: "1 / -1" }}>Basis for the GST rate<input disabled={dis} value={cfg.tax.gst_rate_basis} onChange={(e) => up((c) => (c.tax.gst_rate_basis = e.target.value))} /></label>
          </div>
          <h3 style={{ margin: "16px 0 8px" }}>Evidence with unknown tax basis</h3>
          <div className="formgrid">
            {Object.keys(cfg.tax.unknown_tax_basis).map((k) => (
              <label key={k} className="field">{k}
                <select disabled={dis} value={cfg.tax.unknown_tax_basis[k]} onChange={(e) => up((c) => (c.tax.unknown_tax_basis[k] = e.target.value))}>
                  <option value="exclude">Exclude</option><option value="assume_inclusive">Assume GST-inclusive</option><option value="assume_exclusive">Assume GST-exclusive</option>
                </select></label>
            ))}
          </div>
        </Card>
        <Card title="Per-purchased-unit costs">
          <CostRows rows={cfg.fixed_costs_per_purchased_unit} dis={dis} onChange={(rows) => up((c) => (c.fixed_costs_per_purchased_unit = rows))} unit="INR / purchased unit" />
          <h3 style={{ margin: "16px 0 8px" }}>FX rates to INR</h3>
          <div className="small muted">Evidence in other currencies is excluded unless a rate is set here.</div>
          <textarea disabled={dis} rows={2} style={{ width: "100%", marginTop: 6 }} placeholder="USD=83.2"
            value={Object.entries(cfg.fx_rates_to_inr).map(([k, v]) => `${k}=${v}`).join("\n")}
            onChange={(e) => up((c) => (c.fx_rates_to_inr = Object.fromEntries(e.target.value.split("\n").map((l) => l.split("=")).filter((p) => p.length === 2 && p[0].trim() && !isNaN(Number(p[1]))).map(([k, v]) => [k.trim().toUpperCase(), Number(v)]))))} />
          <h3 style={{ margin: "16px 0 8px" }}>Condition grade scale</h3>
          <input disabled={dis} style={{ width: "100%" }} value={cfg.grade_scale.join(", ")} onChange={(e) => up((c) => (c.grade_scale = e.target.value.split(",").map((x: string) => x.trim()).filter(Boolean)))} />
        </Card>
      </div>

      <Card title="Selling channels: fees, costs and asking-price conversion">
        <div className="grid g3">
          {Object.entries(cfg.channels).map(([ch, cc]: [string, any]) => (
            <div key={ch} className="card" style={{ padding: 14 }}>
              <h3 style={{ textTransform: "capitalize", marginBottom: 8 }}>{ch.replace("_", "-")}</h3>
              <div className="small muted">Percentage fees</div>
              {cc.percentage_fees.map((f: any, i: number) => (
                <div key={i} className="row" style={{ margin: "6px 0" }}>
                  <input disabled={dis} value={f.name} style={{ flex: 1 }} onChange={(e) => up((c) => (c.channels[ch].percentage_fees[i].name = e.target.value))} />
                  <Num disabled={dis} w={70} value={f.rate_pct} onChange={(v) => up((c) => (c.channels[ch].percentage_fees[i].rate_pct = v))} />%
                  <select disabled={dis} value={f.base} onChange={(e) => up((c) => (c.channels[ch].percentage_fees[i].base = e.target.value))}>
                    <option value="gross_incl_tax">of incl-GST</option><option value="net_ex_tax">of ex-GST</option>
                  </select>
                  {!dis && <button className="btn sm ghost" onClick={() => up((c) => c.channels[ch].percentage_fees.splice(i, 1))}>✕</button>}
                </div>
              ))}
              {!dis && <button className="btn sm" onClick={() => up((c) => c.channels[ch].percentage_fees.push({ name: "New fee", rate_pct: null, base: "gross_incl_tax" }))}>+ fee</button>}
              <div className="small muted" style={{ marginTop: 12 }}>Per-sold-unit costs (INR, ex-GST)</div>
              <CostRows rows={cc.fixed_costs_per_sold_unit} dis={dis} onChange={(rows) => up((c) => (c.channels[ch].fixed_costs_per_sold_unit = rows))} unit="" />
              <div className="small muted" style={{ marginTop: 12 }}>Asking-to-sale ratio <span className="tiny">(blank = asking prices never stand in for sales)</span></div>
              <div className="row" style={{ marginTop: 4 }}>
                <Num disabled={dis} w={90} step="0.01" value={cc.asking_to_sale_ratio} onChange={(v) => up((c) => (c.channels[ch].asking_to_sale_ratio = v))} />
                <input disabled={dis} placeholder="basis / evidence for the ratio" style={{ flex: 1 }} value={cc.asking_to_sale_ratio_basis ?? ""} onChange={(e) => up((c) => (c.channels[ch].asking_to_sale_ratio_basis = e.target.value || null))} />
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Fault categories: yield, repair and salvage" tight>
        <div className="tablewrap">
          <table className="t">
            <thead><tr><th>Key</th><th>Label</th><th>Expected saleable yield %</th><th>Repair cost / unit</th><th>Salvage / unsold unit</th><th>Keywords (derive category from fault text)</th><th /></tr></thead>
            <tbody>
              {cfg.fault_categories.map((f: any, i: number) => (
                <tr key={i}>
                  <td><input disabled={dis} value={f.key} style={{ width: 120 }} onChange={(e) => up((c) => (c.fault_categories[i].key = e.target.value))} /></td>
                  <td><input disabled={dis} value={f.label} onChange={(e) => up((c) => (c.fault_categories[i].label = e.target.value))} /></td>
                  <td><Num disabled={dis} value={f.expected_yield_pct} onChange={(v) => up((c) => (c.fault_categories[i].expected_yield_pct = v))} /></td>
                  <td><Num disabled={dis} value={f.repair_cost_per_unit} onChange={(v) => up((c) => (c.fault_categories[i].repair_cost_per_unit = v))} /></td>
                  <td><Num disabled={dis} value={f.salvage_value_per_unit} onChange={(v) => up((c) => (c.fault_categories[i].salvage_value_per_unit = v))} /></td>
                  <td><input disabled={dis} style={{ width: "100%" }} value={f.match_keywords.join(", ")} onChange={(e) => up((c) => (c.fault_categories[i].match_keywords = e.target.value.split(",").map((x: string) => x.trim()).filter(Boolean)))} /></td>
                  <td>{!dis && <button className="btn sm ghost" onClick={() => up((c) => c.fault_categories.splice(i, 1))}>✕</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="row" style={{ padding: 12 }}>
          {!dis && <button className="btn sm" onClick={() => up((c) => c.fault_categories.push({ key: "new", label: "New category", expected_yield_pct: null, repair_cost_per_unit: null, salvage_value_per_unit: null, match_keywords: [] }))}>+ category</button>}
          <span className="small muted">An item's own yield, repair cost and salvage take precedence. With no yield anywhere, no buying price is produced: the app does not assume every unit sells.</span>
        </div>
      </Card>

      <Card title="Configuration adjustments (broadening beyond exact matches)" tight>
        <div className="banner warn" style={{ margin: 12 }}>
          None ship by default. A rule lets a comparable with a different configuration be used, adjusted by the stated amount, only when exact matches are too few. Uncalibrated rules are flagged on every valuation that uses them.
        </div>
        <div className="tablewrap">
          <table className="t">
            <thead><tr><th>Rule id</th><th>Dimension</th><th>Comparable has</th><th>Subject has</th><th>Method</th><th>Value</th><th>Symmetric</th><th>Calibrated</th><th>Basis / evidence</th><th /></tr></thead>
            <tbody>
              {cfg.adjustments.map((a: any, i: number) => (
                <tr key={i}>
                  <td><input disabled={dis} style={{ width: 110 }} value={a.id} onChange={(e) => up((c) => (c.adjustments[i].id = e.target.value))} /></td>
                  <td><select disabled={dis} value={a.dimension} onChange={(e) => up((c) => (c.adjustments[i].dimension = e.target.value))}>{DIMENSIONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></td>
                  <td><input disabled={dis} style={{ width: 90 }} value={a.comparable_value} onChange={(e) => up((c) => (c.adjustments[i].comparable_value = e.target.value))} /></td>
                  <td><input disabled={dis} style={{ width: 90 }} value={a.subject_value} onChange={(e) => up((c) => (c.adjustments[i].subject_value = e.target.value))} /></td>
                  <td><select disabled={dis} value={a.method} onChange={(e) => up((c) => (c.adjustments[i].method = e.target.value))}><option value="percent">% of price</option><option value="amount">INR amount</option></select></td>
                  <td><Num disabled={dis} w={90} value={a.value} onChange={(v) => up((c) => (c.adjustments[i].value = v ?? 0))} /></td>
                  <td><input type="checkbox" disabled={dis} checked={a.symmetric} onChange={(e) => up((c) => (c.adjustments[i].symmetric = e.target.checked))} /></td>
                  <td><input type="checkbox" disabled={dis} checked={a.calibrated} onChange={(e) => up((c) => (c.adjustments[i].calibrated = e.target.checked))} /></td>
                  <td><input disabled={dis} style={{ width: 220 }} value={a.basis} onChange={(e) => up((c) => (c.adjustments[i].basis = e.target.value))} /></td>
                  <td>{!dis && <button className="btn sm ghost" onClick={() => up((c) => c.adjustments.splice(i, 1))}>✕</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {cfg.adjustments.length === 0 && <div className="empty">No adjustment rules: valuations use exact and unverified matches only.</div>}
        </div>
        {!dis && <div style={{ padding: 12 }}><button className="btn sm" onClick={() => up((c) => c.adjustments.push({ id: `rule-${c.adjustments.length + 1}`, dimension: "ram_gb", comparable_value: "8", subject_value: "16", method: "percent", value: 0, symmetric: false, calibrated: false, basis: "" }))}>+ adjustment rule</button></div>}
      </Card>

      <div className="grid g2">
        <Card title="Matching, weighting & outliers">
          <div className="formgrid">
            <label className="field">Minimum comparables<Num disabled={dis} step="1" value={cfg.matching.min_comparables} onChange={(v) => up((c) => (c.matching.min_comparables = v ?? 1))} /></label>
            <label className="field">Minimum independent sources<Num disabled={dis} step="1" value={cfg.matching.min_independent_sources} onChange={(v) => up((c) => (c.matching.min_independent_sources = v ?? 1))} /></label>
            <label className="field">Battery tolerance (pts)<Num disabled={dis} value={cfg.matching.battery_tolerance_pts} onChange={(v) => up((c) => (c.matching.battery_tolerance_pts = v))} /></label>
            <label className="field">Recency half-life (days)<Num disabled={dis} value={cfg.matching.recency_half_life_days} onChange={(v) => up((c) => (c.matching.recency_half_life_days = v ?? 60))} /></label>
            <label className="field">Weight: exact<Num disabled={dis} value={cfg.matching.weight_exact} onChange={(v) => up((c) => (c.matching.weight_exact = v ?? 1))} /></label>
            <label className="field">Weight: unverified<Num disabled={dis} value={cfg.matching.weight_unverified} onChange={(v) => up((c) => (c.matching.weight_unverified = v ?? 0.8))} /></label>
            <label className="field">Weight: adjusted<Num disabled={dis} value={cfg.matching.weight_adjusted} onChange={(v) => up((c) => (c.matching.weight_adjusted = v ?? 0.5))} /></label>
            <label className="field">Outlier rule (× scaled MAD)<span className="hint">blank = off</span><Num disabled={dis} value={cfg.matching.outlier_mad_k} onChange={(v) => up((c) => (c.matching.outlier_mad_k = v))} /></label>
          </div>
          <label className="row small" style={{ marginTop: 10 }}><input type="checkbox" disabled={dis} checked={cfg.matching.split_weight_by_source} onChange={(e) => up((c) => (c.matching.split_weight_by_source = e.target.checked))} /> Split weight across records from the same source</label>
          <h3 style={{ margin: "14px 0 6px" }}>Must be known on both sides (else excluded)</h3>
          <div className="row wrap">
            {DIMENSIONS.map(([k, l]) => (
              <label key={k} className="row small" style={{ gap: 4 }}>
                <input type="checkbox" disabled={dis} checked={cfg.matching.required_dimensions.includes(k)}
                  onChange={(e) => up((c) => {
                    const req = new Set<string>(c.matching.required_dimensions);
                    const opt = new Set<string>(c.matching.optional_dimensions);
                    if (e.target.checked) { req.add(k); opt.delete(k); } else { req.delete(k); opt.add(k); }
                    c.matching.required_dimensions = [...req];
                    c.matching.optional_dimensions = [...opt];
                  })} />{l}
              </label>
            ))}
          </div>
        </Card>
        <Card title="Freshness & deduplication">
          <div className="formgrid">
            {Object.keys(cfg.freshness.max_age_days).map((k) => (
              <label key={k} className="field">Max age: {k} (days)<Num disabled={dis} step="1" value={cfg.freshness.max_age_days[k]} onChange={(v) => up((c) => (c.freshness.max_age_days[k] = v ?? 0))} /></label>
            ))}
            <label className="field">Repeat-listing price tolerance %<Num disabled={dis} value={cfg.dedup.repeat_price_tolerance_pct} onChange={(v) => up((c) => (c.dedup.repeat_price_tolerance_pct = v ?? 0))} /></label>
            <label className="field">Repeat window (days)<Num disabled={dis} step="1" value={cfg.dedup.repeat_window_days} onChange={(v) => up((c) => (c.dedup.repeat_window_days = v ?? 0))} /></label>
            <label className="field">Syndication price tolerance %<Num disabled={dis} value={cfg.dedup.syndication_price_tolerance_pct} onChange={(v) => up((c) => (c.dedup.syndication_price_tolerance_pct = v ?? 0))} /></label>
            <label className="field">Syndication window (days)<Num disabled={dis} step="1" value={cfg.dedup.syndication_window_days} onChange={(v) => up((c) => (c.dedup.syndication_window_days = v ?? 0))} /></label>
          </div>
          <label className="row small" style={{ marginTop: 10 }}><input type="checkbox" disabled={dis} checked={cfg.freshness.exclude_unavailable_listings} onChange={(e) => up((c) => (c.freshness.exclude_unavailable_listings = e.target.checked))} /> Exclude out-of-stock / removed listings</label>
          <label className="row small"><input type="checkbox" disabled={dis} checked={cfg.freshness.exclude_expired_quotes} onChange={(e) => up((c) => (c.freshness.exclude_expired_quotes = e.target.checked))} /> Exclude expired quotations</label>
          <h3 style={{ margin: "14px 0 6px" }}>Version history</h3>
          <table className="t">
            <tbody>
              {(versions.data ?? []).map((v) => (
                <tr key={v.id}><td>v{v.version} {v.is_active && <span className="badge good">active</span>}</td><td className="small">{v.note ?? <span className="muted">no note</span>}</td><td className="small muted nowrap">{dateTime(v.created_at)}</td><td className="mono tiny">{v.hash.slice(0, 10)}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}

function CostRows({ rows, dis, onChange, unit }: { rows: { name: string; amount: number | null }[]; dis: boolean; onChange: (r: { name: string; amount: number | null }[]) => void; unit: string }) {
  return (
    <div className="stack-sm" style={{ marginTop: 6 }}>
      {rows.map((r, i) => (
        <div key={i} className="row">
          <input disabled={dis} value={r.name} style={{ flex: 1 }} onChange={(e) => onChange(rows.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
          <Num disabled={dis} value={r.amount} onChange={(v) => onChange(rows.map((x, j) => (j === i ? { ...x, amount: v } : x)))} />
          {unit && <span className="tiny muted">{unit}</span>}
          {!dis && <button className="btn sm ghost" onClick={() => onChange(rows.filter((_, j) => j !== i))}>✕</button>}
        </div>
      ))}
      {!dis && <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => onChange([...rows, { name: "New cost", amount: null }])}>+ cost</button>}
    </div>
  );
}
