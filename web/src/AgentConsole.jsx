import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import NewTicket from "./NewTicket";
import { AttachmentList, AttachmentPicker } from "./Attachments";
import { OPEN_STATUSES, countdown, initials, priColor, relative, stamp } from "./util";

const VIEWS = [
  ["all", "All open"], ["mine", "Assigned to me"], ["unassigned", "Unassigned"],
  ["breach", "Past due"], ["done", "Resolved"],
];

export default function AgentConsole({ meta, initialRef }) {
  const [view, setView] = useState("all");
  const [track, setTrack] = useState(null);
  const [q, setQ] = useState("");
  const [list, setList] = useState([]);
  const [counts, setCounts] = useState({ views: {}, tracks: {} });
  const [ref, setRef] = useState(initialRef ?? null);
  // a deep-linked ticket may not be in the default queue, so let it survive
  // the first refresh before auto-selection resumes
  const holdDeepLink = useRef(Boolean(initialRef));
  const [active, setActive] = useState(null);
  const [err, setErr] = useState(null);
  const [creating, setCreating] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [rows, c] = await Promise.all([api.list(view, track, q), api.counts()]);
      setList(rows);
      setCounts(c);
      setErr(null);
      if (holdDeepLink.current) {
        holdDeepLink.current = false;
      } else if (!rows.some((t) => t.ref === ref)) {
        setRef(rows[0]?.ref ?? null);
      }
    } catch (e) { setErr(e.message); }
  }, [view, track, q, ref]);

  useEffect(() => { refresh(); }, [view, track, q]);
  useEffect(() => {
    const i = setInterval(refresh, 60000);
    return () => clearInterval(i);
  }, [refresh]);

  useEffect(() => {
    if (!ref) { setActive(null); return; }
    api.get(ref).then(setActive).catch((e) => setErr(e.message));
  }, [ref]);

  const onChanged = (t) => {
    setActive(t);
    refresh();
  };

  return (
    <div className="frame">
      <nav className="rail">
        <div className="railgroup">
          <div className="railtitle">Queues</div>
          {VIEWS.map(([id, label]) => (
            <button key={id} className="railitem" data-on={view === id} onClick={() => setView(id)}>
              <span className="label">{label}</span>
              <span className={"count mono" + (id === "breach" && counts.views.breach > 0 && view !== id ? " dotwarn" : "")}>
                {counts.views[id] ?? "–"}
              </span>
            </button>
          ))}
        </div>
        <div className="railgroup">
          <div className="railtitle">Service line</div>
          <button className="railitem" data-on={track === null} onClick={() => setTrack(null)}>
            <span className="label">Everything</span>
          </button>
          {Object.keys(meta.categories).map((k) => (
            <button key={k} className="railitem" data-on={track === k} onClick={() => setTrack(k)}>
              <span className="label">{k === "saas" ? "SaaS product" : "Workplace IT"}</span>
              <span className="count mono">{counts.tracks[k] ?? "–"}</span>
            </button>
          ))}
        </div>
      </nav>

      <div className="queue">
        <div className="searchwrap">
          <div className="searchrow">
            <input className="search" placeholder="Search tickets, people, orgs"
                   value={q} onChange={(e) => setQ(e.target.value)} />
            <button className="btn teal newbtn" onClick={() => setCreating(true)}
                    title="New ticket">+</button>
          </div>
        </div>
        <div className="qlist">
          {err && <div className="errbar">{err}</div>}
          {list.length === 0 && !err ? (
            <div className="empty">Nothing here. Try another queue or clear the search.</div>
          ) : list.map((t) => (
            <button key={t.ref} className="qrow" data-on={ref === t.ref}
                    style={{ borderLeftColor: ref === t.ref ? "var(--teal)" : priColor[t.priority] }}
                    onClick={() => setRef(t.ref)}>
              <div className="qtop">
                <span className="pri mono" style={{ color: priColor[t.priority] }}>{t.priority}</span>
                <span className="qid mono">{t.ref}</span>
                <span className="clock mono" data-late={t.breaching}>
                  {OPEN_STATUSES.includes(t.status) ? countdown(t.due_at) : t.status}
                </span>
              </div>
              <div className="qsub">{t.subject}</div>
              <div className="qmeta">
                <span>{t.org}</span><span>{t.category}</span>
                <span style={{ marginLeft: "auto" }}>{relative(t.updated_at)}</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {creating ? (
        <NewTicket meta={meta} onCancel={() => setCreating(false)}
                   onCreated={(ref) => { setCreating(false); setRef(ref); refresh(); }} />
      ) : active ? (
        <Detail t={active} meta={meta} onChanged={onChanged} />
      ) : (
        <div className="detail"><div className="empty">Pick a ticket to read it.</div></div>
      )}
    </div>
  );
}

function Detail({ t, meta, onChanged }) {
  const [draft, setDraft] = useState("");
  const [internal, setInternal] = useState(false);
  const [staged, setStaged] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => { setDraft(""); setInternal(false); setStaged([]); setErr(null); }, [t.ref]);

  const run = async (fn) => {
    setBusy(true);
    try { onChanged(await fn()); setErr(null); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };

  const remove = (id) => {
    if (!window.confirm("Remove this message? The text stops being visible to anyone, but the record stays.")) return;
    run(() => api.deleteEvent(t.ref, id));
  };

  const send = async () => {
    const body = draft.trim();
    if (!body && staged.length === 0) return;
    setBusy(true);
    try {
      // check the files before posting anything, so a rejected upload cannot
      // leave an orphaned message behind
      if (staged.length > 0) await api.validateAttachments(staged);

      const updated = await api.addEvent(
        t.ref, body || "(attachment)", internal ? "note" : "comment");
      if (staged.length > 0) {
        const evId = updated.events[updated.events.length - 1].id;
        await api.uploadAttachments(t.ref, evId, staged);
      }
      onChanged(await api.get(t.ref));
      setDraft("");
      setStaged([]);
      setErr(null);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const events = t.events;
  const hours = meta.priorities.find((p) => p.id === t.priority).hours;

  return (
    <div className="detail">
      <div className="dhead">
        <div className="dsub mono">
          {t.ref} <span style={{ color: priColor[t.priority] }}>{t.priority}</span>
        </div>
        <h1 className="dtitle">{t.subject}</h1>
        <div className="dsub">
          {t.requester} at {t.org} — {t.email} — opened {relative(t.created_at)} in {t.category}
        </div>
      </div>

      {err && <div className="errbar">{err}</div>}

      <div className="controls">
        {[["status", "Status", meta.statuses],
          ["priority", "Priority", meta.priorities.map((p) => p.id)],
          ["assignee", "Owner", meta.agents]].map(([field, label, options]) => (
          <div className="ctrl" key={field}>
            <label htmlFor={`${field}-${t.ref}`}>{label}</label>
            <select id={`${field}-${t.ref}`} className="field" value={t[field]} disabled={busy}
                    onChange={(e) => run(() => api.patch(t.ref, { [field]: e.target.value }))}>
              {options.map((o) => <option key={o}>{o}</option>)}
            </select>
          </div>
        ))}
      </div>

      <div className="slabar mono" data-late={t.breaching}>
        {OPEN_STATUSES.includes(t.status) ? (
          <>
            <span>{t.breaching ? "Past due by" : "Due in"}</span>
            <span>{countdown(t.due_at).replace("-", "")}</span>
            <span style={{ fontFamily: "'IBM Plex Sans'", opacity: 0.7 }}>
              {hours}h target, set when the ticket was filed
            </span>
          </>
        ) : (
          <span style={{ fontFamily: "'IBM Plex Sans'" }}>{t.status} — the clock has stopped.</span>
        )}
      </div>

      <div className="thread">
        {events.map((e) => e.kind === "system" ? (
          <div key={e.id} className="dsub sysline">{e.body} — {e.actor}, {stamp(e.at)}</div>
        ) : (
          <div key={e.id} className="msg" data-note={e.kind === "note"} data-gone={!!e.deleted_at}>
            <div className="av" data-agent={meta.agents.includes(e.actor)}>{initials(e.actor)}</div>
            <div className="mbody">
              <div className="mhead">
                <span className="mname">{e.actor}</span>
                <span className="mtime mono">{stamp(e.at)}</span>
                {e.kind === "note" && !e.deleted_at && <span className="notetag">Internal, not sent</span>}
                {!e.is_original && !e.deleted_at && (
                  <button className="msgact" disabled={busy}
                          onClick={() => remove(e.id)}>Remove</button>
                )}
              </div>
              {e.deleted_at ? (
                <div className="mtext tomb">
                  Message removed by {e.deleted_by} on {stamp(e.deleted_at)}
                </div>
              ) : (
                <>
                  <div className="mtext">{e.body}</div>
                  <AttachmentList items={e.attachments} canRemove
                                  onRemoved={async () => onChanged(await api.get(t.ref))} />
                </>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="reply">
        {err && <div className="errbar attacherr">{err}</div>}
        <div className="replybox">
          <textarea value={draft} disabled={busy}
                    placeholder={internal ? "Leave a note for the team" : `Reply to ${t.requester}`}
                    onChange={(e) => setDraft(e.target.value)} />
          <div className="replyfoot">
            <label className="toggle">
              <input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} />
              Internal note
            </label>
            <AttachmentPicker files={staged} onChange={setStaged} disabled={busy} />
            <div className="spacer" />
            <button className={"btn" + (internal ? " ghost" : " teal")}
                    disabled={busy || (!draft.trim() && staged.length === 0)} onClick={send}>
              {internal ? "Save note" : "Send reply"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
