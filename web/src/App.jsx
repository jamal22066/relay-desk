import { useEffect, useState } from "react";
import { api } from "./api";
import AgentConsole from "./AgentConsole";
import Portal from "./Portal";

export default function App() {
  const [mode, setMode] = useState("agent");
  const [meta, setMeta] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.meta().then(setMeta).catch((e) => setErr(e.message));
  }, []);

  return (
    <div className="desk">
      <div className="topbar">
        <div className="brand">Relay <span>desk</span></div>
        <div className="spacer" />
        <div className="switch">
          <button data-on={mode === "portal"} onClick={() => setMode("portal")}>
            Customer portal
          </button>
          <button data-on={mode === "agent"} onClick={() => setMode("agent")}>
            Agent console
          </button>
        </div>
      </div>
      {err && <div className="errbar">{err}</div>}
      {!meta ? (
        <div className="loading">Opening the queue…</div>
      ) : mode === "agent" ? (
        <AgentConsole meta={meta} />
      ) : (
        <Portal meta={meta} />
      )}
    </div>
  );
}
