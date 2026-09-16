#!/usr/bin/env python3
"""Strip secrets from a Keycloak realm export so it can be committed.

A raw `kc.sh export` is not safe to put in a repository. It carries the realm's
signing and encryption private keys, the confidential client's secret, and a
PBKDF2 hash for every user. This removes all three:

  * realm keys      -- deleted outright. Keycloak generates fresh ones on
                       import, so a key that signs ID tokens never needs to
                       leave the machine that made it.
  * client secrets  -- replaced with CHANGE_ME_KEYCLOAK_CLIENT_SECRET.
  * user passwords  -- replaced with a single plaintext credential holding
                       CHANGE_ME_KEYCLOAK_TEST_PASSWORD, which Keycloak hashes
                       on import.

The placeholders match the convention in ldap-dev/bootstrap.ldif: substitute
them with `sed` before importing, never commit a substituted file.

    python keycloak-dev/sanitise.py /tmp/kc-export/relay-desk-realm.json \
        keycloak-dev/relay-desk-realm.json

Exits non-zero if anything secret survives, so it can gate a commit.
"""
import json
import re
import sys

CLIENT_PLACEHOLDER = "CHANGE_ME_KEYCLOAK_CLIENT_SECRET"
USER_PLACEHOLDER = "CHANGE_ME_KEYCLOAK_TEST_PASSWORD"

# any run of base64-ish characters this long is a key, a hash or a token
BLOB = re.compile(r"[A-Za-z0-9+/_-]{60,}={0,2}")


def sanitise(realm: dict) -> list[str]:
    done = []

    removed = realm.get("components", {}).pop("org.keycloak.keys.KeyProvider", None)
    if removed:
        done.append(f"removed {len(removed)} KeyProvider components (realm RSA/AES/HMAC keys)")

    for client in realm.get("clients", []):
        if client.get("secret"):
            client["secret"] = CLIENT_PLACEHOLDER
            done.append(f"client {client['clientId']!r}: secret -> placeholder")

    for user in realm.get("users", []):
        if user.get("credentials"):
            n = len(user["credentials"])
            user["credentials"] = [
                {"type": "password", "value": USER_PLACEHOLDER, "temporary": False}
            ]
            done.append(f"user {user['username']!r}: {n} hashed credential(s) -> placeholder")

    return done


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    src, dst = argv[1], argv[2]
    with open(src) as f:
        realm = json.load(f)

    for line in sanitise(realm):
        print(" -", line)

    text = json.dumps(realm, indent=2) + "\n"

    # belt and braces: a future Keycloak may put secrets somewhere new, so
    # refuse to write a file that still contains anything key-shaped
    leftover = {b for b in BLOB.findall(text) if b not in (CLIENT_PLACEHOLDER, USER_PLACEHOLDER)}
    if leftover:
        print(f"\nREFUSING TO WRITE: {len(leftover)} opaque blob(s) still present:", file=sys.stderr)
        for b in sorted(leftover)[:5]:
            print(f"  {b[:60]}… ({len(b)} chars)", file=sys.stderr)
        print("Inspect the export and extend this script before committing.", file=sys.stderr)
        return 1

    with open(dst, "w") as f:
        f.write(text)
    print(f"\nwrote {dst} ({len(text)} bytes, no secret material)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
