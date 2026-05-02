from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Set


def parse_allowed(arg: str) -> List[int]:
    out: List[int] = []
    for part in (arg or "").split(","):
        s = part.strip()
        if not s:
            continue
        try:
            out.append(int(s))
        except Exception:
            raise ValueError(f"invalid window: {s!r}")
    return out


def _collect_window_hits(obj: Any, *, ignore_keys: Set[str] | None = None, path: str = "") -> List[str]:
    ignore = ignore_keys or set()
    hits: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) in ignore:
                continue
            hits.extend(_collect_window_hits(v, ignore_keys=ignore, path=f"{path}.{k}" if path else str(k)))
        return hits
    if isinstance(obj, list):
        for idx, item in enumerate(obj):
            hits.extend(_collect_window_hits(item, ignore_keys=ignore, path=f"{path}[{idx}]"))
        return hits
    try:
        iv = int(obj)
        if iv == 156:
            hits.append(path or "<root>")
    except Exception:
        pass
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate that a run dir respects allowed window constraints.")
    ap.add_argument("--run-dir", required=True, help="Path to run directory, e.g. runs/multi_agent_runs/EXP_XXX_...")
    ap.add_argument("--allowed-windows", required=True, help="Comma-separated allowed windows, e.g. 4,8")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists() or not run_dir.is_dir():
        print(f"ERROR: run dir not found: {run_dir}", file=sys.stderr)
        return 2

    allowed_list = parse_allowed(args.allowed_windows)
    allowed: Set[int] = {int(x) for x in allowed_list if int(x) > 0}
    if not allowed:
        print("ERROR: allowed-windows is empty", file=sys.stderr)
        return 2

    errors: List[str] = []
    error_set: Set[str] = set()

    # 1) Folder presence check
    for w in (24, 52, 156):
        if int(w) not in allowed:
            if (run_dir / f"window_{w:02d}").exists():
                error_set.add(f"forbidden window folder exists: window_{w:02d}")

    # 2) Plan check if available
    plan_path = run_dir / "window_execution_plan.json"
    if plan_path.exists():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
        except Exception as e:
                    error_set.add(f"invalid window_execution_plan.json: {e}")
                    plan = {}
        if isinstance(plan, dict):
            executed = plan.get("executed_windows") or []
            if isinstance(executed, list):
                for x in executed:
                    try:
                        ix = int(x)
                    except Exception:
                        error_set.add(f"executed_windows contains non-int: {x!r}")
                        continue
                    if ix not in allowed:
                        error_set.add(f"executed window not allowed: {ix}")
            for key in ("requested_windows", "allowed_windows", "planned_windows", "progressive_plan", "executed_windows"):
                vals = plan.get(key)
                if isinstance(vals, list):
                    for x in vals:
                        try:
                            ix = int(x)
                        except Exception:
                            continue
                        if ix == 156:
                            error_set.add(f"forbidden window appears in {key}: 156")
            hits = _collect_window_hits(plan, ignore_keys={"forbidden_windows"})
            for path in hits:
                error_set.add(f"forbidden window appears in plan at {path}: 156")

    errors = sorted(error_set)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 3

    print(f"OK: run respects allowed windows {sorted(allowed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
