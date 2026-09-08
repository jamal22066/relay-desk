import { useState } from "react";
import { auth } from "./auth";
import Logo from "./Logo";

export default function Login({ onSignedIn }) {
  const [mode, setMode] = useState("login");
  const [f, setF] = useState({ email: "", password: "", display_name: "", org: "" });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  const valid =
    mode === "login"
      ? f.email.trim() && f.password
      : f.email.trim() && f.password.length >= 10 && f.display_name.trim();

  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const me =
        mode === "login"
          ? await auth.login(f.email.trim(), f.password)
          : await auth.register({
              email: f.email.trim(),
              password: f.password,
              display_name: f.display_name.trim(),
              org: f.org.trim() || "Unspecified",
            });
      onSignedIn(me);
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  };

  return (
    <div className="portal">
      <div className="pinner" style={{ maxWidth: 420 }}>
        <div className="loginmark"><Logo size={44} /></div>
        {mode === "register" && (
          <button className="backlink" onClick={() => { setMode("login"); setErr(null); }}>
            ← Back to sign in
          </button>
        )}
        <h1 className="plead">{mode === "login" ? "Sign in" : "Create an account"}</h1>
        <p className="pdek">
          {mode === "login"
            ? "Support staff and customers use the same sign-in."
            : "Customer accounts only. Staff access is granted separately."}
        </p>

        <div className="form">
          {err && <div className="errbar" style={{ marginBottom: 14 }}>{err}</div>}

          {mode === "register" && (
            <>
              <div className="fgroup">
                <label htmlFor="l-name">Your name</label>
                <input id="l-name" className="field" value={f.display_name}
                       onChange={(e) => set("display_name", e.target.value)} />
              </div>
              <div className="fgroup">
                <label htmlFor="l-org">Company</label>
                <input id="l-org" className="field" value={f.org}
                       onChange={(e) => set("org", e.target.value)} />
              </div>
            </>
          )}

          <div className="fgroup">
            <label htmlFor="l-email">Email</label>
            <input id="l-email" className="field" type="email" autoComplete="username"
                   value={f.email} onChange={(e) => set("email", e.target.value)}
                   onKeyDown={(e) => e.key === "Enter" && submit()} />
          </div>

          <div className="fgroup">
            <label htmlFor="l-pw">Password</label>
            <input id="l-pw" className="field" type="password"
                   autoComplete={mode === "login" ? "current-password" : "new-password"}
                   value={f.password} onChange={(e) => set("password", e.target.value)}
                   onKeyDown={(e) => e.key === "Enter" && submit()} />
            {mode === "register" && (
              <div className="hint">At least 10 characters.</div>
            )}
          </div>

          <div className="formfoot">
            <button className="btn teal" disabled={!valid || busy} onClick={submit}>
              {busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
            </button>
            <button className="btn ghost" disabled={busy}
                    onClick={() => { setMode(mode === "login" ? "register" : "login"); setErr(null); }}>
              {mode === "login" ? "Create an account" : "Cancel"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
