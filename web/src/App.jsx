import { useEffect, useState } from "react";
import { api } from "./api";
import { auth } from "./auth";
import AgentConsole from "./AgentConsole";
import Login from "./Login";
import Portal from "./Portal";
import Settings from "./Settings";
import Logo from "./Logo";

export default function App() {
  const [me, setMe] = useState(null);
  const [meta, setMeta] = useState(null);
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState(null);
  const [showSettings, setShowSettings] = useState(false);

  useEffect(() => {
    auth.me().then(setMe).catch(() => setMe(null)).finally(() => setReady(true));
  }, []);

  useEffect(() => {
    if (!me || me.role === "customer") { setMeta(null); return; }
    api.meta().then(setMeta).catch((e) => setErr(e.message));
  }, [me]);

  const signOut = async () => {
    await auth.logout().catch(() => {});
    setMe(null);
    setMeta(null);
  };

  if (!ready) return <div className="desk"><div className="loading">…</div></div>;

  return (
    <div className="desk">
      <div className="topbar">
        <button className="brand" onClick={() => setShowSettings(false)}
                title="Back to the queue"><Logo size={22} />
                <span className="wordmark">Relay <span>Desk</span> by Jamal Nasir</span></button>
        <div className="spacer" />
        {me && (
          <>
            {me.role === "admin" && !showSettings && (
              <button className="btn ghost" onClick={() => setShowSettings(true)}>Settings</button>
            )}
            <span className="dsub">
              {me.display_name} · {me.role === "customer" ? me.org : "Support"}
            </span>
            <button className="btn ghost" onClick={signOut}>Sign out</button>
          </>
        )}
      </div>

      {err && <div className="errbar">{err}</div>}

      {!me ? (
        <Login onSignedIn={setMe} />
      ) : showSettings ? (
        <Settings onClose={() => setShowSettings(false)} />
      ) : me.role !== "customer" ? (
        meta ? <AgentConsole meta={meta} /> : <div className="loading">Opening the queue…</div>
      ) : (
        <Portal me={me} />
      )}
    </div>
  );
}
