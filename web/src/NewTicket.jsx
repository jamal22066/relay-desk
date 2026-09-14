import { useEffect, useState } from "react";
import { api } from "./api";
import { IMPACT } from "./util";
import { AttachmentPicker } from "./Attachments";

export default function NewTicket({ meta, onCreated, onCancel }) {
  const [q, setQ] = useState("");
  const [people, setPeople] = useState([]);
  const [who, setWho] = useState(null);
  const [f, setF] = useState({
    track: "saas", category: meta.categories.saas[0],
    priority: "P3", subject: "", body: "",
  });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [files, setFiles] = useState([]);

  useEffect(() => {
    const id = setTimeout(
      () => api.lookupUsers(q).then(setPeople).catch((e) => setErr(e.message)),
      250
    );
    return () => clearTimeout(id);
  }, [q]);

  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  const valid = who && f.subject.trim().length > 2 && f.body.trim().length > 2;

  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true);
    try {
      if (files.length > 0) await api.validateAttachments(files);

      const t = await api.create({ ...f, requester_email: who.email });
      if (files.length > 0 && t.events.length > 0) {
        await api.uploadAttachments(t.ref, t.events[0].id, files);
      }
      onCreated(t.ref);
    } catch (e) { setErr(e.message); setBusy(false); }
  };

  return (
    <div className="detail">
      <div className="dhead">
        <div className="dsub">New ticket</div>
        <h1 className="dtitle">File on behalf of someone</h1>
        <div className="dsub">
          Only people with an account can be a requester. They see it in their portal.
        </div>
      </div>

      {err && <div className="errbar">{err}</div>}

      <div className="setbody">
        <div className="setrow">
          <label htmlFor="nt-who">Requester</label>
          {who ? (
            <div className="chosen">
              <span><strong>{who.display_name}</strong> · {who.email} · {who.org}</span>
              <button className="btn ghost" onClick={() => setWho(null)}>Change</button>
            </div>
          ) : (
            <>
              <input id="nt-who" className="field" value={q} autoFocus
                     placeholder="Search by name, email or company"
                     onChange={(e) => setQ(e.target.value)} />
              <div className="picker">
                {people.length === 0 && <div className="hint">No matching accounts.</div>}
                {people.map((p) => (
                  <button key={p.email} className="pickrow" onClick={() => setWho(p)}>
                    <span className="pickname">{p.display_name}</span>
                    <span className="hint">{p.email} · {p.org}</span>
                    {p.role !== "customer" && <span className="pill">{p.role}</span>}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="row2">
          <div className="setrow">
            <label htmlFor="nt-track">Service line</label>
            <select id="nt-track" className="field" value={f.track}
                    onChange={(e) => { set("track", e.target.value); set("category", meta.categories[e.target.value][0]); }}>
              <option value="saas">SaaS product</option>
              <option value="it">Workplace IT</option>
            </select>
          </div>
          <div className="setrow">
            <label htmlFor="nt-cat">Topic</label>
            <select id="nt-cat" className="field" value={f.category}
                    onChange={(e) => set("category", e.target.value)}>
              {meta.categories[f.track].map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
        </div>

        <div className="setrow">
          <label htmlFor="nt-pri">Priority</label>
          <select id="nt-pri" className="field" value={f.priority}
                  onChange={(e) => set("priority", e.target.value)}>
            {meta.priorities.map((p) => (
              <option key={p.id} value={p.id}>{p.id} — {IMPACT[p.id]}</option>
            ))}
          </select>
        </div>

        <div className="setrow">
          <label htmlFor="nt-sub">Summary</label>
          <input id="nt-sub" className="field" value={f.subject}
                 placeholder="Called in: cannot print to the third floor"
                 onChange={(e) => set("subject", e.target.value)} />
        </div>

        <div className="setrow">
          <label htmlFor="nt-body">What they reported</label>
          <textarea id="nt-body" className="field" rows={7} value={f.body}
                    onChange={(e) => set("body", e.target.value)} />
        </div>
      </div>

      <div className="setfoot">
        <button className="btn teal" disabled={!valid || busy} onClick={submit}>
          {busy ? "Creating…" : "Create ticket"}
        </button>
        <AttachmentPicker files={files} onChange={setFiles} disabled={busy} />
        <button className="btn ghost" onClick={onCancel}>Cancel</button>
        {!who && <span className="hint">Choose a requester first.</span>}
      </div>
    </div>
  );
}
