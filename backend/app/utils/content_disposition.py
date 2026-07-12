"""HTTP Content-Disposition helpers for file downloads."""

from __future__ import annotations

import re
from urllib.parse import quote


_UNSAFE_FILENAME = re.compile(r'[\x00-\x1f<>:"/\\|?*]+')


def sanitize_attachment_filename(name: str, *, default: str = "export") -> str:
    """Return a filesystem-safe basename (no path segments)."""
    raw = (name or "").strip() or default
    raw = raw.replace("\\", "/").split("/")[-1]
    raw = _UNSAFE_FILENAME.sub("_", raw).strip(" .")
    return raw[:180] or default


def content_disposition_attachment(filename: str) -> str:
    """
    RFC 5987 Content-Disposition for ASCII + UTF-8 filenames.

    Browsers that ignore filename* still get a safe ASCII fallback.
    """
    safe = sanitize_attachment_filename(filename)
    # ASCII fallback: keep extension, strip non-ascii
    stem_ext = safe.rsplit(".", 1)
    if len(stem_ext) == 2 and stem_ext[1]:
        stem, ext = stem_ext[0], stem_ext[1]
        ascii_stem = stem.encode("ascii", "ignore").decode("ascii").strip() or "export"
        ascii_name = f"{ascii_stem}.{ext}"
    else:
        ascii_name = safe.encode("ascii", "ignore").decode("ascii").strip() or "export"
    ascii_name = ascii_name.replace('"', "")
    utf8_name = quote(safe, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"
