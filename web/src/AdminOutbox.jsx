import { useEffect, useState } from "react";

const call = async (url, opts = {}) => {
  const r = await fetch(url, { credentials: "same-origin", ...opts });
  const b = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof b.detail === "string" ? b.detail : "Request failed");
  return b;
};

const when = (iso) =>
  iso ? new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  }) : "—";

const FILTERS = [
  ["", "All"], ["queued", "Queued"], ["sent", "Sent"],
  ["suppressed", "Suppressed"], ["failed", "Failed"],
];

export default function AdminOutbox() {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState(null);
  const [err, setErr] = useState(null);
  const [note, setNote] = useState(null);

  const load = () =>
    call(`/api/admin/outbox${filter ? `?status=${filter}` : ""}`)
      .then(setData).catch((e) => setErr(e.message));

  useEffect(() => { load(); }, [filter]);

  const retry = async (id) => {
    setErr(null); setNote(null);
    try {
      const r = await call(`/api/admin/outbox/${id}/retry`, { method: "POST" });
      setNote(r.detail);
      await load();
    } catch (e) { setErr(e.message); }
  };

  if (!data) return <div className="setbody">{err || "Loading…"}</div>;

  return (
    <div className="setbody widepane mailqueue">
      {err && <div className="errbar" style={{ marginBottom: 14 }}>{err}</div>}
      {note && <div className="banner">{note}</div>}

      <p className="hint" style={{ marginTop: 0 }}>
        Sending from <strong>{data.from_address}</strong>
        {!data.smtp_enabled && " — delivery is currently disabled"}.
        Allowlist: {data.allowlist.join(", ")}
      </p>

      <div className="switch" style={{ marginBottom: 14, display: "inline-flex" }}>
        {FILTERS.map(([v, label]) => (
          <button key={v} data-on={filter === v} onClick={() => { setFilter(v); setOpen(null); }}>
            {label}
          </button>
        ))}
      </div>

      {data.messages.length === 0 && <p className="hint">Nothing here.</p>}

      <table className="utable">
        <thead>
          <tr>
            <th>Status</th><th>To</th><th>Subject</th>
            <th>Reason</th><th>Created</th><th>Sent</th><th></th>
          </tr>
        </thead>
        <tbody>
          {data.messages.map((m) => (
            <>
              <tr key={m.id}>
                <td>
                  <span className={"pill " + (
                    m.status === "sent" ? "ok-pill"
                    : m.status === "failed" ? "warn"
                    : m.status === "suppressed" ? "muted" : ""
                  )}>{m.status}</span>
                  {m.attempts > 0 && <div className="hint">{m.attempts} attempt(s)</div>}
                </td>
                <td>
                  <div className="uname">{m.to_email}</div>
                  {m.ticket_ref && <div className="hint mono">{m.ticket_ref}</div>}
                </td>
                <td>{m.subject}</td>
                <td className="hint">{m.reason}</td>
                <td className="hint">{when(m.created_at)}</td>
                <td className="hint">{when(m.sent_at)}</td>
                <td className="uactions">
                  <button className="msgact" onClick={() => setOpen(open === m.id ? null : m.id)}>
                    {open === m.id ? "Hide" : "Body"}
                  </button>
                  {m.status !== "sent" && (
                    <button className="msgact" onClick={() => retry(m.id)}>Retry</button>
                  )}
                </td>
              </tr>
              {open === m.id && (
                <tr key={`${m.id}-body`}>
                  <td colSpan={7}>
                    {m.last_error && <div className="errbar">{m.last_error}</div>}
                    <pre className="mailbody">{m.body}</pre>
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  );
}
