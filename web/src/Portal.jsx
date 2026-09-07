import { useEffect, useState } from "react";
import { api } from "./api";
import { IMPACT, OPEN_STATUSES, initials, priColor, stamp } from "./util";

const blank = (meta) => ({
  requester: "", email: "", org: "", track: "saas",
  category: meta.categories.saas[0], priority: "P3", subject: "", body: "",
});

export default function Portal({ meta }) {
  const [f, setF] = useState(() => blank(meta));
  const [filed, setFiled] = useState(null);
  const [lookup, setLookup] = useState("");
  const [mine, setMine] = useState([]);
  const [err, setErr] = useState(null);

  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  const valid = f.requester.trim() && f.email.trim() && f.subject.trim().length > 2 && f.body.trim().length > 2;
  const hours = meta.priorities.find((p) => p.id === f.priority).hours;

  const load = (email) => {
    if (!email.trim()) { setMine([]); return; }
    api.portalList(email).then(setMine).catch((e) => setErr(e.message));
  };

  useEffect(() => {
    const id = setTimeout(() => load(lookup), 300);
    return () => clearTimeout(id);
  }, [lookup]);

  const submit = async () => {
    try {
      const t = await api.create({ ...f, org: f.org.trim() || "Unspecified" });
      setFiled({ ref: t.ref, email: t.email });
      setLookup(t.email);
      setF(blank(meta));
      setErr(null);
    } catch (e) { setErr(e.message); }
  };

  return (
    <div className="portal">
      <div className="pinner">
        {filed && (
          <div className="banner">
            Ticket <strong className="mono">{filed.ref}</strong> is filed. A reply goes to {filed.email} once
            someone picks it up.
          </div>
        )}
        {err && <div className="errbar" style={{ marginBottom: 20 }}>{err}</div>}

        <h1 className="plead">Tell us what broke</h1>
        <p className="pdek">
          One form for the product and for your laptop. The more specific you are about what you did
          and what happened instead, the faster this gets resolved.
        </p>

        <div className="form">
          <div className="row2">
            <div className="fgroup">
              <label htmlFor="p-name">Your name</label>
              <input id="p-name" className="field" value={f.requester}
                     onChange={(e) => set("requester", e.target.value)} />
            </div>
            <div className="fgroup">
              <label htmlFor="p-email">Email for updates</label>
              <input id="p-email" className="field" type="email" value={f.email}
                     onChange={(e) => set("email", e.target.value)} />
            </div>
          </div>
          <div className="fgroup">
            <label htmlFor="p-org">Company</label>
            <input id="p-org" className="field" value={f.org} onChange={(e) => set("org", e.target.value)} />
          </div>
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
            <button className="btn teal" disabled={!valid} onClick={submit}>File ticket</button>
            {!valid && <span className="hint">Name, email, summary and description are needed.</span>}
          </div>
        </div>

        <div className="mine">
          <div className="minehead">Check on a ticket</div>
          <input className="field" style={{ marginBottom: 14 }} value={lookup}
                 placeholder="Enter the email you filed with, e.g. dana@northgate.io"
                 onChange={(e) => setLookup(e.target.value)} />
          {lookup.trim() && mine.length === 0 && <p className="hint">No tickets under that address yet.</p>}
          {mine.map((t) => (
            <details key={t.ref} className="pticket" style={{ borderLeftColor: priColor[t.priority] }}>
              <summary>
                <span className="qid mono">{t.ref}</span>
                <span className="psub">{t.subject}</span>
                <span className="pstat">{t.status}</span>
              </summary>
              <div className="pthread">
                <Thread t={t} meta={meta} email={lookup} onReply={() => load(lookup)} />
              </div>
            </details>
          ))}
        </div>
      </div>
    </div>
  );
}

function Thread({ t, meta, email, onReply }) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const events = [
    { id: "root", at: t.created_at, actor: t.requester, kind: "comment", body: t.body },
    ...t.events,
  ];

  const send = async () => {
    setBusy(true);
    try { await api.portalReply(t.ref, email, draft.trim()); setDraft(""); onReply(); }
    finally { setBusy(false); }
  };

  const remove = async (id) => {
    if (!window.confirm("Remove this message? Support will still see that you removed it.")) return;
    setBusy(true);
    try { await api.portalDeleteEvent(t.ref, id, email); onReply(); }
    finally { setBusy(false); }
  };

  return (
    <>
      <div style={{ paddingTop: 16 }}>
        {events.map((e) => (
          <div key={e.id} className="msg" data-gone={!!e.deleted_at}>
            <div className="av" data-agent={meta.agents.includes(e.actor)}>{initials(e.actor)}</div>
            <div className="mbody">
              <div className="mhead">
                <span className="mname">{e.actor}</span>
                <span className="mtime mono">{stamp(e.at)}</span>
                {e.id !== "root" && !e.deleted_at && e.actor === t.requester && (
                  <button className="msgact" disabled={busy}
                          onClick={() => remove(e.id)}>Remove</button>
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
