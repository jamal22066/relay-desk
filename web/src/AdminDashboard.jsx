import { useEffect, useState } from "react";

const call = async (url) => {
  const r = await fetch(url, { credentials: "same-origin" });
  const b = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof b.detail === "string" ? b.detail : "Request failed");
  return b;
};

const when = (iso) =>
  new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });

function Stat({ label, value, tone }) {
  return (
    <div className="stat" data-tone={tone}>
      <div className="statv mono">{value}</div>
      <div className="statl">{label}</div>
    </div>
  );
}

export default function AdminDashboard() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => { call("/api/admin/dashboard").then(setD).catch((e) => setErr(e.message)); }, []);
  if (!d) return <div className="setbody">{err || "Loading…"}</div>;

  const open = ["New", "Open", "Waiting on customer"]
    .reduce((n, s) => n + (d.tickets.by_status[s] || 0), 0);

  return (
    <div className="setbody">
      <div className="statrow">
        <Stat label="Open tickets" value={open} />
        <Stat label="Unassigned" value={d.tickets.unassigned} tone={d.tickets.unassigned ? "warn" : null} />
        <Stat label="Past due" value={d.tickets.breaching} tone={d.tickets.breaching ? "bad" : null} />
        <Stat label="Due within 4h" value={d.tickets.due_soon} />
      </div>

      <div className="minehead" style={{ marginTop: 26 }}>By priority</div>
      <div className="statrow">
        {["P1", "P2", "P3", "P4"].map((p) => (
          <Stat key={p} label={p} value={d.tickets.by_priority[p] || 0} />
        ))}
      </div>

      <div className="minehead" style={{ marginTop: 26 }}>Email queue</div>
      <div className="statrow">
        <Stat label="Sent" value={d.outbox.sent || 0} />
        <Stat label="Queued" value={d.outbox.queued || 0} />
        <Stat label="Suppressed" value={d.outbox.suppressed || 0}
              tone={d.outbox.suppressed ? "warn" : null} />
        <Stat label="Failed" value={d.outbox.failed || 0}
              tone={d.outbox.failed ? "bad" : null} />
      </div>
      {d.outbox.suppressed > 0 && (
        <p className="hint">
          Suppressed messages were blocked by the recipient allowlist, not a delivery failure.
        </p>
      )}

      <div className="minehead" style={{ marginTop: 26 }}>Schedules</div>
      <div className="statrow">
        <Stat label="Active" value={d.schedules?.active ?? 0} />
        <Stat label="Failed" value={d.schedules?.failed ?? 0}
              tone={d.schedules?.failed ? "bad" : null} />
      </div>
      {d.schedules?.failed > 0 && (
        <p className="hint">
          A failed schedule stops firing until it is resumed.
        </p>
      )}

      <div className="minehead" style={{ marginTop: 26 }}>Accounts</div>
      <div className="statrow">
        <Stat label="Total" value={d.users.total} />
        <Stat label="Unverified" value={d.users.unverified}
              tone={d.users.unverified ? "warn" : null} />
        <Stat label="Disabled" value={d.users.inactive} />
      </div>

      <div className="minehead" style={{ marginTop: 26 }}>Recent activity</div>
      <div className="feed">
        {d.recent.length === 0 && <p className="hint">Nothing yet.</p>}
        {d.recent.map((e, i) => (
          <div className="feedrow" key={i}>
            <span className="qid mono">{e.ticket_ref}</span>
            <span className="feedwho">{e.actor}</span>
            <span className="feedtxt">{e.summary}</span>
            <span className="hint">{when(e.at)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
