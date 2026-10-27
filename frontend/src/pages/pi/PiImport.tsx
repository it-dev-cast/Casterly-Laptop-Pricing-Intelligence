import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api";
import { Card, ErrorBox, Loading, PageHead } from "../../components/ui";
import { useApp, useLoad } from "../../context";
import { num } from "../../format";
import { Field, Steps, useBatchParam, usePiMeta } from "./shared";
import type { PiBatch } from "./types";

import AutomaticValuation from "./AutomaticValuation";

interface Preview {
  batch: PiBatch;
  rows: { row_number: number; raw: Record<string, unknown>; label: string | null; category: string; quantity: number | null; grade: string | null; identify_confidence: string }[];
}

export default function PiImport() {
  const { can, toast } = useApp();
  const nav = useNavigate();
  const [batchId, setBatchId] = useBatchParam();
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const [vendor, setVendor] = useState("");
  const [name, setName] = useState("");
  const [grade, setGrade] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    const f = new FormData();
    f.append("file", file);
    if (vendor) f.append("vendor", vendor);
    if (name) f.append("name", name);
    if (grade) f.append("default_grade", grade);
    try {
      const b = await api.form<PiBatch>("/api/pi/batches", f);
      toast(`Imported ${b.lines} lines (${b.layout.toUpperCase()} layout).`);
      setBatchId(b.id);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack fade-in">
      <PageHead title="Excel bulk import" sub="Upload a vendor's asset list (.xlsx). The importer finds the asset table, recognises the B001 and B002 layouts, excludes totals, and keeps every source row for the priced export. Your file is never modified." />
      <Steps at={0} />
      {!batchId && (
        <Card title="Upload vendor workbook">
          <div className="stack">
            <ErrorBox error={err} />
            {busy && <div role="status" className="banner info">Importing assets and identifying products…</div>}
            <div className={`dropzone ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) setFile(f); }}
              onClick={() => input.current?.click()} role="button" tabIndex={0} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}>
              <input ref={input} type="file" accept=".xlsx" hidden onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              {file ? <><b>{file.name}</b><div className="small muted">{(file.size / 1024).toFixed(0)} KB · click to change</div></> :
                <><b>Drop the vendor .xlsx here</b><div className="small muted">or click to choose a file (max 10 MB)</div></>}
            </div>
            <div className="formgrid">
              <Field label="Batch name" hint="defaults to the file name"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
              <Field label="Vendor"><input value={vendor} onChange={(e) => setVendor(e.target.value)} /></Field>
              <Field label="Default grade" hint="applied only to rows with no grade/condition">
                <select value={grade} onChange={(e) => setGrade(e.target.value)}>
                  <option value="">none (flag as unknown)</option>{["A+", "A", "B", "C", "D"].map((g) => <option key={g}>{g}</option>)}
                </select>
              </Field>
            </div>
            <div className="row"><div className="spacer" />
              <button className="btn primary" disabled={!file || busy || !can("pi_import")} onClick={submit}>{busy ? <span className="spin" /> : "Import and identify"}</button>
            </div>
          </div>
        </Card>
      )}
      {batchId && <BatchSetup id={batchId} onReset={() => { setBatchId(null); setFile(null); }} onPriced={() => nav(`/pi/review?batch=${batchId}`)} />}
    </div>
  );
}

function BatchSetup({ id, onReset, onPriced }: { id: number; onReset: () => void; onPriced: () => void }) {
  const { can, toast } = useApp();
  const meta = usePiMeta();
  const p = useLoad(() => api.get<Preview>(`/api/pi/batches/${id}/preview?limit=15`), [id]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (p.data) setMapping(p.data.batch.column_map);
  }, [p.data]);
  if (p.loading && !p.data) return <Loading />;
  if (p.error) return <ErrorBox error={p.error} />;
  const b = p.data!.batch;
  const det = b.detection!;
  const fields = meta.data?.fields ?? {};
  const changed = JSON.stringify(mapping) !== JSON.stringify(b.column_map);

  const run = async (fn: () => Promise<unknown>, ok: string, after?: () => void) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      toast(ok);
      p.reload();
      after?.();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <ErrorBox error={err} />
      <AutomaticValuation batchId={id} />
      <div className="grid g4">
        <div className="card kpi accent"><div className="label">Detected layout</div><div className="value sm">{b.layout.toUpperCase()}</div><div className="foot">sheet “{b.sheet_name}”, header row {b.header_row}</div></div>
        <div className="card kpi"><div className="label">Asset lines</div><div className="value sm">{num(b.lines)}</div><div className="foot">{num(b.units)} units · {det.skipped_count} rows skipped</div></div>
        <div className="card kpi"><div className="label">Research groups</div><div className="value sm">{num(b.products)}</div><div className="foot">identical products share one research</div></div>
        <div className="card kpi"><div className="label">Exceptions</div><div className="value sm">{num(b.open_exceptions)}</div><div className="foot"><Link to={`/pi/exceptions?batch=${b.id}`}>review list →</Link></div></div>
      </div>
      {det.warnings.map((w) => <div key={w} className="banner info">{w}</div>)}
      <div className="grid g2">
        <Card title="Column mapping" actions={can("pi_import") && changed ? <button className="btn sm primary" disabled={busy}
          onClick={() => run(() => api.post(`/api/pi/batches/${b.id}/mapping`, { mapping, sheet: b.sheet_name, header_row: b.header_row }), "Mapping applied; rows re-identified.")}>Apply mapping</button> : null}>
          <div className="small muted" style={{ marginBottom: 8 }}>{b.price_column ? <>Existing <b>{b.price_column}</b> column will be filled in the export.</> : <>A <b>Market Unit Price</b> column will be added{b.qty_column ? <> with <b>Estimated Lot Value</b> = {b.qty_column} × price</> : null}.</>}</div>
          <table className="t">
            <thead><tr><th>Field</th><th>Source column</th></tr></thead>
            <tbody>
              {Object.entries(fields).map(([k, label]) => (
                <tr key={k}>
                  <td className="small">{label}</td>
                  <td>
                    <select value={mapping[k] ?? ""} disabled={!can("pi_import")} style={{ width: "100%" }}
                      onChange={(e) => { const m = { ...mapping }; if (e.target.value) m[k] = e.target.value; else delete m[k]; setMapping(m); }}>
                      <option value="">— not mapped —</option>
                      {det.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <div className="stack">
          <Card title="Sheets considered" tight>
            <table className="t"><thead><tr><th>Sheet</th><th>Header row</th><th>Layout</th><th className="num">Score</th></tr></thead>
              <tbody>{det.candidates.map((c) => <tr key={c.sheet} className={c.sheet === b.sheet_name ? "sel" : ""}><td>{c.sheet}</td><td>{c.header_row}</td><td>{c.layout}</td><td className="num">{c.score.toFixed(0)}</td></tr>)}</tbody>
            </table>
          </Card>
          {det.skipped_rows.length > 0 && (
            <Card title="Rows excluded" tight>
              <table className="t"><tbody>{det.skipped_rows.slice(0, 12).map((s) => <tr key={s.row}><td>Row {s.row}</td><td className="small muted">{s.reason}</td></tr>)}</tbody></table>
            </Card>
          )}
        </div>
      </div>
      <Card title="Identification preview" tight>
        <div className="tablewrap">
          <table className="t">
            <thead><tr><th>Row</th><th>Identified as</th><th>Category</th><th className="num">Qty</th><th>Grade</th><th>Confidence</th></tr></thead>
            <tbody>{p.data!.rows.map((r) => (
              <tr key={r.row_number}><td>{r.row_number}</td><td>{r.label ?? <span className="muted">unidentified</span>}</td><td className="small">{meta.data?.categories[r.category] ?? r.category}</td>
                <td className="num">{r.quantity ?? <span className="muted">?</span>}</td><td>{r.grade ?? "—"}</td><td className="small">{r.identify_confidence}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </Card>
      <div className="row">
        <button className="btn" onClick={onReset}>Import another file</button>
        <div className="spacer" />
        {can("pi_research") && <Link className="btn" to={`/pi/research?batch=${b.id}`}>Research market prices</Link>}
        {can("pi_price") && <button className="btn primary" disabled={busy}
          onClick={() => run(() => api.post(`/api/pi/batches/${b.id}/analyze`), "Automatic research and pricing queued.", onPriced)}>Analyze & Calculate Market Prices</button>}
      </div>
    </>
  );
}
