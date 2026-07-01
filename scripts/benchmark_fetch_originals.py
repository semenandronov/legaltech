#!/usr/bin/env python3
"""Benchmark fetch_original_text for local vs Neon (read-only)."""
from __future__ import annotations

import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

CASE_ID = "bde0a4a1-7ebd-43e0-bebd-5308b852d910"
ROUNDS = 3


def read_db_url(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^DATABASE_URL\s*=\s*["\']?([^"\'#\n]+)', text, re.M)
    if not match:
        raise RuntimeError(f"DATABASE_URL not found in {path}")
    return match.group(1).strip()


def bench_label(url: str) -> str:
    return "local" if "localhost" in url else "neon"


def run_rounds(db_url: str) -> list[float]:
    import os

    os.environ["DATABASE_URL"] = db_url

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from app.services.chat.citation_payload import fetch_original_text_map_for_case

    engine = create_engine(db_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine)
    timings: list[float] = []

    with session_factory() as db:
        rows = db.execute(
            text("SELECT id FROM files WHERE case_id = :case_id"),
            {"case_id": CASE_ID},
        ).fetchall()
        file_ids = [str(row[0]) for row in rows]
        print(f"  files in case: {len(file_ids)}")

        for i in range(ROUNDS):
            started = time.perf_counter()
            originals = fetch_original_text_map_for_case(
                db,
                CASE_ID,
                file_ids=file_ids,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            total_chars = sum(len(v or "") for v in originals.values())
            print(
                f"  round {i + 1}: {elapsed_ms:.0f} ms, "
                f"originals={len(originals)}, chars={total_chars}"
            )
            timings.append(elapsed_ms)
            db.rollback()

    engine.dispose()
    return timings


def main() -> None:
    local_url = read_db_url(ROOT / ".env")
    neon_url = read_db_url(ROOT / ".env.neon-backup")

    print(f"Case: {CASE_ID}")
    print(f"Rounds per target: {ROUNDS}\n")

    results: dict[str, list[float]] = {}
    for url in (local_url, neon_url):
        label = bench_label(url)
        print(f"=== {label.upper()} ===")
        results[label] = run_rounds(url)
        print()

    print("=== SUMMARY (median ms) ===")
    for label, timings in results.items():
        med = statistics.median(timings)
        print(f"{label}: median={med:.0f} ms, min={min(timings):.0f}, max={max(timings):.0f}")


if __name__ == "__main__":
    main()
