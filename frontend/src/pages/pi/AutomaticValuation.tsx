import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, download as downloadFile } from "../../api";
import { useApp } from "../../context";
import { Card, ErrorBox } from "../../components/ui";

type Job = { id: number; status: string; total: number; done: number; failed: number; error: string | null;
  workflow: { priced_lines?: number; phase?: string; research_mode?: string; result?: string; artifact?: string;
    events?: { phase: string; at: string }[]; integrity?: { fidelity?: { warning?: string } } } };
const phases = ["Importing assets", "Identifying products", "Researching market", "Validating price evidence", "Calculating procurement prices", "Generating quotation"];

export default function AutomaticValuation({ batchId, onComplete }: { batchId: number; onComplete?: () => void }) {
  const { can } = useApp();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const completedJob = useRef<number | null>(null);
  const completionCallback = useRef(onComplete);
  completionCallback.current = onComplete;
  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const jobs = await api.get<Job[]>(`/api/pi/jobs?batch_id=${batchId}`);
        const current = jobs.find(j => j.workflow?.phase);
        if (alive && current) {
          setJob(current);
          if (current.workflow.artifact && completedJob.current !== current.id) {
            completedJob.current = current.id;
            completionCallback.current?.();
          }
        }
        if (alive) setError(null);
      } catch (e) { if (alive) setError(`Progress unavailable: ${(e as Error).message}`); }
      if (alive) timer = window.setTimeout(tick, 2000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [batchId]);
  const start = async () => {
    setBusy(true); setError(null);
    try { setJob(await api.post<Job>(`/api/pi/batches/${batchId}/analyze`)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const running = job?.status === "queued" || job?.status === "running";
  const done = job?.workflow.events?.map(e => e.phase) ?? [];
  const download = async () => {
    try { await downloadFile(`/api/pi/jobs/${job!.id}/workbook`, `Casterly_Valuation_${batchId}.xlsx`); }
    catch(e) { setError((e as Error).message); }
  };
  return <Card title="Automatic market valuation">
    <ErrorBox error={error || job?.error || null} />
    <p className="small muted">Research available providers, reuse dated trusted evidence, apply the versioned procurement policy, and generate a draft quotation. Unsupported items remain flagged.</p>
    <div className="row" style={{gap: 8, flexWrap: "wrap"}}>
      <button className="btn primary" disabled={busy || !!running || !can("pi_price") || !can("pi_research") || !can("pi_quote") || !can("export")} onClick={start}>
        {busy || running ? "Analysis in progress…" : "Analyze & Calculate Market Prices"}
      </button>
      {job?.workflow.artifact && <button className="btn" onClick={download}>{job.workflow.result === "Research Unavailable" ? "Download review workbook (no prices)" : "Download completed Excel"}</button>}
      {job && !running && <button className="btn" onClick={async () => {
        try { await downloadFile(`/api/pi/batches/${batchId}/export?clean=true`, `Casterly_Clean_Quotation_${batchId}.xlsx`); }
        catch (e) { setError((e as Error).message); }
      }}>Download clean quotation</button>}
      <Link className="btn" to={`/pi/review?batch=${batchId}`}>Review prices and evidence</Link>
    </div>
    {job && <div className="stack-sm" role="status" aria-live="polite" style={{marginTop:12}}>
      <b>{job.workflow.phase ?? job.status}</b>
      <div className="small">{job.workflow.research_mode === "offline_history" ? "Offline / historical mode. Live research is not configured." : "Configured live research with fallback; each price shows its actual evidence method."}</div>
      <div className="small">Research tasks: {job.done} / {job.total} finished · {job.failed} failed</div>
      <progress aria-label="Research task progress" value={job.done + job.failed} max={Math.max(job.total,1)} style={{width:"100%"}} />
      <div className="small">{phases.map(p => <div key={p}>{done.includes(p) ? "✓ " : "○ "}{p}</div>)}</div>
      {job.workflow.result && <div className="banner info">{job.workflow.result}. {job.workflow.priced_lines !== undefined ? `${job.workflow.priced_lines.toLocaleString()} rows priced. ` : ""}Unsupported rows remain blank. Generated quotations are drafts; provisional values and exceptions require review before purchase.</div>}
      {job.workflow.integrity?.fidelity?.warning && <div className="small muted">{job.workflow.integrity.fidelity.warning}</div>}
    </div>}
  </Card>;
}
