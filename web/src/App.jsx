import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { auth } from "./auth";
import AgentConsole from "./AgentConsole";
import Login from "./Login";
import Portal from "./Portal";
import Settings from "./Settings";
import { onPopState, parse, push, replace } from "./route";
import Logo from "./Logo";

export default function App() {
  const [me, setMe] = useState(null);
  const [meta, setMeta] = useState(null);
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState(null);
  const [route, setRoute] = useState(() => parse());
  const [canEndIdp, setCanEndIdp] = useState(false);
  // an authorisation code is single-use, and StrictMode runs effects twice in
  // development, so the second exchange would fail and overwrite the success
  const exchanged = useRef(false);
  const showSettings = route.view === "settings";
  const deepRef = route.view === "ticket" ? route.ref : null;


  useEffect(() => onPopState(setRoute), []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = window.location.pathname === "/verify" ? params.get("token") : null;

    if (route.view === "oidc-callback") {
      if (exchanged.current) { setReady(true); return; }
      exchanged.current = true;
      const code = params.get("code");
      const st = params.get("state");
      const failed = params.get("error_description") || params.get("error");

      if (failed) {
        setErr(failed);
        replace("/");
        setRoute({ view: "home" });
        setReady(true);
        return;
      }
      auth.oidcCallback(code, st)
        .then((m) => { setMe(m); replace("/"); setRoute({ view: "home" }); })
        .catch((e) => { setErr(e.message); replace("/"); setRoute({ view: "home" }); })
        .finally(() => setReady(true));
      return;
    }

    if (token) {
      auth.verify(token)
        .then((m) => { setMe(m); replace("/"); setRoute({ view: "home" }); })
        .catch((e) => setErr(e.message))
        .finally(() => setReady(true));
      return;
    }
    auth.me().then(setMe).catch(() => setMe(null)).finally(() => setReady(true));
  }, []);

  useEffect(() => {
    if (!me || me.role === "customer") { setMeta(null); return; }
    api.meta().then(setMeta).catch((e) => setErr(e.message));
  }, [me]);

  // Not every provider supports RP-initiated logout — Google publishes no
  // end_session_endpoint — so ask before offering to end a session we cannot end.
  useEffect(() => {
    if (me?.auth_source !== "oidc") { setCanEndIdp(false); return; }
    auth.oidcStatus().then((r) => setCanEndIdp(!!r.end_session)).catch(() => setCanEndIdp(false));
  }, [me]);

  // Signing out of Relay Desk leaves the identity provider's session alone —
  // the person may have other applications open against it. "Sign out
  // everywhere" is the explicit request to end that session too, which the
  // provider only accepts as a browser redirect.
  const signOut = async (everywhere = false) => {
    const r = await auth.logout(everywhere).catch(() => null);
    setMe(null);
    setMeta(null);
    if (everywhere && r?.idp_logout_url) window.location.href = r.idp_logout_url;
  };

  if (!ready) return <div className="desk"><div className="loading">…</div></div>;

  return (
    <div className="desk">
      <div className="topbar">
        <button className="brand"
                onClick={() => { push("/"); setRoute({ view: "home" }); }}
                title="Back to the queue"><Logo size={22} />
                <span className="wordmark">Relay <span>Desk</span> by Jamal Nasir</span></button>
        <div className="spacer" />
        {me && (
          <>
            {me.role === "admin" && !showSettings && (
              <button className="btn ghost"
                      onClick={() => { push("/settings"); setRoute({ view: "settings", section: "overview" }); }}>Settings</button>
            )}
            <span className="dsub">
              {me.display_name} · {me.role === "customer" ? me.org : "Support"}
            </span>
            <button className="btn ghost" onClick={() => signOut(false)}>Sign out</button>
            {me.auth_source === "oidc" && canEndIdp && (
              <button className="btn ghost" onClick={() => signOut(true)}
                      title="Also end your session with the identity provider">
                Sign out everywhere
              </button>
            )}
          </>
        )}
      </div>

      {err && <div className="errbar">{err}</div>}

      {!me ? (
        <Login onSignedIn={setMe} />
      ) : showSettings ? (
        <Settings meta={meta} section={route.section}
                  onSection={(k) => { push(`/settings/${k}`); setRoute({ view: "settings", section: k }); }}
                  onClose={() => { push("/"); setRoute({ view: "home" }); }} />
      ) : me.role !== "customer" ? (
        meta ? <AgentConsole meta={meta} initialRef={deepRef} /> : <div className="loading">Opening the queue…</div>
      ) : (
        <Portal me={me} initialRef={deepRef} />
      )}
    </div>
  );
}
