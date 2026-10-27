import { useState } from "react";
import { api } from "../../api";
import { Card, Drawer, ErrorBox, Loading, PageHead } from "../../components/ui";
import { useApp, useLoad } from "../../context";
import { num } from "../../format";
import { Field, usePiMeta } from "./shared";

interface Source { id: number; name: string; domain: string; source_kind: string; default_price_type: string | null; reliability: number; categories: string[] | null; is_active: boolean; terms_note: string | null; observations: number }
const KINDS = ["refurb_retailer", "marketplace", "buyback", "wholesaler", "internal", "unclassified"];

export default function PiSources() {
  const { can } = useApp();
  const meta = usePiMeta();
  const s = useLoad(() => api.get<Source[]>("/api/pi/sources"), []);
  const [edit, setEdit] = useState<Source | "new" | null>(null);
  return (
    <div className="stack fade-in">
      <PageHead title="Market source library" sub="Sources seen in research or entered manually. Reliability weights evidence; a disabled source's results are ignored. Listing a source is not an integration and does not grant permission to scrape it."
        actions={can("pi_sources") && <button className="btn primary" onClick={() => setEdit("new")}>Add source</button>} />
      <Card tight>
        {s.loading && !s.data ? <Loading /> : (
          <table className="t">
            <thead><tr><th>Source</th><th>Kind</th><th>Default price type</th><th className="num">Reliability</th><th className="num">Observations</th><th>Status</th><th>Notes</th></tr></thead>
            <tbody>{(s.data ?? []).map((x) => (
              <tr key={x.id} className={can("pi_sources") ? "clickable" : ""} onClick={() => can("pi_sources") && setEdit(x)}>
                <td><b>{x.name}</b><div className="tiny muted">{x.domain}</div></td><td className="small">{x.source_kind}</td>
                <td className="small">{x.default_price_type ? meta.data?.price_types[x.default_price_type] ?? x.default_price_type : "—"}</td>
                <td className="num"><div className="meter" style={{ width: 80, display: "inline-block" }}><i style={{ width: `${x.reliability * 100}%` }} /></div> {x.reliability.toFixed(2)}</td>
                <td className="num">{num(x.observations)}</td><td>{x.is_active ? <span className="badge good">active</span> : <span className="badge">disabled</span>}</td>
                <td className="tiny muted" style={{ maxWidth: 320 }}>{x.terms_note}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Card>
      {edit && <SourceEditor src={edit === "new" ? null : edit} priceTypes={meta.data?.price_types ?? {}} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); s.reload(); }} />}
    </div>
  );
}

function SourceEditor({ src, priceTypes, onClose, onSaved }: { src: Source | null; priceTypes: Record<string, string>; onClose: () => void; onSaved: () => void }) {
  const { toast } = useApp();
  const [f, setF] = useState({ name: src?.name ?? "", domain: src?.domain ?? "", source_kind: src?.source_kind ?? "refurb_retailer",
    default_price_type: src?.default_price_type ?? "", reliability: String(src?.reliability ?? 0.5), is_active: src?.is_active ?? true, terms_note: src?.terms_note ?? "" });
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    const body = { ...f, reliability: Number(f.reliability), default_price_type: f.default_price_type || null, categories: src?.categories ?? null };
    try {
      if (src) await api.patch(`/api/pi/sources/${src.id}`, body);
      else await api.post("/api/pi/sources", body);
      toast("Source saved.");
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <Drawer title={src ? src.name : "Add source"} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" onClick={save}>Save</button></>}>
      <div className="stack">
        <ErrorBox error={err} />
        <div className="formgrid">
          <Field label="Name"><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Domain"><input value={f.domain} disabled={!!src} onChange={(e) => setF({ ...f, domain: e.target.value })} placeholder="example.in" /></Field>
          <Field label="Kind"><select value={f.source_kind} onChange={(e) => setF({ ...f, source_kind: e.target.value })}>{KINDS.map((k) => <option key={k}>{k}</option>)}</select></Field>
          <Field label="Default price type"><select value={f.default_price_type} onChange={(e) => setF({ ...f, default_price_type: e.target.value })}><option value="">classify per result</option>
            {Object.entries(priceTypes).filter(([k]) => k !== "historical_valuation").map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Reliability (0–1)" hint="weights this source's evidence"><input inputMode="decimal" value={f.reliability} onChange={(e) => setF({ ...f, reliability: e.target.value })} /></Field>
          <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}><input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />Active</label>
        </div>
        <Field label="Terms / notes"><textarea rows={3} value={f.terms_note} onChange={(e) => setF({ ...f, terms_note: e.target.value })} /></Field>
      </div>
    </Drawer>
  );
}
