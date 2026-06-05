"""Run offline Langfuse-compatible evals from a JSON dataset."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.services.evals.langfuse_eval_runner import run_offline_eval


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline evals and output JSON report")
    parser.add_argument("--dataset", required=True, help="Path to eval dataset JSON array")
    parser.add_argument("--baseline-min", type=float, default=0.65, help="Minimal average score gate")
    parser.add_argument("--output", default="backend/eval-report.json", help="Output report path")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    report = await run_offline_eval(args.dataset, baseline_min=args.baseline_min)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(out), "pass_rate": report["pass_rate"]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
