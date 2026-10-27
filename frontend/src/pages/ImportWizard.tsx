import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, download } from "../api";
import { TemplateList, TemplatePanel } from "../components/TemplateDownload";
import { Card, Drawer, Empty, ErrorBox, Loading, PageHead } from "../components/ui";
import { useApp, useLoad } from "../context";
import { dateTime, show } from "../format";

interface Sheet { name: string; rows: number; headers: string[]; preview: Record<string, unknown>[] }
interface Batch {
  id: number; record_type: string; record_type_label: string; original_filename: string; file_kind: string;
  size_bytes: number; sha256: string; sheets: Sheet[]; selected_sheets: string[] | null;
  mapping: Record<string, string> | null; import_defaults: Record<string, string> | null; status: string;
  summary: { total: number; by_status: Record<string, number> } | null; created_at: string;
}
interface FieldDef { key: string; label: string; kind: string; help: string; required: boolean; matching: boolean }
interface Issue { field: string | null; message: string }
interface Suggestion { value: unknown; raw: string | null; confidence: string; method: string; note: string | null }
interface Row {
  id: number; sheet: string; row_number: number; raw: Record<string, unknown>; mapped_raw: Record<string, unknown>;
  normalized: Record<string, unknown>; corrections: Record<string, unknown>; suggestions: Record<string, Suggestion> | null;
  errors: Issue[]; warnings: Issue[]; status: string; duplicate_of: string | null; keep_duplicate: boolean;
  committed_record_id: number | null;
}

const TYPES = [
  { key: "inventory", label: "Inventory to value", desc: "A stock list or lot you are being offered or already hold.", perm: "import_inventory" },
  { key: "transaction", label: "Completed purchases & sales", desc: "Realised prices from your own invoices. The strongest evidence.", perm: "import_evidence" },
  { key: "listing", label: "Advertised listings", desc: "Asking prices observed in the market. Never treated as sales.", perm: "import_evidence" },
  { key: "quote", label: "Supplier quotations", desc: "As-is procurement prices offered by suppliers.", perm: "import_evidence" },
];

const STATUS_TONE: Record<string, string> = {
  valid: "good", warning: "warn", invalid: "bad", duplicate: "warn", needs_review: "info", skipped: "", committed: "dark", pending: "",
};
const STATUS_TEXT: Record<string, string> = {
  valid: "Valid", warning: "Valid with warnings", invalid: "Invalid", duplicate: "Duplicate", needs_review: "Needs review",
  skipped: "Skipped", committed: "Committed", pending: "Pending",
};

function Steps({ at }: { at: number }) {
  const names = ["Upload", "Sheets & columns", "Review & correct", "Commit"];
  return (
    <div className="steps">
      {names.map((n, i) => (
        <div key={n} className={`step ${i === at ? "on" : ""} ${i < at ? "done" : ""}`}>
          <span className="n">{i < at ? "✓" : i + 1}</span>
          {n}
        </div>
      ))}
    </div>
  );
}

export default function ImportWizard() {
  const { batchId } = useParams();
  if (!batchId) return <UploadStep />;
  return <BatchFlow id={Number(batchId)} />;
}

function UploadStep() {
  const { can, toast } = useApp();
  const nav = useNavigate();
  const [type, setType] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const uploads = useLoad(() => api.get<Batch[]>("/api/uploads"), []);

  const send = async (file: File) => {
    if (!type) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("record_type", type);
    fd.append("file", file);
    try {
      const b = await api.form<Batch>("/api/uploads", fd);
      nav(`/import/${b.id}`);
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack fade-in">
      <PageHead title="Upload & review" sub="Bring in inventory and evidence from Excel or CSV. Nothing is stored as a record until you review and commit it." />
      <Steps at={0} />
      <Card title="1. What are you uploading?">
        <div className="grid g4">
          {TYPES.map((t) => {
            const allowed = can(t.perm);
            return (
              <button key={t.key} disabled={!allowed} onClick={() => setType(t.key)}
                className="card" style={{ textAlign: "left", padding: 16, cursor: allowed ? "pointer" : "not-allowed",
                  outline: type === t.key ? "2px solid var(--brand)" : "none", font: "inherit", opacity: allowed ? 1 : 0.5 }}>
                <h3>{t.label}</h3>
                <div className="small muted" style={{ marginTop: 6 }}>{t.desc}</div>
                {!allowed && <div className="tiny muted">Your role cannot import this type.</div>}
              </button>
            );
          })}
        </div>
      </Card>
      <Card title="2. Get the sample format">
        {type ? <TemplatePanel recordType={type} /> : (
          <div className="stack-sm">
            <div className="small muted">Pick a record type above, or download any of the sample formats here. Each has the exact columns the importer expects.</div>
            <TemplateList />
          </div>
        )}
      </Card>
      <Card title="3. Upload the filled file">
        <label
          className={`dropzone ${over ? "over" : ""}`}
          style={{ display: "block", cursor: type ? "pointer" : "not-allowed", opacity: type ? 1 : 0.6 }}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) send(f); }}
        >
          <input type="file" accept=".csv,.xlsx" hidden disabled={!type || busy} onChange={(e) => e.target.files?.[0] && send(e.target.files[0])} />
          {busy ? <><span className="spin" /> Checking and reading the file…</> : (
            <>
              <h3>{type ? "Drop a .xlsx or .csv file here, or click to browse" : "Select a record type first"}</h3>
              <div className="small muted" style={{ marginTop: 6 }}>
                Up to 10 MB. Macro-enabled and legacy .xls workbooks are rejected. Formulas are never executed: only stored cell values are read.
              </div>
            </>
          )}
        </label>
      </Card>
      <Card title="Recent uploads" tight>
        {uploads.loading ? <Loading /> : !uploads.data?.length ? <Empty>No uploads yet.</Empty> : (
          <table className="t">
            <thead><tr><th>File</th><th>Type</th><th>Status</th><th>Rows</th><th>Uploaded</th><th /></tr></thead>
            <tbody>
              {uploads.data.slice(0, 15).map((b) => (
                <tr key={b.id}>
                  <td>{b.original_filename}</td>
                  <td>{b.record_type_label}</td>
                  <td><span className={`badge ${b.status === "committed" ? "dark" : "info"}`}>{b.status.replace("_", " ")}</span></td>
                  <td>{b.summary?.total ?? "—"}</td>
                  <td className="muted small">{dateTime(b.created_at)}</td>
                  <td><Link className="btn sm" to={`/import/${b.id}`}>{b.status === "committed" ? "View" : "Resume"}</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function BatchFlow({ id }: { id: number }) {
  const batch = useLoad(() => api.get<Batch>(`/api/uploads/${id}`), [id]);
  const [remap, setRemap] = useState(false);
  if (batch.loading && !batch.data) return <Loading />;
  if (batch.error) return <ErrorBox error={batch.error} />;
  const b = batch.data!;
  const mapping = b.status === "uploaded" || remap;
  return (
    <div className="stack fade-in">
      <PageHead title={b.original_filename}
        sub={<>{b.record_type_label} · {(b.size_bytes / 1024).toFixed(0)} KB · <span className="mono">sha256 {b.sha256.slice(0, 12)}…</span></>}
        actions={<Link className="btn" to="/import">New upload</Link>} />
      <Steps at={mapping ? 1 : b.status === "committed" ? 3 : 2} />
      {mapping ? (
        <MappingStep b={b} onDone={() => { setRemap(false); batch.reload(); }} />
      ) : (
        <ReviewStep b={b} onChanged={batch.reload} onRemap={() => setRemap(true)} />
      )}
    </div>
  );
}

function MappingStep({ b, onDone }: { b: Batch; onDone: () => void }) {
  const { toast } = useApp();
  const [sheets, setSheets] = useState<string[]>(b.selected_sheets ?? b.sheets.filter((s) => s.rows > 0).slice(0, 1).map((s) => s.name));
  const [mapping, setMapping] = useState<Record<string, string>>(b.mapping ?? {});
  const [defaults, setDefaults] = useState<Record<string, string>>(b.import_defaults ?? {});
  const [saveAs, setSaveAs] = useState("");
  const [busy, setBusy] = useState(false);
  const fields = useLoad(() => api.get<FieldDef[]>(`/api/import/fields?record_type=${b.record_type}`), [b.record_type]);
  const sugg = useLoad(
    () => api.get<{ headers: string[]; suggested: Record<string, string>; saved_mappings: { id: number; name: string; mapping: Record<string, string>; applicable: boolean }[] }>(
      `/api/uploads/${b.id}/suggest-mapping?` + sheets.map((s) => `sheets=${encodeURIComponent(s)}`).join("&")),
    [sheets.join("|")],
  );
  useEffect(() => {
    if (sugg.data && !b.mapping) setMapping(sugg.data.suggested);
  }, [sugg.data, b.mapping]);

  const preview = useMemo(() => b.sheets.find((s) => sheets.includes(s.name))?.preview[0] ?? {}, [b.sheets, sheets]);
  const defaultKeys: [string, string, string[]][] = b.record_type === "inventory"
    ? [["lot_ref", "Lot reference", []], ["intended_channel", "Intended channel", ["retail", "wholesale", "as_is"]], ["asking_tax_basis", "Asking price tax basis", ["inclusive", "exclusive", "unknown"]], ["currency", "Currency", ["INR"]], ["supplier", "Supplier", []]]
    : b.record_type === "listing"
      ? [["channel", "Channel", ["retail", "wholesale", "as_is"]], ["tax_basis", "Tax basis", ["inclusive", "exclusive", "unknown"]], ["currency", "Currency", ["INR"]], ["platform", "Platform / site", []], ["seller", "Seller", []]]
      : b.record_type === "quote"
        ? [["tax_basis", "Tax basis", ["inclusive", "exclusive", "unknown"]], ["currency", "Currency", ["INR"]], ["seller", "Supplier", []]]
        : [["kind", "Transaction type", ["sale", "purchase"]], ["channel", "Channel", ["retail", "wholesale", "as_is"]], ["tax_basis", "Tax basis", ["inclusive", "exclusive", "unknown"]], ["currency", "Currency", ["INR"]]];

  const submit = async () => {
    setBusy(true);
    try {
      await api.post(`/api/uploads/${b.id}/stage`, {
        sheets, mapping, defaults: Object.fromEntries(Object.entries(defaults).filter(([, v]) => v)),
        save_mapping_as: saveAs || null,
      });
      onDone();
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  const missingRequired = (fields.data ?? []).filter((f) => f.required && !mapping[f.key] && !defaults[f.key]);

  return (
    <div className="grid split" style={{ gridTemplateColumns: "minmax(260px, 320px) 1fr" }}>
      <div className="stack">
        <Card title="Sheets">
          <div className="stack-sm">
            {b.sheets.map((s) => (
              <label key={s.name} className="row" style={{ alignItems: "flex-start" }}>
                <input type="checkbox" checked={sheets.includes(s.name)} disabled={s.rows === 0}
                  onChange={(e) => setSheets(e.target.checked ? [...sheets, s.name] : sheets.filter((x) => x !== s.name))} />
                <div>
                  <b>{s.name}</b> <span className="muted small">{s.rows} rows</span>
                  <div className="tiny muted">{s.headers.slice(0, 6).join(" · ")}{s.headers.length > 6 ? " …" : ""}</div>
                </div>
              </label>
            ))}
            <div className="tiny muted">Selected sheets are mapped together by column name. Title rows above the header are skipped automatically.</div>
          </div>
        </Card>
        {!!sugg.data?.saved_mappings.length && (
          <Card title="Saved mappings">
            <div className="stack-sm">
              {sugg.data.saved_mappings.map((m) => (
                <button key={m.id} className="btn sm" disabled={!m.applicable} onClick={() => setMapping(m.mapping)}
                  title={m.applicable ? "Apply" : "This file lacks some of the mapping's columns"}>
                  Apply “{m.name}”
                </button>
              ))}
            </div>
          </Card>
        )}
        <Card title="Batch defaults">
          <div className="stack-sm">
            <div className="tiny muted">Used only where a row's own cell is blank, and recorded as a warning on that row.</div>
            {defaultKeys.map(([k, label, opts]) => (
              <label key={k} className="field">
                {label}
                {opts.length ? (
                  <select value={defaults[k] ?? ""} onChange={(e) => setDefaults({ ...defaults, [k]: e.target.value })}>
                    <option value="">— none —</option>
                    {opts.map((o) => <option key={o}>{o}</option>)}
                  </select>
                ) : (
                  <input value={defaults[k] ?? ""} onChange={(e) => setDefaults({ ...defaults, [k]: e.target.value })} />
                )}
              </label>
            ))}
          </div>
        </Card>
      </div>
      <Card title="Map columns to fields" tight
        actions={<>
          <input placeholder="Save mapping as… (optional)" value={saveAs} onChange={(e) => setSaveAs(e.target.value)} style={{ width: 220 }} />
          <button className="btn primary" disabled={busy || !sheets.length || missingRequired.length > 0} onClick={submit}>
            {busy ? <span className="spin" /> : "Validate rows →"}
          </button>
        </>}>
        {missingRequired.length > 0 && (
          <div className="banner warn" style={{ margin: 12 }}>Map or default the required field(s): {missingRequired.map((f) => f.label).join(", ")}</div>
        )}
        {!fields.data || !sugg.data ? <Loading /> : (
          <div className="tablewrap" style={{ maxHeight: "70vh" }}>
            <table className="t">
              <thead><tr><th>Field</th><th>Source column</th><th>First row value</th></tr></thead>
              <tbody>
                {fields.data.map((f) => (
                  <tr key={f.key}>
                    <td>
                      <b>{f.label}</b>{" "}
                      {f.required && <span className="badge bad">required</span>}{" "}
                      {f.matching && <span className="badge info" title="Needed for exact configuration matching">matching</span>}
                      {f.help && <div className="tiny muted">{f.help}</div>}
                    </td>
                    <td>
                      <select value={mapping[f.key] ?? ""} onChange={(e) => setMapping({ ...mapping, [f.key]: e.target.value })} style={{ width: "100%" }}>
                        <option value="">— not mapped —</option>
                        {sugg.data!.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                      </select>
                    </td>
                    <td className="small">{mapping[f.key] ? show(preview[mapping[f.key]]) : <span className="muted">—</span>}</td>
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

function ReviewStep({ b, onChanged, onRemap }: { b: Batch; onChanged: () => void; onRemap: () => void }) {
  const { toast } = useApp();
  const [filter, setFilter] = useState<string>("");
  const rows = useLoad(() => api.get<Row[]>(`/api/uploads/${b.id}/rows`), [b.id]);
  const [open, setOpen] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const counts = b.summary?.by_status ?? {};
  const list = (rows.data ?? []).filter((r) => !filter || r.status === filter);
  const committable = (counts.valid ?? 0) + (counts.warning ?? 0) + (rows.data ?? []).filter((r) => r.status === "duplicate" && r.keep_duplicate).length;
  const priceKey = b.record_type === "inventory" ? "asking_price" : "price";

  const refresh = (updated?: Row) => {
    rows.reload();
    onChanged();
    if (updated) setOpen(updated);
  };
  const commit = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ created: number; not_committed: number }>(`/api/uploads/${b.id}/commit`);
      toast(`${r.created} record(s) committed. ${r.not_committed} row(s) left uncommitted.`);
      refresh();
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      {b.status === "committed" && (
        <div className="banner good">
          <div>
            <b>Committed.</b> Records keep their original cell values and your corrections.{" "}
            <Link to={b.record_type === "inventory" ? "/inventory" : "/evidence"}>Open {b.record_type === "inventory" ? "inventory" : "evidence"}</Link>
          </div>
        </div>
      )}
      <Card tight title={
        <div className="row wrap">
          <button className={`chip ${filter === "" ? "on" : ""}`} onClick={() => setFilter("")}>All {b.summary?.total ?? 0}</button>
          {Object.entries(counts).map(([k, v]) => (
            <button key={k} className={`chip ${filter === k ? "on" : ""}`} onClick={() => setFilter(k)}>{STATUS_TEXT[k] ?? k} {v}</button>
          ))}
        </div>
      } actions={<>
        <button className="btn sm" onClick={() => download(`/api/uploads/${b.id}/issues?format=csv`, "issues.csv")}>Issues CSV</button>
        <button className="btn sm" onClick={() => download(`/api/uploads/${b.id}/issues?format=xlsx`, "issues.xlsx")}>Issues Excel</button>
        {b.status !== "committed" && <button className="btn sm" onClick={onRemap}>Change mapping</button>}
        {b.status !== "committed" && (
          <button className="btn primary" disabled={busy || committable === 0} onClick={commit}>
            {busy ? <span className="spin" /> : `Commit ${committable} row${committable === 1 ? "" : "s"}`}
          </button>
        )}
      </>}>
        {rows.loading && !rows.data ? <Loading /> : (
          <div className="tablewrap" style={{ maxHeight: "68vh" }}>
            <table className="t">
              <thead><tr><th>Sheet · row</th><th>Status</th><th>Brand / model</th><th>CPU</th><th className="num">RAM</th><th className="num">Storage</th><th>Grade</th><th className="num">{priceKey === "price" ? "Price" : "Asking"}</th><th>Issues</th></tr></thead>
              <tbody>
                {list.map((r) => {
                  const n = r.normalized;
                  return (
                    <tr key={r.id} className="clickable" onClick={() => setOpen(r)}>
                      <td className="nowrap small">{r.sheet} · {r.row_number}</td>
                      <td><span className={`badge ${STATUS_TONE[r.status]}`}>{STATUS_TEXT[r.status] ?? r.status}</span></td>
                      <td>{show(n.brand)} {show(n.model)}</td>
                      <td className="small">{show(n.cpu)}</td>
                      <td className="num">{n.ram_gb == null ? "—" : `${n.ram_gb} GB`}</td>
                      <td className="num">{n.storage_gb == null ? "—" : `${n.storage_gb} GB ${n.storage_type ?? ""}`}</td>
                      <td>{show(n.condition_grade)}</td>
                      <td className="num">{show(n[priceKey])}</td>
                      <td className="small" style={{ maxWidth: 360 }}>
                        {r.errors.map((e, i) => <div key={i} style={{ color: "var(--bad)" }}>{e.message}</div>)}
                        {r.duplicate_of && <div style={{ color: "var(--warn)" }}>Duplicate of {r.duplicate_of}{r.keep_duplicate ? " (kept)" : ""}</div>}
                        {r.suggestions && <div style={{ color: "var(--brand)" }}>{Object.keys(r.suggestions).length} extracted value(s) to review</div>}
                        {!r.errors.length && r.warnings.length > 0 && <div className="muted">{r.warnings.length} warning(s)</div>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!list.length && <Empty>No rows with this status.</Empty>}
          </div>
        )}
      </Card>
      {open && <RowDrawer row={open} recordType={b.record_type} onClose={() => setOpen(null)} onSaved={refresh} />}
    </div>
  );
}

function RowDrawer({ row, recordType, onClose, onSaved }: { row: Row; recordType: string; onClose: () => void; onSaved: (r?: Row) => void }) {
  const { toast, can } = useApp();
  const fields = useLoad(() => api.get<FieldDef[]>(`/api/import/fields?record_type=${recordType}`), [recordType]);
  const ai = useLoad(() => api.get<{ configured: boolean }>("/api/ai/status"), []);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [accept, setAccept] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const locked = row.status === "committed";

  const run = async (fn: () => Promise<Row>) => {
    setBusy(true);
    try {
      const r = await fn();
      setEdits({});
      onSaved(r);
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  const save = () => run(() => api.patch<Row>(`/api/staging-rows/${row.id}`, { changes: edits, reason: reason || null }));
  const act = (action: string) => run(() => api.post<Row>(`/api/staging-rows/${row.id}/action`, { action }));
  const extract = (use_ai: boolean) => run(() => api.post<Row>(`/api/staging-rows/${row.id}/extract`, { use_ai }));
  const resolve = () => {
    const sugg = row.suggestions ?? {};
    const keys = Object.keys(sugg);
    const ticked = (k: string) => accept[k] ?? sugg[k].confidence === "high";
    return run(() => api.post<Row>(`/api/staging-rows/${row.id}/suggestions`, {
      accept: keys.filter(ticked), reject: keys.filter((k) => !ticked(k)),
    }));
  };
  const issuesFor = (k: string) => [...row.errors, ...row.warnings].filter((e) => e.field === k);

  return (
    <Drawer title={`${row.sheet} · row ${row.row_number}`} onClose={onClose}
      footer={locked ? <span className="muted small">Committed as record #{row.committed_record_id}</span> : <>
        {row.status === "skipped"
          ? <button className="btn" onClick={() => act("unskip")} disabled={busy}>Restore row</button>
          : <button className="btn" onClick={() => act("skip")} disabled={busy}>Skip row</button>}
        {row.duplicate_of && (row.keep_duplicate
          ? <button className="btn" onClick={() => act("drop_duplicate")} disabled={busy}>Treat as duplicate</button>
          : <button className="btn" onClick={() => act("keep_duplicate")} disabled={busy}>Keep anyway</button>)}
        <button className="btn primary" disabled={busy || Object.keys(edits).length === 0} onClick={save}>Save corrections</button>
      </>}>
      <div className="stack">
        <div className="row wrap">
          <span className={`badge ${STATUS_TONE[row.status]}`}>{STATUS_TEXT[row.status]}</span>
          {row.duplicate_of && <span className="badge warn">Duplicate of {row.duplicate_of}</span>}
        </div>
        {row.errors.length > 0 && <div className="banner bad"><div>{row.errors.map((e, i) => <div key={i}>{e.message}</div>)}</div></div>}
        {row.warnings.length > 0 && <div className="banner warn"><div>{row.warnings.map((e, i) => <div key={i}>{e.message}</div>)}</div></div>}

        {row.suggestions && (
          <Card title="Extracted values awaiting your review">
            <div className="stack-sm">
              <div className="tiny muted">Nothing is applied until you accept it. Low-confidence values are unticked by default.</div>
              {Object.entries(row.suggestions).map(([k, s]) => (
                <label key={k} className="row" style={{ alignItems: "flex-start" }}>
                  <input type="checkbox" checked={accept[k] ?? s.confidence === "high"}
                    onChange={(e) => setAccept({ ...accept, [k]: e.target.checked })} />
                  <div>
                    <b>{k}</b>: {show(s.value)}{" "}
                    <span className={`badge ${s.confidence === "high" ? "good" : s.confidence === "medium" ? "warn" : "bad"}`}>{s.confidence}</span>{" "}
                    <span className="tiny muted">{s.method === "claude" ? "AI" : "rule"} · from “{s.raw}”</span>
                    {s.note && <div className="tiny" style={{ color: "var(--warn)" }}>{s.note}</div>}
                  </div>
                </label>
              ))}
              <div className="row">
                <button className="btn primary sm" disabled={busy} onClick={resolve}>Apply ticked, discard the rest</button>
              </div>
            </div>
          </Card>
        )}
        {!locked && !row.suggestions && (
          <div className="row wrap">
            <button className="btn sm" disabled={busy} onClick={() => extract(false)}>Extract specs from description (rules)</button>
            <button className="btn sm" disabled={busy || !ai.data?.configured || !can("use_ai")} onClick={() => extract(true)}
              title={ai.data?.configured ? "Claude suggests values; you review each one" : "AI is not configured on the server"}>
              Extract with AI
            </button>
          </div>
        )}

        <table className="t">
          <thead><tr><th>Field</th><th>Original cell</th><th>Parsed</th>{!locked && <th>Correction</th>}</tr></thead>
          <tbody>
            {(fields.data ?? []).map((f) => {
              const orig = row.mapped_raw[f.key];
              const corrected = f.key in row.corrections;
              const iss = issuesFor(f.key);
              return (
                <tr key={f.key}>
                  <td className="small"><b>{f.label}</b>{f.required && <span style={{ color: "var(--bad)" }}> *</span>}</td>
                  <td className="small">{corrected ? <span className="orig">{show(orig)}</span> : show(orig)}</td>
                  <td className="small">
                    {show(row.normalized[f.key])}
                    {corrected && <> <span className="pill-diff">corrected</span></>}
                    {iss.map((e, i) => <div key={i} className="tiny" style={{ color: row.errors.includes(e) ? "var(--bad)" : "var(--warn)" }}>{e.message}</div>)}
                  </td>
                  {!locked && (
                    <td>
                      <input style={{ width: "100%" }} placeholder={corrected ? String(row.corrections[f.key]) : ""}
                        value={edits[f.key] ?? ""} onChange={(e) => setEdits({ ...edits, [f.key]: e.target.value })} />
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
        {!locked && (
          <label className="field">Reason for corrections (kept in the audit trail)
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Supplier confirmed by phone" />
          </label>
        )}
      </div>
    </Drawer>
  );
}
