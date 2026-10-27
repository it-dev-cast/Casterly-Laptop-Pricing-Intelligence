import { useState } from "react";
import { api } from "../api";
import { Card, ErrorBox, Loading, PageHead } from "../components/ui";
import { useApp, useLoad } from "../context";
import { dateTime } from "../format";
import type { User } from "../types";

interface AuditRow { id: number; at: string; user: string | null; action: string; entity_type: string | null; entity_id: string | null; details: Record<string, unknown> | null }

export default function Admin() {
  const { can, toast, user: me } = useApp();
  const users = useLoad(() => (can("manage_users") ? api.get<User[]>("/api/users") : Promise.resolve([])), []);
  const [filter, setFilter] = useState("");
  const audit = useLoad(() => api.get<AuditRow[]>(`/api/audit?limit=400${filter ? `&action=${encodeURIComponent(filter)}` : ""}`), [filter]);
  const [nu, setNu] = useState({ email: "", name: "", role: "procurement", password: "" });
  const [err, setErr] = useState<string | null>(null);
  const [demoBusy, setDemoBusy] = useState(false);

  if (!can("view_audit")) return <div className="banner warn">Administrators only.</div>;
  const create = async () => {
    setErr(null);
    try {
      await api.post("/api/users", nu);
      toast(`User ${nu.email} created.`);
      setNu({ email: "", name: "", role: "procurement", password: "" });
      users.reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const patch = async (id: number, body: Record<string, unknown>) => {
    try {
      await api.patch(`/api/users/${id}`, body);
      users.reload();
      audit.reload();
    } catch (e) {
      toast((e as Error).message, true);
    }
  };
  const demo = async (load: boolean) => {
    if (!load && !window.confirm("Remove all synthetic demo records? Real records are not affected.")) return;
    setDemoBusy(true);
    try {
      const r = load ? await api.post<{ message?: string }>("/api/admin/demo") : await api.del("/api/admin/demo");
      toast(load ? ((r as { message?: string }).message ?? "Synthetic demo data loaded.") : "Synthetic demo data removed.");
      audit.reload();
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setDemoBusy(false);
    }
  };

  return (
    <div className="stack fade-in">
      <PageHead title="Users & audit" sub="Role-based access and the complete history of who changed what." />
      <div className="grid g2">
        <Card title="Users" tight>
          {users.loading && !users.data ? <Loading /> : (
            <table className="t">
              <thead><tr><th>User</th><th>Role</th><th>Active</th></tr></thead>
              <tbody>
                {(users.data ?? []).map((u) => (
                  <tr key={u.id}>
                    <td><b>{u.name}</b><div className="small muted">{u.email}</div></td>
                    <td><select value={u.role} disabled={u.id === me?.id} onChange={(e) => patch(u.id, { role: e.target.value })}>
                      <option value="admin">Administrator</option><option value="procurement">Procurement</option><option value="sales">Sales</option></select></td>
                    <td><input type="checkbox" checked={u.is_active} disabled={u.id === me?.id} onChange={(e) => patch(u.id, { is_active: e.target.checked })} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div style={{ padding: 14, borderTop: "1px solid var(--line)" }} className="stack-sm">
            <h3>Add user</h3>
            <ErrorBox error={err} />
            <div className="formgrid">
              <input placeholder="Email" value={nu.email} onChange={(e) => setNu({ ...nu, email: e.target.value })} />
              <input placeholder="Name" value={nu.name} onChange={(e) => setNu({ ...nu, name: e.target.value })} />
              <select value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}><option value="procurement">Procurement</option><option value="sales">Sales</option><option value="admin">Administrator</option></select>
              <input type="password" placeholder="Initial password (10+ chars)" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} />
            </div>
            <button className="btn primary" style={{ alignSelf: "flex-start" }} onClick={create}>Create user</button>
            <div className="tiny muted">Administrator: everything, including settings, users and connectors. Procurement: import, edit inventory and evidence, record purchases, value. Sales: view, value, add listings, record sales, export.</div>
          </div>
        </Card>
        <Card title="Synthetic demo dataset">
          <div className="stack-sm">
            <div className="small">Generates a clearly labelled sample lot and evidence for demonstrations and training. It is flagged synthetic everywhere, shown only in the demo view, has no source URLs, and is never used to value real inventory.</div>
            <div className="row">
              <button className="btn" disabled={demoBusy} onClick={() => demo(true)}>Load demo data</button>
              <button className="btn danger" disabled={demoBusy} onClick={() => demo(false)}>Remove demo data</button>
            </div>
          </div>
        </Card>
      </div>
      <Card tight title={<div className="row"><h2>Audit log</h2><input placeholder="Filter by action prefix, e.g. import." value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 260 }} /></div>}>
        <div className="tablewrap" style={{ maxHeight: 560 }}>
          <table className="t">
            <thead><tr><th>When</th><th>User</th><th>Action</th><th>Entity</th><th>Details</th></tr></thead>
            <tbody>
              {(audit.data ?? []).map((a) => (
                <tr key={a.id}>
                  <td className="small nowrap">{dateTime(a.at)}</td>
                  <td className="small">{a.user ?? <span className="muted">system</span>}</td>
                  <td><span className="mono">{a.action}</span></td>
                  <td className="small">{a.entity_type ? `${a.entity_type} ${a.entity_id ?? ""}` : "—"}</td>
                  <td className="mono tiny" style={{ maxWidth: 520, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{a.details ? JSON.stringify(a.details) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
