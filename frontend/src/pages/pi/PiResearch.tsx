import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { Card, Drawer, Empty, ErrorBox, Loading, PageHead } from "../../components/ui";
import { useApp, useLoad } from "../../context";
import { date, dateTime, inr, num } from "../../format";
import { BatchPicker, Confidence, ExtLink, Field, Steps, useBatchParam, usePiMeta } from "./shared";
import type { PiBatch, PiGroup, PiJob, PiObservation } from "./types";
import { n } from "./types";

interface JobDetail extends PiJob {
  tasks: { id: number; product: string; status: string; attempts: number; hits: number; observations_found: number; error: string | null }[];
}

export default function PiResearch() {
  const { can, toast } = useApp();
  const meta = usePiMeta();
  const [batchId, setBatchId] = useBatchParam();
  const batch = useLoad(() => (batchId ? api.get<PiBatch>(`/api/pi/batches/${batchId}`) : Promise.resolve(null)), [batchId]);
  const groups = useLoad(() => (batchId ? api.get<PiGroup[]>(`/api/pi/batches/${batchId}/groups`) : Promise.resolve([])), [batchId]);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [open, setOpen] = useState<PiGroup | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showRef, setShowRef] = useState(false);

  const jobId = job?.id ?? batch.data?.latest_job?.id ?? null;
  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const j = await api.get<JobDetail>(`/api/pi/jobs/${jobId}`);
        if (!alive) return;
        setJob(j);
        if (j.status === "queued" || j.status === "running") timer = window.setTimeout(tick, 2500);
        else groups.reload();
      } catch {
        /* transient */
      }
    };
    tick();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const act = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fn();
      toast(msg);
      if (r && typeof r === "object" && "provider" in (r as PiJob)) setJob({ ...(r as PiJob), tasks: [] });
      groups.reload();
      batch.reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const configured = (meta.data?.providers ?? []).filter((p) => p.configured);
  const pct = job && job.total ? Math.round((100 * (job.done + job.failed)) / job.total) : 0;
  const active = job && (job.status === "queued" || job.status === "running");

  return (
    <div className="stack fade-in">
      <PageHead title="Market research results" sub="One research task per identical product (not per serial). Search results become candidates; only verified evidence is used for pricing."
        actions={<>
          <BatchPicker value={batchId} onChange={setBatchId} />
          {can("pi_rules") && <button className="btn" onClick={() => setShowRef(true)}>Import reference valuation</button>}
        </>} />
      <Steps at={1} />
      <ErrorBox error={err} />
      {configured.length === 0 ? (
        <div className="banner warn"><div><b>Live research is not configured.</b> {meta.data?.providers.filter((p) => p.env_var).map((p) => p.env_var).join(" or ")} must be set on the server.
          Use automatic analysis on the import screen to reuse trusted historical evidence. Insufficiently supported items are flagged; no live prices are invented.</div></div>
      ) : (
        <div className="banner info"><div>Research provider: <b>{configured.map((p) => p.label).join(", ")}</b>. Only prices present in the provider's own result text are captured; result pages are not scraped.</div></div>
      )}
      {!batchId ? <Empty>Select a valuation batch.</Empty> : (
        <>
          <Card title="Research job" actions={<>
            {active && can("pi_research") && <button className="btn sm" disabled={busy} onClick={() => act(() => api.post(`/api/pi/jobs/${job!.id}/cancel`), "Cancellation requested.")}>Cancel</button>}
            {job && !active && job.status !== "completed" && can("pi_research") && <button className="btn sm" disabled={busy} onClick={() => act(() => api.post(`/api/pi/jobs/${job.id}/resume`), "Job resumed.")}>Resume</button>}
            {can("pi_research") && <button className="btn sm primary" disabled={busy || !!active || configured.length === 0}
              onClick={() => act(() => api.post(`/api/pi/batches/${batchId}/research`, {}), "Research queued.")}>Start research</button>}
            {can("pi_research") && job && !active && <button className="btn sm" disabled={busy || configured.length === 0}
              onClick={() => act(() => api.post(`/api/pi/batches/${batchId}/research`, { force: true }), "Fresh research queued (cache bypassed).")}>Refresh (bypass cache)</button>}
          </>}>
            {!job ? <div className="small muted">No research has been run for this batch.</div> : (
              <div className="stack-sm">
                <div className="row" style={{ gap: 10 }}>
                  <span className="badge">{job.status}</span><span className="small">{job.provider}</span>
                  <span className="small muted">{num(job.done)} done · {num(job.cached)} cached · {num(job.failed)} failed · {num(job.observations_found)} priced results found</span>
                  <div className="spacer" /><span className="small muted">{dateTime(job.created_at)}</span>
                </div>
                <div className="meter"><i style={{ width: `${pct}%` }} /></div>
                {job.error && <div className="small" style={{ color: "var(--bad)" }}>{job.error}</div>}
                {job.tasks?.some((t) => t.status === "failed") && (
                  <details><summary className="small">Failed tasks</summary>
                    <ul className="small">{job.tasks.filter((t) => t.status === "failed").map((t) => <li key={t.id}>{t.product}: {t.error} ({t.attempts} attempts)</li>)}</ul>
                  </details>
                )}
              </div>
            )}
          </Card>
          <Card title="Products in this batch" tight actions={<Link className="btn sm" to={`/pi/review?batch=${batchId}`}>Pricing review →</Link>}>
            {groups.loading && !groups.data ? <Loading /> : (
              <div className="tablewrap">
                <table className="t">
                  <thead><tr><th>Product</th><th>Grade</th><th className="num">Lines</th><th className="num">Units</th><th className="num">Evidence</th><th className="num">Benchmark</th><th className="num">Market Unit Price</th><th>Confidence</th><th>Status</th><th /></tr></thead>
                  <tbody>
                    {(groups.data ?? []).map((g) => (
                      <tr key={`${g.product_id}-${g.grade}`} className="clickable" onClick={() => g.product_id && setOpen(g)}>
                        <td><b>{g.label}</b><div className="tiny muted">{meta.data?.categories[g.category ?? ""] ?? g.category ?? "unidentified"}</div></td>
                        <td>{g.grade ?? "—"}</td><td className="num">{num(g.lines)}</td><td className="num">{num(g.units)}</td>
                        <td className="num">{g.verified} verified{g.candidates ? <div className="tiny" style={{ color: "var(--warn)" }}>{g.candidates} to review</div> : null}</td>
                        <td className="num">{inr(n(g.estimate?.benchmark ?? null))}</td>
                        <td className="num"><b>{inr(n(g.estimate?.recommended_unit ?? null))}</b></td>
                        <td><Confidence c={g.estimate?.confidence} /></td>
                        <td className="small">{g.estimate?.status ?? (g.product_id ? "not priced" : "unidentified")}</td>
                        <td>{g.product_id ? <span className="small">Evidence →</span> : null}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
      {open && <EvidenceDrawer group={open} onClose={() => setOpen(null)} onChanged={() => groups.reload()} />}
      {showRef && <ReferencePack onClose={() => setShowRef(false)} onDone={() => { setShowRef(false); groups.reload(); }} />}
    </div>
  );
}

function EvidenceDrawer({ group, onClose, onChanged }: { group: PiGroup; onClose: () => void; onChanged: () => void }) {
  const { can, toast } = useApp();
  const meta = usePiMeta();
  const obs = useLoad(() => api.get<PiObservation[]>(`/api/pi/observations?product_id=${group.product_id}`), [group.product_id]);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [tax, setTax] = useState("inclusive");
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ price_type: "supplier_quote", price: "", tax_basis: "exclusive", url: "", seller: "", title: "", match_quality: "identical" });

  const verify = async (action: string) => {
    try {
      await api.post("/api/pi/observations/verify", { ids: [...sel], action, tax_basis: action === "verify" ? tax : undefined });
      toast(`${sel.size} observation(s) ${action === "verify" ? "verified" : action === "reject" ? "rejected" : "reset"}.`);
      setSel(new Set());
      obs.reload();
      onChanged();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const add = async () => {
    try {
      await api.post("/api/pi/observations", { ...form, product_id: group.product_id, url: form.url || null, seller: form.seller || null, title: form.title || null });
      toast("Verified evidence added.");
      setForm({ ...form, price: "", url: "", title: "" });
      obs.reload();
      onChanged();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const list = obs.data ?? [];
  return (
    <Drawer title={group.label} onClose={onClose}>
      <div className="stack">
        <ErrorBox error={err} />
        {can("pi_verify_evidence") && (
          <div className="row" style={{ gap: 8 }}>
            <span className="small">{sel.size} selected</span>
            <select value={tax} onChange={(e) => setTax(e.target.value)} aria-label="Tax basis for verification"><option value="inclusive">price incl. GST</option><option value="exclusive">price ex-GST</option><option value="unknown">tax unknown</option></select>
            <button className="btn sm primary" disabled={!sel.size} onClick={() => verify("verify")}>Verify</button>
            <button className="btn sm" disabled={!sel.size} onClick={() => verify("reject")}>Reject</button>
            <button className="btn sm ghost" disabled={!sel.size} onClick={() => verify("reset")}>Reset</button>
          </div>
        )}
        {obs.loading && !obs.data ? <Loading /> : list.length === 0 ? <Empty>No evidence yet for this product.</Empty> : (
          <div className="tablewrap">
            <table className="t">
              <thead><tr><th /><th>Evidence</th><th className="num">Price</th><th>Type</th><th>Status</th></tr></thead>
              <tbody>
                {list.map((o) => (
                  <tr key={o.id} className={o.status === "rejected" ? "excluded" : ""}>
                    <td><input type="checkbox" aria-label="select" disabled={o.provider === "reference_pack" && o.price_type === "historical_valuation"} checked={sel.has(o.id)}
                      onChange={() => { const s = new Set(sel); if (s.has(o.id)) s.delete(o.id); else s.add(o.id); setSel(s); }} /></td>
                    <td className="small">
                      <div>{o.title ?? "—"}</div>
                      <div className="tiny muted">{o.source?.name ?? o.seller ?? o.provider} · {date(o.observed_at)} · {o.match_quality}{o.condition ? ` · ${o.condition}` : ""}</div>
                      {o.url && <div className="tiny"><ExtLink href={o.url} /></div>}
                      {o.snippet && <div className="tiny muted" style={{ maxWidth: 420 }}>{o.snippet.slice(0, 220)}{o.snippet.length > 220 ? "…" : ""}</div>}
                    </td>
                    <td className="num">{o.price ? inr(n(o.price)) : <span className="muted">no price</span>}<div className="tiny muted">{o.tax_basis}</div></td>
                    <td className="small">{meta.data?.price_types[o.price_type] ?? o.price_type}</td>
                    <td><span className={`badge ${o.status === "verified" ? "good" : o.status === "candidate" ? "warn" : ""}`}>{o.status}</span>
                      {o.status_reason && <div className="tiny muted">{o.status_reason}</div>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {can("pi_verify_evidence") && (
          <div className="card" style={{ padding: 12 }}>
            <h3 className="small" style={{ marginBottom: 8 }}>Add verified evidence</h3>
            <div className="formgrid">
              <Field label="Price type"><select value={form.price_type} onChange={(e) => setForm({ ...form, price_type: e.target.value })}>
                {Object.entries(meta.data?.price_types ?? {}).filter(([k]) => k !== "historical_valuation").map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
              <Field label="Unit price (₹)"><input inputMode="decimal" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} /></Field>
              <Field label="Tax basis"><select value={form.tax_basis} onChange={(e) => setForm({ ...form, tax_basis: e.target.value })}><option value="exclusive">ex-GST</option><option value="inclusive">incl. GST</option><option value="unknown">unknown</option></select></Field>
              <Field label="Match"><select value={form.match_quality} onChange={(e) => setForm({ ...form, match_quality: e.target.value })}><option value="identical">identical</option><option value="comparable">comparable</option></select></Field>
              <Field label="Source URL"><input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://…" /></Field>
              <Field label="Seller / vendor"><input value={form.seller} onChange={(e) => setForm({ ...form, seller: e.target.value })} /></Field>
              <Field label="Note / title"><input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
            </div>
            <div className="row" style={{ marginTop: 8 }}><div className="spacer" /><button className="btn primary" disabled={!form.price} onClick={add}>Add evidence</button></div>
          </div>
        )}
      </div>
    </Drawer>
  );
}

function ReferencePack({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { toast } = useApp();
  const [file, setFile] = useState<File | null>(null);
  const [ref, setRef] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    if (!file) return;
    setBusy(true);
    const f = new FormData();
    f.append("file", file);
    if (ref) f.append("reference_date", ref);
    try {
      const r = await api.form<{ historical_observations: number; benchmark_candidates: number; reference_date: string }>("/api/pi/reference-packs", f);
      toast(`Reference ${r.reference_date}: ${r.historical_observations} historical valuations, ${r.benchmark_candidates} archived benchmarks (to verify).`);
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Drawer title="Import reference valuation" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!file || busy} onClick={go}>Import</button></>}>
      <div className="stack">
        <ErrorBox error={err} />
        <div className="small">A completed Casterly valuation workbook (for example <b>CIN-20261026-B002_Market_Unit_Prices_Researched.xlsx</b>). Its Market Unit Price values become dated
          <b> historical valuation</b> evidence: used only when no current evidence exists, and always marked provisional. Rate Benchmarks are imported as candidates to verify.</div>
        <input type="file" accept=".xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <Field label="Reference date" hint="read from the workbook when present"><input type="date" value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
      </div>
    </Drawer>
  );
}
