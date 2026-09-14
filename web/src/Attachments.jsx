import { useRef, useState } from "react";
import { api } from "./api";

const ACCEPT = ".png,.jpg,.jpeg,.gif,.webp,.pdf,.txt,.log,.csv,.json,.yaml,.yml,.md";
const MAX_FILES = 5;

export function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Chips shown under a message in a thread. */
export function AttachmentList({ items, canRemove, onRemoved }) {
  const [busy, setBusy] = useState(null);
  if (!items || items.length === 0) return null;

  const remove = async (a) => {
    if (!window.confirm(`Remove ${a.original_name}?`)) return;
    setBusy(a.id);
    try { await api.deleteAttachment(a.id); await onRemoved?.(); }
    finally { setBusy(null); }
  };

  return (
    <div className="attachrow">
      {items.map((a) => (
        <span className="attach" key={a.id}>
          <a href={`/api/attachments/${a.id}`} download>{a.original_name}</a>
          <span className="hint">{humanSize(a.size_bytes)}</span>
          {canRemove && (
            <button className="attachx" disabled={busy === a.id}
                    title="Remove" onClick={() => remove(a)}>×</button>
          )}
        </span>
      ))}
    </div>
  );
}

/** File picker that stages files; the parent uploads them after posting the message. */
export function AttachmentPicker({ files, onChange, disabled }) {
  const input = useRef(null);

  const add = (e) => {
    const picked = Array.from(e.target.files || []);
    const next = [...files, ...picked].slice(0, MAX_FILES);
    onChange(next);
    e.target.value = "";   // so the same file can be picked again after removal
  };

  return (
    <>
      <button className="btn ghost" type="button" disabled={disabled}
              onClick={() => input.current?.click()}>
        Attach
      </button>
      <input ref={input} type="file" multiple accept={ACCEPT}
             style={{ display: "none" }} onChange={add} />
      {files.length > 0 && (
        <span className="attachrow staged">
          {files.map((f, i) => (
            <span className="attach" key={i}>
              {f.name}
              <span className="hint">{humanSize(f.size)}</span>
              <button className="attachx" type="button" disabled={disabled}
                      onClick={() => onChange(files.filter((_, n) => n !== i))}>×</button>
            </span>
          ))}
        </span>
      )}
    </>
  );
}
