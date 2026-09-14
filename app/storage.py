"""Attachment storage on the local filesystem.

Three rules, each closing a specific hole:

1. Stored filenames are generated, never derived from client input. That makes
   path traversal structurally impossible rather than something to sanitise.
2. The content type comes from sniffing the bytes, not from the upload's
   Content-Type header or the extension, either of which the client controls.
3. Downloads are served as attachments with nosniff, so an uploaded HTML or SVG
   file cannot execute in the browser against a signed-in session.
"""
import secrets
from pathlib import Path

import magic

from app.config import settings

# what the sniffed type must be. An allowlist, so anything unrecognised is
# refused rather than something unsafe having to be anticipated.
ALLOWED = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/csv": ".csv",
}

# text/plain covers .log and .csv on most systems, so accept those extensions
# for it rather than rewriting them to .txt
TEXT_EXTENSIONS = {".txt", ".log", ".csv", ".json", ".yaml", ".yml", ".md"}


class UploadRejected(Exception):
    pass


def root() -> Path:
    p = Path(settings.upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sniff(data: bytes) -> str:
    return magic.from_buffer(data[:2048], mime=True)


def check(data: bytes, original_name: str) -> tuple[str, str]:
    """Return (content_type, extension) or raise UploadRejected."""
    if not data:
        raise UploadRejected("That file is empty.")
    if len(data) > settings.upload_max_bytes:
        mb = settings.upload_max_bytes // (1024 * 1024)
        raise UploadRejected(f"Files must be {mb} MB or smaller.")

    detected = sniff(data)
    if detected not in ALLOWED:
        raise UploadRejected(
            f"{original_name} looks like {detected}, which is not an accepted type. "
            "Images, PDFs and plain text files are allowed."
        )

    ext = ALLOWED[detected]
    if detected == "text/plain":
        # libmagic falls back to text/plain for content it cannot identify, so
        # binary masquerading as text would slip through. Real text files do
        # not contain null bytes.
        if b"\x00" in data[:8192]:
            raise UploadRejected(
                f"{original_name} contains binary data but is not a recognised "
                "image or document type."
            )
        given = Path(original_name).suffix.lower()
        if given in TEXT_EXTENSIONS:
            ext = given

    return detected, ext


def save(data: bytes, ext: str) -> str:
    """Write the bytes under a generated name and return that name."""
    stored = secrets.token_hex(16) + ext
    path = root() / stored

    # belt and braces: the generated name cannot escape, but assert it anyway
    if path.parent.resolve() != root().resolve():
        raise UploadRejected("Refusing to write outside the upload directory.")

    path.write_bytes(data)
    return stored


def path_for(stored_name: str) -> Path:
    """Resolve a stored name to a path, refusing anything that escapes root."""
    base = root().resolve()
    candidate = (base / stored_name).resolve()
    if not str(candidate).startswith(str(base) + "/"):
        raise UploadRejected("Invalid attachment reference.")
    if not candidate.is_file():
        raise UploadRejected("That file is no longer available.")
    return candidate


def delete(stored_name: str) -> None:
    try:
        path_for(stored_name).unlink()
    except (UploadRejected, OSError):
        pass  # already gone, or never written
