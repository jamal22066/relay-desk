async function j(r) {
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const b = await r.json();
      if (b.detail) detail = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    } catch {}
    throw new Error(detail);
  }
  return r.status === 204 ? null : r.json();
}

const post = (url, body) =>
  fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }).then(j);

export const api = {
  meta: () => fetch("/api/meta", { credentials: "same-origin" }).then(j),
  counts: () => fetch("/api/counts", { credentials: "same-origin" }).then(j),
  list: (view, track, q) => {
    const p = new URLSearchParams({ view });
    if (track) p.set("track", track);
    if (q) p.set("q", q);
    return fetch(`/api/tickets?${p}`, { credentials: "same-origin" }).then(j);
  },
  lookupUsers: (q) =>
    fetch(`/api/users/lookup?q=${encodeURIComponent(q || "")}`,
          { credentials: "same-origin" }).then(j),
  get: (ref) => fetch(`/api/tickets/${ref}`, { credentials: "same-origin" }).then(j),
  create: (body) => post("/api/tickets", body),
  patch: (ref, body) =>
    fetch(`/api/tickets/${ref}`, {
      method: "PATCH",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then(j),
  addEvent: (ref, body, kind) => post(`/api/tickets/${ref}/events`, { body, kind }),
  deleteEvent: (ref, id) =>
    fetch(`/api/tickets/${ref}/events/${id}`, { method: "DELETE", credentials: "same-origin" }).then(j),
  portalDeleteEvent: (ref, id) =>
    fetch(`/api/portal/tickets/${ref}/events/${id}`, {
      method: "DELETE",
      credentials: "same-origin",
    }).then(j),
  portalMeta: () =>
    fetch("/api/portal/meta", { credentials: "same-origin" }).then(j),
  portalList: () =>
    fetch("/api/portal/tickets", { credentials: "same-origin" }).then(j),
  portalReply: (ref, body) =>
    post(`/api/portal/tickets/${ref}/events`, { body }),
};
