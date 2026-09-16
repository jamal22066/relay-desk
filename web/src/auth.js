const json = { "content-type": "application/json" };

async function call(url, opts = {}) {
  const r = await fetch(url, { credentials: "same-origin", ...opts });
  if (r.status === 204) return null;
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = body.detail;
    throw new Error(typeof d === "string" ? d : "Something went wrong");
  }
  return body;
}

export const auth = {
  me: () => call("/api/auth/me"),
  login: (email, password) =>
    call("/api/auth/login", { method: "POST", headers: json, body: JSON.stringify({ email, password }) }),
  register: (payload) =>
    call("/api/auth/register", { method: "POST", headers: json, body: JSON.stringify(payload) }),
  logout: () => call("/api/auth/logout", { method: "POST" }),
  oidcStatus: () => call("/api/auth/oidc/status"),
  oidcCallback: (code, state) =>
    call("/api/auth/oidc/callback", {
      method: "POST", headers: json, body: JSON.stringify({ code, state }),
    }),
  verify: (token) =>
    call("/api/auth/verify", { method: "POST", headers: json, body: JSON.stringify({ token }) }),
  verify: (token) =>
    call("/api/auth/verify", { method: "POST", headers: json, body: JSON.stringify({ token }) }),
};
