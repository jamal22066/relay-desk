/**
 * Minimal routing. The server serves index.html for any unmatched path, so the
 * SPA can own the URL without a router library.
 */

export function parse(pathname = window.location.pathname) {
  const ticket = pathname.match(/^\/t\/([A-Za-z0-9_-]+)\/?$/);
  if (ticket) return { view: "ticket", ref: ticket[1].toUpperCase() };

  if (pathname === "/auth/callback") return { view: "oidc-callback" };

  const settings = pathname.match(/^\/settings(?:\/([a-z]+))?\/?$/);
  if (settings) return { view: "settings", section: settings[1] || "overview" };

  return { view: "home" };
}

export function push(path) {
  if (window.location.pathname !== path) {
    window.history.pushState({}, "", path);
  }
}

export function replace(path) {
  window.history.replaceState({}, "", path);
}

/** Calls back whenever the user navigates with the browser's back/forward buttons. */
export function onPopState(fn) {
  const handler = () => fn(parse());
  window.addEventListener("popstate", handler);
  return () => window.removeEventListener("popstate", handler);
}
