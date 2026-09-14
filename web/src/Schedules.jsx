import { useEffect, useState } from "react";
import { api } from "./api";

const when = (iso) =>
  iso ? new Date(iso).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  }) : "—";

/** ISO string for a datetime-local input, in the browser's timezone. */
const toLocalInput = (d) => {
  const off = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - off).toISOString().slice(0, 16);
};

const blank = (meta) => ({
  name: "",
  kind: "once",
  next_run_at: toLocalInput(new Date(Date.now() + 86400000)),
  recur_every: 1,
  recur_unit: "months",
  subject: "",
  body: "",
  track: "it",
  category: meta.categories.it[0],
  priority: "P3",
  requester_email: "",
  assignee: "Unassigned",
});

export default function Schedules({ meta }) {
  const [rows, setRows] = useState(null);
  const [f, setF] = useState(null);
  const [adding, setAdding] = useState(false);
  const [people, setPeople] = useState([]);
  const [err, setErr] = useState(null);
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(null);

  const load = () => api.listSchedules().then(setRows).catch((e) => setErr(e.message));

  useEffect(() => {
    load();
    api.lookupUsers("").then(setPeople).catch(() => {});
  }, []);

  if (!rows) return <div className="setbody">{err || "Loading schedules…"}</div>;

  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  const startAdd = () => { setF(blank(meta)); setAdding(true); setErr(null); setNote(null); };

  const act = async (id, fn) => {
    setBusy(id); setErr(null); setNote(null);
    try { const r = await fn(); setNote(r.detail || "Done"); await load(); }
    catch (e) { setErr(e.message); }
    finally { setBusy(null); }
  };

  const save = async () => {
    setBusy("new"); setErr(null);
    try {
      const payload = {
        ...f,
        next_run_at: new Date(f.next_run_at).toISOString(),
        recur_every: f.kind === "recurring" ? Number(f.recur_every) : null,
        recur_unit: f.kind === "recurring" ? f.recur_unit : null,
      };
      await api.createSchedule(payload);
      setAdding(false);
      setNote("Schedule created.");
      await load();
    } catch (e) { setErr(e.message); }
    finally { setBusy(null); }
  };

  const remove = (s) => {
    if (!window.confirm(
      `Delete "${s.name}"?\n\nTickets it already created stay in the system.`
    )) return;
    act(s.id, () => api.deleteSchedule(s.id));
  };

  const cadence = (s) =>
    s.kind === "once" ? "once" : `every ${s.recur_every} ${s.recur_unit}`;

  return (
    <div className="setbody widepane schedules">
      {err && <div className="errbar" style={{ marginBottom: 14 }}>{err}</div>}
      {note && <div className="banner">{note}</div>}

      <p className="hint" style={{ marginTop: 0 }}>
        Schedules create tickets automatically. Each generated ticket carries a
        system event naming the schedule, so the audit trail shows it was not
        filed by a person. A failed schedule stops firing until reactivated.
      </p>

      {!adding && (
        <button className="btn teal" onClick={startAdd} style={{ marginBottom: 16 }}>
          New schedule
        </button>
      )}

      {adding && f && (
        <div className="form" style={{ marginBottom: 20 }}>
          <div className="fgroup">
            <label htmlFor="s-name">Name</label>
            <input id="s-name" className="field" value={f.name}
                   placeholder="Quarterly certificate review"
                   onChange={(e) => set("name", e.target.value)} />
          </div>

          <div className="row2">
            <div className="fgroup">
              <label htmlFor="s-kind">Repeats</label>
              <select id="s-kind" className="field" value={f.kind}
                      onChange={(e) => set("kind", e.target.value)}>
                <option value="once">Once</option>
                <option value="recurring">On a cadence</option>
              </select>
            </div>
            <div className="fgroup">
              <label htmlFor="s-when">First run</label>
              <input id="s-when" className="field" type="datetime-local"
                     value={f.next_run_at}
                     onChange={(e) => set("next_run_at", e.target.value)} />
              <div className="hint">
                For a lead time, set this to the date the ticket should appear —
                30 days before the maintenance window, for instance.
              </div>
            </div>
          </div>

          {f.kind === "recurring" && (
            <div className="row2">
              <div className="fgroup">
                <label htmlFor="s-every">Every</label>
                <input id="s-every" className="field" type="number" min="1" max="365"
                       value={f.recur_every}
                       onChange={(e) => set("recur_every", e.target.value)} />
              </div>
              <div className="fgroup">
                <label htmlFor="s-unit">Unit</label>
                <select id="s-unit" className="field" value={f.recur_unit}
                        onChange={(e) => set("recur_unit", e.target.value)}>
                  <option value="days">days</option>
                  <option value="weeks">weeks</option>
                  <option value="months">months (30 days)</option>
                </select>
              </div>
            </div>
          )}

          <div className="row2">
            <div className="fgroup">
              <label htmlFor="s-req">File on behalf of</label>
              <select id="s-req" className="field" value={f.requester_email}
                      onChange={(e) => set("requester_email", e.target.value)}>
                <option value="">Choose an account…</option>
                {people.map((p) => (
                  <option key={p.email} value={p.email}>
                    {p.display_name} — {p.email}
                  </option>
                ))}
              </select>
            </div>
            <div className="fgroup">
              <label htmlFor="s-assignee">Assign to</label>
              <select id="s-assignee" className="field" value={f.assignee}
                      onChange={(e) => set("assignee", e.target.value)}>
                {meta.agents.map((a) => <option key={a}>{a}</option>)}
              </select>
            </div>
          </div>

          <div className="row2">
            <div className="fgroup">
              <label htmlFor="s-track">Service line</label>
              <select id="s-track" className="field" value={f.track}
                      onChange={(e) => { set("track", e.target.value); set("category", meta.categories[e.target.value][0]); }}>
                <option value="saas">SaaS product</option>
                <option value="it">Workplace IT</option>
              </select>
            </div>
            <div className="fgroup">
              <label htmlFor="s-cat">Topic</label>
              <select id="s-cat" className="field" value={f.category}
                      onChange={(e) => set("category", e.target.value)}>
                {meta.categories[f.track].map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
          </div>

          <div className="fgroup">
            <label htmlFor="s-pri">Priority</label>
            <select id="s-pri" className="field" value={f.priority}
                    onChange={(e) => set("priority", e.target.value)}>
              {meta.priorities.map((p) => <option key={p.id} value={p.id}>{p.id}</option>)}
            </select>
          </div>

          <div className="fgroup">
            <label htmlFor="s-subj">Ticket subject</label>
            <input id="s-subj" className="field" value={f.subject}
                   onChange={(e) => set("subject", e.target.value)} />
          </div>

          <div className="fgroup">
            <label htmlFor="s-body">Ticket description</label>
            <textarea id="s-body" className="field" rows={4} value={f.body}
                      onChange={(e) => set("body", e.target.value)} />
          </div>

          <div className="formfoot">
            <button className="btn teal" disabled={busy === "new"} onClick={save}>
              {busy === "new" ? "Saving…" : "Create schedule"}
            </button>
            <button className="btn ghost" onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </div>
      )}

      {rows.length === 0 && <p className="hint">No schedules yet.</p>}

      <table className="utable">
        <thead>
          <tr>
            <th>Schedule</th><th>Status</th><th>Cadence</th>
            <th>Next run</th><th>Runs</th><th>Assignee</th><th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id} data-off={s.status !== "active"}>
              <td>
                <div className="uname">{s.name}</div>
                <div className="hint">{s.subject}</div>
                {s.last_error && <div className="hint bad">{s.last_error}</div>}
              </td>
              <td>
                <span className={"pill " + (
                  s.status === "active" ? "ok-pill"
                  : s.status === "failed" ? "warn" : "muted"
                )}>{s.status}</span>
              </td>
              <td className="hint">{cadence(s)}</td>
              <td className="hint">{s.status === "completed" ? "—" : when(s.next_run_at)}</td>
              <td className="mono">{s.run_count}</td>
              <td className="hint">{s.assignee}</td>
              <td className="uactions">
                {s.status === "active" && (
                  <button className="msgact" disabled={busy === s.id}
                          onClick={() => act(s.id, () => api.patchSchedule(s.id, { status: "paused" }))}>
                    Pause
                  </button>
                )}
                {(s.status === "paused" || s.status === "failed") && (
                  <button className="msgact" disabled={busy === s.id}
                          onClick={() => act(s.id, () => api.patchSchedule(s.id, { status: "active" }))}>
                    Resume
                  </button>
                )}
                <button className="msgact" disabled={busy === s.id}
                        onClick={() => act(s.id, () => api.runScheduleNow(s.id))}>
                  Run now
                </button>
                <button className="msgact danger" disabled={busy === s.id}
                        onClick={() => remove(s)}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
