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
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }).then(j);

export const api = {
  meta: () => fetch("/api/meta").then(j),
  counts: () => fetch("/api/counts").then(j),
  list: (view, track, q) => {
    const p = new URLSearchParams({ view });
    if (track) p.set("track", track);
    if (q) p.set("q", q);
    return fetch(`/api/tickets?${p}`).then(j);
  },
  get: (ref) => fetch(`/api/tickets/${ref}`).then(j),
  create: (body) => post("/api/tickets", body),
  patch: (ref, body) =>
    fetch(`/api/tickets/${ref}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then(j),
  addEvent: (ref, body, kind) => post(`/api/tickets/${ref}/events`, { body, kind }),
  deleteEvent: (ref, id) =>
    fetch(`/api/tickets/${ref}/events/${id}`, { method: "DELETE" }).then(j),
  portalDeleteEvent: (ref, id, email) =>
    fetch(`/api/portal/tickets/${ref}/events/${id}?email=${encodeURIComponent(email)}`, {
      method: "DELETE",
    }).then(j),
  portalList: (email) =>
    fetch(`/api/portal/tickets?email=${encodeURIComponent(email)}`).then(j),
  portalReply: (ref, email, body) =>
    post(`/api/portal/tickets/${ref}/events?email=${encodeURIComponent(email)}`, { body }),
};
