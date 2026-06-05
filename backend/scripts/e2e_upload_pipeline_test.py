#!/usr/bin/env python3
"""E2E: upload one PDF to a case and poll until pipeline completes."""
from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))


def _login(base: str, email: str, password: str) -> str:
    import requests

    r = requests.post(
        f"{base}/api/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _create_case(base: str, token: str, title: str) -> str:
    import requests

    r = requests.post(
        f"{base}/api/cases",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": title, "case_type": "bankruptcy"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("id") or data.get("case_id") or data["case"]["id"]


def _upload_file(base: str, token: str, case_id: str, pdf_path: str) -> dict:
    import requests

    with open(pdf_path, "rb") as fh:
        r = requests.post(
            f"{base}/api/cases/{case_id}/files",
            headers={"Authorization": f"Bearer {token}"},
            files={"files": (os.path.basename(pdf_path), fh, "application/pdf")},
            timeout=120,
        )
    r.raise_for_status()
    return r.json()


def _poll_status(base: str, token: str, case_id: str, timeout_sec: float) -> dict:
    import requests

    t0 = time.perf_counter()
    last = None
    while time.perf_counter() - t0 < timeout_sec:
        r = requests.get(
            f"{base}/api/cases/{case_id}/processing-status",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        last = data
        if data.get("all_done"):
            data["elapsed_sec"] = round(time.perf_counter() - t0, 2)
            return data
        time.sleep(2)
    raise TimeoutError(f"Pipeline not done after {timeout_sec}s; last={last}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_path")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default=os.getenv("E2E_TEST_EMAIL", ""))
    parser.add_argument("--password", default=os.getenv("E2E_TEST_PASSWORD", ""))
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()

    if not os.path.isfile(args.pdf_path):
        print(f"ERROR: file not found: {args.pdf_path}")
        return 1
    if not args.email or not args.password:
        print("ERROR: set E2E_TEST_EMAIL and E2E_TEST_PASSWORD in env or pass --email/--password")
        return 1

    t_total = time.perf_counter()
    print("=== E2E upload pipeline test ===")
    print(f"file: {args.pdf_path} ({os.path.getsize(args.pdf_path)} bytes)")
    print(f"api: {args.base}")

    token = _login(args.base, args.email, args.password)
    print("login: ok")

    title = f"e2e-upload-{uuid.uuid4().hex[:8]}"
    case_id = _create_case(args.base, token, title)
    print(f"case: {case_id}")

    t_up = time.perf_counter()
    up = _upload_file(args.base, token, case_id, args.pdf_path)
    upload_sec = round(time.perf_counter() - t_up, 2)
    print(f"upload HTTP: {upload_sec}s -> {up.get('status')} files={up.get('added')}")
    file_ids = up.get("new_file_ids") or [f["id"] for f in up.get("files", [])]
    print(f"file_ids: {file_ids}")

    status = _poll_status(args.base, token, case_id, args.timeout)
    total_sec = round(time.perf_counter() - t_total, 2)
    print(f"pipeline: {status.get('elapsed_sec')}s (poll after upload)")
    print(f"total: {total_sec}s")
    for f in status.get("files", []):
        print(f"  - {f.get('filename')}: {f.get('status')}")
        if f.get("error"):
            print(f"    error: {f.get('error')[:500]}")

    if status.get("has_errors"):
        print("RESULT: FAILED")
        return 2
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
