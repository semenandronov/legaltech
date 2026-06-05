#!/usr/bin/env python3
"""
Normalize workflow tool names to canonical values in DB.

Usage:
  python scripts/migrate_workflow_tools_to_canonical.py --dry-run
  python scripts/migrate_workflow_tools_to_canonical.py --apply
"""

import argparse
import copy
import os
import sys
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.workflow import WorkflowDefinition, normalize_workflow_tool_name  # noqa: E402
from app.utils.database import SessionLocal  # noqa: E402


def normalize_tool_list(tool_names: List[str]) -> Tuple[List[str], bool]:
    seen = set()
    normalized = []
    changed = False
    for name in tool_names or []:
        canonical = normalize_workflow_tool_name(name)
        if canonical != name:
            changed = True
        if canonical and canonical not in seen:
            seen.add(canonical)
            normalized.append(canonical)
        elif canonical in seen:
            changed = True
    return normalized, changed


def normalize_plan(plan: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    if not isinstance(plan, dict):
        return plan, False
    changed = False
    out = copy.deepcopy(plan)
    steps = out.get("steps")
    if not isinstance(steps, list):
        return out, False

    for step in steps:
        if not isinstance(step, dict):
            continue
        tool_name = step.get("tool_name") or step.get("tool")
        if not tool_name:
            continue
        canonical = normalize_workflow_tool_name(tool_name)
        if canonical != tool_name:
            changed = True
            if "tool_name" in step:
                step["tool_name"] = canonical
            if "tool" in step:
                step["tool"] = canonical
    return out, changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Persist changes")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes only")
    args = parser.parse_args()

    if not args.apply and not args.dry_run:
        print("Specify one mode: --dry-run or --apply")
        return 1

    db = SessionLocal()
    try:
        definitions = db.query(WorkflowDefinition).all()
        updated_count = 0

        for definition in definitions:
            tools, tools_changed = normalize_tool_list(definition.available_tools or [])
            plan, plan_changed = normalize_plan(definition.default_plan)
            if not tools_changed and not plan_changed:
                continue

            updated_count += 1
            print(f"- {definition.id} ({definition.name})")
            if tools_changed:
                print(f"  available_tools -> {tools}")
            if plan_changed:
                print("  default_plan steps tools normalized")

            if args.apply:
                definition.available_tools = tools
                definition.default_plan = plan

        if args.apply:
            db.commit()
            print(f"\nApplied. Updated definitions: {updated_count}")
        else:
            print(f"\nDry run complete. Definitions to update: {updated_count}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
