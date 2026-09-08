"""Per-IP rate limiting for authentication.

In-memory and per-process: adequate for a single instance, not for a fleet.
A distributed deployment needs Redis or equivalent.

Behind Cloudflare, the client IP arrives in CF-Connecting-IP. That header is
only trustworthy because the tunnel means nothing reaches this app except via
Cloudflare — if the app is ever exposed directly, a client can forge it.
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_by_ip: dict[str, deque[float]] = defaultdict(deque)
_by_key: dict[str, deque[float]] = defaultdict(deque)

# An IP may be a shared NAT, so its budget is loose: it exists to stop one
# source enumerating many accounts.
IP_WINDOW = 300
IP_MAX = 30

# A single account is the thing actually under attack, so its budget is tight.
KEY_WINDOW = 900
KEY_MAX = 5


def client_ip(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    return request.client.host if request.client else "unknown"


def _hit(store: dict[str, deque[float]], key: str, window: int, limit: int) -> None:
    now = time.time()
    hits = store[key]
    while hits and now - hits[0] > window:
        hits.popleft()

    if len(hits) >= limit:
        retry = int(window - (now - hits[0]))
        raise HTTPException(
            429,
            "Too many sign-in attempts. Try again shortly.",
            headers={"Retry-After": str(max(retry, 1))},
        )

    hits.append(now)

    if len(store) > 10_000:
        for k in [k for k, v in store.items() if not v or now - v[-1] > window]:
            del store[k]


def check(request: Request, key: str | None = None) -> None:
    """Raises 429 if either the source IP or the target account is over budget."""
    _hit(_by_ip, client_ip(request), IP_WINDOW, IP_MAX)
    if key:
        _hit(_by_key, key.lower().strip(), KEY_WINDOW, KEY_MAX)


def clear(request: Request, key: str | None = None) -> None:
    """Called on successful login so a legitimate user is not penalised."""
    _by_ip.pop(client_ip(request), None)
    if key:
        _by_key.pop(key.lower().strip(), None)
