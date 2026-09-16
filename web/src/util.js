const HOUR = 3600e3;

export function relative(iso) {
  const d = Date.now() - new Date(iso).getTime();
  const m = Math.round(d / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

// A ticket can legitimately have no deadline (null due_at); say so rather than
// counting down from the epoch.
export const NO_DUE = "\u2014";

export function countdown(iso) {
  if (!iso) return NO_DUE;
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return NO_DUE;
  const left = at - Date.now();
  const abs = Math.abs(left);
  const sign = left < 0 ? "-" : "";
  const h = Math.floor(abs / HOUR);
  const m = Math.floor((abs % HOUR) / 60000);
  if (h >= 24) return `${sign}${Math.floor(h / 24)}d ${h % 24}h`;
  return `${sign}${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

export function stamp(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function initials(name) {
  if (!name) return "?";
  const p = name.replace(/[^A-Za-z. ]/g, "").split(/[. ]+/).filter(Boolean);
  return (p[0][0] + (p[1]?.[0] ?? "")).toUpperCase();
}

export const OPEN_STATUSES = ["New", "Open", "Waiting on customer"];
export const priColor = {
  P1: "var(--p1)", P2: "var(--p2)", P3: "var(--p3)", P4: "var(--p4)",
};
export const IMPACT = {
  P1: "Completely stopped, nobody can work",
  P2: "Blocking me, I have no workaround",
  P3: "Annoying, I can work around it",
  P4: "Whenever you get to it",
};
