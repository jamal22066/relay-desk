import { useEffect, useState } from "react";
import { api } from "./api";
import { IMPACT, OPEN_STATUSES, initials, priColor, stamp } from "./util";

const blank = (meta) => ({
  track: "saas",
  category: meta.categories.saas[0],
  priority: "P3",
  subject: "",
  body: "",
});

export default function Portal({ me }) {
  const [meta, setMeta] = useState(null);
  const [f, setF] = useState(null);
  const [filed, setFiled] = useState(null);
  const [mine, setMine] = useState([]);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.portalList().then(setMine).catch((e) => setErr(e.message));

  useEffect(() => {
    api.portalMeta()
      .then((m) => { setMeta(m); setF(blank(m)); })
      .catch((e) => setErr(e.message));
    load();
  }, []);

  if (!meta || !f) {
    return <div className="portal"><div className="loading">Loading…</div></div>;
  }

  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  const valid = f.subject.trim().length > 2 && f.body.trim().length > 2;
  const hours = meta.priorities.find((p) => p.id === f.priority).hours;

  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true);
    try {
      const t = await api.create(f);
      setFiled(t.ref);
      setF(blank(meta));
      await load();
      setErr(null);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="portal">
      <div className="pinner">
        {filed && (
          <div className="banner">
            Ticket <strong className="mono">{filed}</strong> is filed. It appears below, and
            replies from support show up there.
          </div>
        )}
        {err && <div className="errbar" style={{ marginBottom: 20 }}>{err}</div>}

        <h1 className="plead">Tell us what broke</h1>
        <p className="pdek">
          One form for the product and for your laptop. The more specific you are about what you
          did and what happened instead, the faster this gets resolved.
        </p>

        <div className="form">
          <div className="row2">
            <div className="fgroup">
              <label htmlFor="p-track">What is this about</label>
              <select id="p-track" className="field" value={f.track}
                      onChange={(e) => { set("track", e.target.value); set("category", meta.categories[e.target.value][0]); }}>
                <option value="saas">SaaS product</option>
                <option value="it">Workplace IT</option>
              </select>
            </div>
            <div className="fgroup">
              <label htmlFor="p-cat">Topic</label>
              <select id="p-cat" className="field" value={f.category}
                      onChange={(e) => set("category", e.target.value)}>
                {meta.categories[f.track].map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
          </div>

          <div className="fgroup">
            <label htmlFor="p-pri">How badly is this blocking you</label>
            <select id="p-pri" className="field" value={f.priority}
                    onChange={(e) => set("priority", e.target.value)}>
              {meta.priorities.map((p) => <option key={p.id} value={p.id}>{IMPACT[p.id]}</option>)}
            </select>
            <div className="hint">We aim to respond within {hours} hours for this level.</div>
          </div>

          <div className="fgroup">
            <label htmlFor="p-sub">One-line summary</label>
            <input id="p-sub" className="field" value={f.subject}
                   placeholder="SAML login loops back to the sign-in page"
                   onChange={(e) => set("subject", e.target.value)} />
          </div>

          <div className="fgroup">
            <label htmlFor="p-body">What happened</label>
            <textarea id="p-body" className="field" rows={6} value={f.body}
                      placeholder="What you were doing, what you expected, what happened instead, and when it started."
                      onChange={(e) => set("body", e.target.value)} />
          </div>

          <div className="formfoot">
            <button className="btn teal" disabled={!valid || busy} onClick={submit}>
              {busy ? "Filing…" : "File ticket"}
            </button>
            {!valid && <span className="hint">A summary and a description are needed.</span>}
          </div>
        </div>

        <div className="mine">
          <div className="minehead">Your tickets</div>
          {mine.length === 0 && <p className="hint">Nothing filed yet.</p>}
          {mine.map((t) => (
            <details key={t.ref} className="pticket" style={{ borderLeftColor: priColor[t.priority] }}>
              <summary>
                <span className="qid mono">{t.ref}</span>
                <span className="psub">{t.subject}</span>
                <span className="pstat">{t.status}</span>
              </summary>
              <div className="pthread">
                <Thread t={t} me={me} onChanged={load} />
              </div>
            </details>
          ))}
        </div>
      </div>
    </div>
  );
}

function Thread({ t, me, onChanged }) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const events = [
    { id: "root", at: t.created_at, actor: t.requester, kind: "comment", body: t.body },
    ...t.events,
  ];

  const send = async () => {
    setBusy(true);
    try { await api.portalReply(t.ref, draft.trim()); setDraft(""); await onChanged(); }
    finally { setBusy(false); }
  };

  const remove = async (id) => {
    if (!window.confirm("Remove this message? Support will still see that you removed it.")) return;
    setBusy(true);
    try { await api.portalDeleteEvent(t.ref, id); await onChanged(); }
    finally { setBusy(false); }
  };

  return (
    <>
      <div style={{ paddingTop: 16 }}>
        {events.map((e) => (
          <div key={e.id} className="msg" data-gone={!!e.deleted_at}>
            <div className="av" data-agent={e.actor !== t.requester}>{initials(e.actor)}</div>
            <div className="mbody">
              <div className="mhead">
                <span className="mname">{e.actor}</span>
                <span className="mtime mono">{stamp(e.at)}</span>
                {e.id !== "root" && !e.deleted_at && e.actor === me.display_name && (
                  <button className="msgact" disabled={busy} onClick={() => remove(e.id)}>Remove</button>
                )}
              </div>
              {e.deleted_at ? (
                <div className="mtext tomb">
                  Message removed by {e.deleted_by} on {stamp(e.deleted_at)}
                </div>
              ) : (
                <div className="mtext">{e.body}</div>
              )}
            </div>
          </div>
        ))}
      </div>
      {OPEN_STATUSES.includes(t.status) && (
        <div className="replybox">
          <textarea value={draft} disabled={busy} placeholder="Add something we should know"
                    onChange={(e) => setDraft(e.target.value)} />
          <div className="replyfoot">
            <div className="spacer" />
            <button className="btn teal" disabled={busy || !draft.trim()} onClick={send}>Send reply</button>
          </div>
        </div>
      )}
    </>
  );
}
