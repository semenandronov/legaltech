"""Helpers for deterministic chunk IDs."""

from __future__ import annotations

import hashlib


def generate_chunk_id(doc_id: str, chunk_index: int, char_start: int) -> str:
    """
    Generate deterministic short chunk identifier.
    """
    hash_input = f"{doc_id}:{chunk_index}:{char_start}"
    hash_short = hashlib.md5(hash_input.encode()).hexdigest()[:6]
    doc_id_short = doc_id[:8] if len(doc_id) > 8 else doc_id
    return f"{doc_id_short}_{chunk_index}_{hash_short}"

