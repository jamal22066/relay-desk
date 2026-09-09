import { useEffect, useState } from "react";

const j = { "content-type": "application/json" };
const call = async (url, opts = {}) => {
  const r = await fetch(url, { credentials: "same-origin", ...opts });
  const b = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof b.detail === "string" ? b.detail : "Request failed");
  return b;
};

const ago = (iso) => {
  if (!iso) return "never";
  const d = Math.round((Date.now() - new Date(iso)) / 86400000);
  if (d === 0) return "today";
  return d === 1 ? "1 day ago" : `${d} days ago`;
};

export default function AdminUsers() {
  const [users, setUsers] = useState(null);
  const [err, setErr] = useState(null);
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(null);

  const load = () => call("/api/admin/users").then(setUsers).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const act = async (id, fn) => {
    setBusy(id); setErr(null); setNote(null);
    try {
      const r = await fn();
      setNote(r.detail || "Done");
      await load();
    } catch (e) {
      setErr(e.message);
      await load();   // the select kept the rejected value; resync with the server
    }
    finally { setBusy(null); }
  };

  const setRole = (u, role) =>
    act(u.id, () => call(`/api/admin/users/${u.id}`, {
      method: "PATCH", headers: j, body: JSON.stringify({ role }),
    }));

  const toggleActive = (u) =>
    act(u.id, () => call(`/api/admin/users/${u.id}`, {
      method: "PATCH", headers: j, body: JSON.stringify({ is_active: !u.is_active }),
    }));

  const markVerified = (u) =>
    act(u.id, () => call(`/api/admin/users/${u.id}`, {
      method: "PATCH", headers: j, body: JSON.stringify({ email_verified: true }),
    }));

  const resend = (u) =>
    act(u.id, () => call(`/api/admin/users/${u.id}/resend-verification`, { method: "POST" }));

  const remove = (u) => {
    if (!window.confirm(
      `Delete ${u.email}?\n\nTheir ${u.ticket_count} ticket(s) stay in the system with ` +
      `their name on them. This cannot be undone.`
    )) return;
    act(u.id, () => call(`/api/admin/users/${u.id}`, { method: "DELETE" }));
  };

  if (!users) return <div className="setbody">{err || "Loading accounts…"}</div>;

  return (
    <div className="setbody">
      {err && <div className="errbar" style={{ marginBottom: 14 }}>{err}</div>}
      {note && <div className="banner">{note}</div>}

      <table className="utable">
        <thead>
          <tr>
            <th>Account</th><th>Role</th><th>Source</th>
            <th>Status</th><th>Tickets</th><th>Last seen</th><th></th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} data-off={!u.is_active}>
              <td>
                <div className="uname">{u.display_name}</div>
                <div className="hint">{u.email} · {u.org}</div>
              </td>
              <td>
                <select className="field" value={u.role} disabled={busy === u.id}
                        onChange={(e) => setRole(u, e.target.value)}>
                  <option value="customer">customer</option>
                  <option value="agent">agent</option>
                  <option value="admin">admin</option>
                </select>
                {u.role_override && <div className="hint">override</div>}
              </td>
              <td className="hint">{u.auth_source}</td>
              <td>
                {!u.is_active && <span className="pill muted">disabled</span>}
                {u.is_active && !u.email_verified && <span className="pill warn">unverified</span>}
                {u.is_active && u.email_verified && <span className="hint">active</span>}
              </td>
              <td className="mono">{u.ticket_count}</td>
              <td className="hint">{ago(u.last_login_at)}</td>
              <td className="uactions">
                {!u.email_verified && u.auth_source === "local" && (
                  <>
                    <button className="msgact" disabled={busy === u.id}
                            onClick={() => resend(u)}>Resend link</button>
                    <button className="msgact" disabled={busy === u.id}
                            onClick={() => markVerified(u)}>Mark verified</button>
                  </>
                )}
                <button className="msgact" disabled={busy === u.id}
                        onClick={() => toggleActive(u)}>
                  {u.is_active ? "Disable" : "Enable"}
                </button>
                <button className="msgact danger" disabled={busy === u.id}
                        onClick={() => remove(u)}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="hint" style={{ marginTop: 18 }}>
        Deleting an account leaves its tickets in place. You cannot change or remove your
        own account, or the last remaining administrator.
      </p>
    </div>
  );
}
