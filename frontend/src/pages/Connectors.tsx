import { useState } from "react";
import { api } from "../api";
import { Card, ErrorBox, Loading, PageHead } from "../components/ui";
import { useApp, useLoad } from "../context";
import { dateTime } from "../format";

interface Conn {
  id: number; name: string; adapter: string; title: string; description: string; live_capable: boolean; enabled: boolean;
  status: string; config: Record<string, unknown>; config_problems: string[]; last_attempt_at: string | null;
  last_success_at: string | null; last_error: string | null; failure_count: number; last_records: number | null;
  evidence_records: number; stale_records: number;
}

const TONE: Record<string, string> = { active: "good", configured: "info", error: "bad", not_configured: "", disabled: "" };

export default function Connectors() {
  const { can, toast } = useApp();
  const conns = useLoad(() => api.get<Conn[]>("/api/connectors"), []);
  const [edit, setEdit] = useState<Conn | null>(null);
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  if (conns.loading && !conns.data) return <Loading />;
  const live = (conns.data ?? []).some((c) => c.live_capable && c.status === "active");

  const save = async (enable?: boolean) => {
    setErr(null);
    try {
      await api.put(`/api/connectors/${edit!.id}`, { config: JSON.parse(text || "{}"), ...(enable === undefined ? {} : { enabled: enable }) });
      setEdit(null);
      conns.reload();
    } catch (e) {
      setErr(e instanceof SyntaxError ? "Configuration is not valid JSON" : (e as Error).message);
    }
  };
  const run = async (c: Conn) => {
    try {
      const r = await api.post<{ created: number; rejected: number; duplicates_skipped: number }>(`/api/connectors/${c.id}/run`);
      toast(`Fetched: ${r.created} new, ${r.rejected} rejected, ${r.duplicates_skipped} already held.`);
    } catch (e) {
      toast((e as Error).message, true);
    }
    conns.reload();
  };

  return (
    <div className="stack fade-in">
      <PageHead title="Connectors" sub="Where market evidence comes from, and whether it is current. Live coverage is claimed only once a real, permitted feed is configured and has fetched successfully." />
      <div className={`banner ${live ? "good" : "info"}`}>
        {live ? "A live feed is active." : <><b>No live market connector is configured.</b>&nbsp;All evidence is manual entry or file upload. No web scraping is performed and no demo data is substituted.</>}
      </div>
      <div className="grid g3">
        {(conns.data ?? []).map((c) => (
          <Card key={c.id} title={c.name} actions={<span className={`badge ${TONE[c.status] ?? ""}`}>{c.status.replace("_", " ")}</span>}>
            <div className="stack-sm">
              <div className="small muted">{c.description}</div>
              <dl className="kv small">
                <dt>Evidence records</dt><dd>{c.evidence_records} <span className="muted">({c.stale_records} past freshness limit)</span></dd>
                {c.live_capable && <>
                  <dt>Last success</dt><dd>{dateTime(c.last_success_at)}</dd>
                  <dt>Last attempt</dt><dd>{dateTime(c.last_attempt_at)}</dd>
                  <dt>Failures</dt><dd>{c.failure_count}</dd>
                  <dt>Last fetch</dt><dd>{c.last_records ?? "—"} records</dd>
                </>}
              </dl>
              {c.last_error && <div className="banner bad small">{c.last_error}</div>}
              {c.config_problems.length > 0 && <div className="banner warn small"><div>{c.config_problems.map((p) => <div key={p}>{p}</div>)}</div></div>}
              {c.live_capable && can("manage_connectors") && (
                <div className="row">
                  <button className="btn sm" onClick={() => { setEdit(c); setText(JSON.stringify(c.config, null, 2)); }}>Configure</button>
                  <button className="btn sm primary" disabled={!c.enabled} onClick={() => run(c)}>Fetch now</button>
                </div>
              )}
            </div>
          </Card>
        ))}
      </div>
      {edit && (
        <Card title={`Configure ${edit.name}`} actions={<>
          <button className="btn" onClick={() => setEdit(null)}>Cancel</button>
          <button className="btn" onClick={() => save()}>Save</button>
          <button className="btn" onClick={() => save(false)}>Save & disable</button>
          <button className="btn primary" onClick={() => save(true)}>Save & enable</button>
        </>}>
          <div className="stack-sm">
            <ErrorBox error={err} />
            <div className="small muted">
              Required: <span className="mono">url</span> (https), <span className="mono">terms_confirmed: true</span> once you have confirmed the provider permits this use,
              <span className="mono"> field_map</span> (our field → feed key, e.g. brand, model, price, listing_date), and <span className="mono">default_channel</span>.
              Optional: <span className="mono">records_path</span>, <span className="mono">api_key_env</span> (name of a server environment variable holding the key; never the key itself),
              <span className="mono"> api_key_header</span>, <span className="mono">default_tax_basis</span>, <span className="mono">platform</span>.
            </div>
            <textarea rows={16} className="mono" value={text} onChange={(e) => setText(e.target.value)} style={{ width: "100%" }} />
          </div>
        </Card>
      )}
    </div>
  );
}
