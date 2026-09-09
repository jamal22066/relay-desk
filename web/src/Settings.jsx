import { useEffect, useState } from "react";
import AdminDashboard from "./AdminDashboard";
import AdminOutbox from "./AdminOutbox";
import AdminUsers from "./AdminUsers";

const j = { "content-type": "application/json" };
const call = async (url, opts = {}) => {
  const r = await fetch(url, { credentials: "same-origin", ...opts });
  const b = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof b.detail === "string" ? b.detail : "Request failed");
  return b;
};

const ADMIN_VIEWS = [["overview", "Overview"], ["users", "Accounts"], ["outbox", "Mail queue"]];
const ADMIN_META = {
  overview: { title: "Overview", blurb: "Queue health, email delivery and recent activity." },
  users: { title: "Accounts", blurb: "Everyone who can sign in. Roles set here override the directory." },
  outbox: { title: "Mail queue", blurb: "Every notification the system has queued, sent or suppressed." },
};

export default function Settings({ onClose }) {
  const [data, setData] = useState(null);
  const [active, setActive] = useState("overview");
  const [edits, setEdits] = useState({});
  const [err, setErr] = useState(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = () =>
    call("/api/admin/settings").then(setData).catch((e) => setErr(e.message));

  useEffect(() => { load(); }, []);

  if (!data) return <div className="loading">{err || "Loading settings…"}</div>;

  const adminView = ADMIN_META[active];
  const section = adminView || data.sections.find((s) => s.key === active);
  const dirty = Object.keys(edits).length > 0;

  const valueOf = (f) => (f.key in edits ? edits[f.key] : f.value);
  const set = (k, v) => { setEdits((e) => ({ ...e, [k]: v })); setSaved(false); };

  const save = async () => {
    setBusy(true);
    try {
      const fresh = await call("/api/admin/settings", {
        method: "PUT", headers: j, body: JSON.stringify({ values: edits }),
      });
      setData(fresh);
      setEdits({});
      setSaved(true);
      setErr(null);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };

  const reset = async (key) => {
    await call(`/api/admin/settings/reset/${key}`, { method: "POST" });
    setEdits((e) => { const n = { ...e }; delete n[key]; return n; });
    load();
  };

  return (
    <div className="frame settings">
      <nav className="rail">
        <div className="railgroup">
          <div className="railtitle">Admin</div>
          {ADMIN_VIEWS.map(([k, label]) => (
            <button key={k} className="railitem" data-on={active === k}
                    onClick={() => setActive(k)}>
              <span className="label">{label}</span>
            </button>
          ))}
        </div>
        <div className="railgroup">
          <div className="railtitle">Settings</div>
          {data.sections.map((s) => (
            <button key={s.key} className="railitem" data-on={active === s.key}
                    onClick={() => setActive(s.key)}>
              <span className="label">{s.title}</span>
            </button>
          ))}
        </div>
        <div className="railgroup">
          <button className="railitem" onClick={onClose}>
            <span className="label">Back to the queue</span>
          </button>
        </div>
      </nav>

      <div className="setpane">
        <div className="sethead">
          <h1 className="dtitle" style={{ margin: 0 }}>{section.title}</h1>
          <p className="dsub" style={{ marginTop: 4 }}>{section.blurb}</p>
        </div>

        {err && <div className="errbar">{err}</div>}
        {saved && !dirty && <div className="banner">Saved.</div>}

        {adminView && (active === "overview" ? <AdminDashboard />
          : active === "users" ? <AdminUsers /> : <AdminOutbox />)}

        {!adminView && <div className="setbody">
          {section.fields.map((f) => (
            <Field key={f.key} f={f} value={valueOf(f)} onChange={set} onReset={reset} />
          ))}

          {active === "ldap" && <LdapTest />}
          {active === "smtp" && <SmtpTest />}
          {active === "sla" && <SlaRecompute dirty={dirty} />}
        </div>}

        {!adminView && <div className="setfoot">
          <button className="btn teal" disabled={!dirty || busy} onClick={save}>
            {busy ? "Saving…" : dirty ? `Save ${Object.keys(edits).length} change(s)` : "No changes"}
          </button>
          {dirty && (
            <button className="btn ghost" onClick={() => setEdits({})}>Discard</button>
          )}
        </div>}
      </div>
    </div>
  );
}

function Field({ f, value, onChange, onReset }) {
  const id = `set-${f.key}`;

  if (f.kind === "bool") {
    return (
      <div className="setrow">
        <label className="toggle" htmlFor={id}>
          <input id={id} type="checkbox" checked={!!value}
                 onChange={(e) => onChange(f.key, e.target.checked)} />
          {f.label}
        </label>
        {f.help && <div className="hint">{f.help}</div>}
      </div>
    );
  }

  const isJson = f.kind === "json";
  const shown = isJson ? JSON.stringify(value, null, 0) : value ?? "";

  return (
    <div className="setrow">
      <label htmlFor={id}>
        {f.label}
        {f.overridden && <span className="pill">set here</span>}
        {!f.overridden && <span className="pill muted">from .env</span>}
      </label>
      <div className="setinput">
        <input id={id} className="field"
               type={f.secret ? "password" : "text"}
               value={shown}
               placeholder={f.secret ? "Leave blank to keep the current value" : ""}
               onChange={(e) => {
                 if (!isJson) return onChange(f.key, f.kind === "int" ? Number(e.target.value) : e.target.value);
                 try { onChange(f.key, JSON.parse(e.target.value)); } catch { /* wait for valid JSON */ }
               }} />
        {f.overridden && (
          <button className="btn ghost" onClick={() => onReset(f.key)}>Reset</button>
        )}
      </div>
      {f.help && <div className="hint">{f.help}</div>}
    </div>
  );
}

function LdapTest() {
  const [f, setF] = useState({ email: "", password: "" });
  const [r, setR] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setR(await call("/api/admin/test/ldap", {
        method: "POST", headers: j, body: JSON.stringify(f),
      }));
    } catch (e) { setR({ ok: false, detail: e.message }); }
    finally { setBusy(false); }
  };

  return (
    <div className="testbox">
      <div className="minehead">Test a directory login</div>
      <p className="hint" style={{ marginTop: 0 }}>
        Uses the saved settings. Verify a real account works before relying on this.
      </p>
      <div className="row2">
        <input className="field" placeholder="Email" value={f.email}
               onChange={(e) => setF({ ...f, email: e.target.value })} />
        <input className="field" type="password" placeholder="Password" value={f.password}
               onChange={(e) => setF({ ...f, password: e.target.value })} />
      </div>
      <div className="formfoot">
        <button className="btn ghost" disabled={busy || !f.email} onClick={run}>
          {busy ? "Binding…" : "Test bind"}
        </button>
        {r && <span className={r.ok ? "ok" : "bad"}>{r.detail}{r.ok && ` · role: ${r.role}`}</span>}
      </div>
    </div>
  );
}

function SmtpTest() {
  const [to, setTo] = useState("");
  const [r, setR] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setR(await call("/api/admin/test/smtp", {
        method: "POST", headers: j, body: JSON.stringify({ to }),
      }));
    } catch (e) { setR({ ok: false, detail: e.message }); }
    finally { setBusy(false); }
  };

  return (
    <div className="testbox">
      <div className="minehead">Send a test message</div>
      <p className="hint" style={{ marginTop: 0 }}>
        Sends to any address, so you can verify the relay. The allowlist still governs
        real notifications — an address outside it is reported here, not silently allowed.
      </p>
      <input className="field" placeholder="Recipient" value={to}
             onChange={(e) => setTo(e.target.value)} />
      <div className="formfoot">
        <button className="btn ghost" disabled={busy || !to} onClick={run}>
          {busy ? "Sending…" : "Send test"}
        </button>
        {r && <span className={r.ok ? "ok" : "bad"}>{r.detail}</span>}
      </div>
    </div>
  );
}


function SlaRecompute({ dirty }) {
  const [r, setR] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try { setR(await call("/api/admin/sla/recompute", { method: "POST" })); }
    catch (e) { setR({ ok: false, detail: e.message }); }
    finally { setBusy(false); }
  };

  return (
    <div className="testbox">
      <div className="minehead">Apply to existing tickets</div>
      <p className="hint" style={{ marginTop: 0 }}>
        Changes above only affect new tickets. This recalculates the deadline on every
        open ticket from its original creation time — some may become past due.
      </p>
      <div className="formfoot">
        <button className="btn ghost" disabled={busy || dirty} onClick={run}>
          {busy ? "Recomputing…" : "Recompute open tickets"}
        </button>
        {dirty && <span className="hint">Save your changes first.</span>}
        {r && <span className={r.ok ? "ok" : "bad"}>{r.detail}</span>}
      </div>
    </div>
  );
}
