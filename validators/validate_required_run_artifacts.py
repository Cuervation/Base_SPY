from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


RC_COMPLETE = 0
RC_INCOMPLETE_NO_PARENT = 3
RC_RECOVERABLE_PARTIAL_RUN = 4
RC_FAIL_UNRECOVERABLE = 5


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _as_int_list(values: Any) -> List[int]:
    out: List[int] = []
    if not isinstance(values, list):
        return out
    for x in values:
        try:
            out.append(int(x))
        except Exception:
            continue
    return out


def classify(run_dir: Path) -> Tuple[int, str]:
    plan_path = run_dir / "window_execution_plan.json"
    live_log = run_dir / "run_live_status.log"
    run_status_path = run_dir / "run_status.json"
    executor_path = run_dir / "executor_output.json"
    coord_path = run_dir / "coordinator_output.json"
    manifest_path = run_dir / "experiment_manifest.json"
    partial_path = run_dir / "executor_output.partial.json"

    if not plan_path.exists() or not live_log.exists():
        return RC_FAIL_UNRECOVERABLE, "FAIL_UNRECOVERABLE: missing plan/log"

    plan = read_json(plan_path, {})
    allowed = _as_int_list(plan.get("allowed_windows") if isinstance(plan, dict) else [])
    run_status = read_json(run_status_path, {})
    manifest = read_json(manifest_path, {})
    if (
        (isinstance(run_status, dict) and read_json(run_status_path, {}).get("status") == "blocked_preflight")
        or (isinstance(manifest, dict) and manifest.get("status") == "blocked_preflight")
    ):
        return RC_COMPLETE, "BLOCKED_PREFLIGHT_COMPLETE"

    missing = []
    for p in [executor_path, coord_path, manifest_path]:
        if not p.exists():
            missing.append(p.name)

    if not missing:
        return RC_COMPLETE, "COMPLETE"

    if partial_path.exists() and not executor_path.exists():
        partial = read_json(partial_path, {})
        executed = _as_int_list((partial.get("executed_windows") if isinstance(partial, dict) else []))
        partial_windows = (partial.get("windows") if isinstance(partial, dict) else {})
        has_partial_signal = bool(executed) or (isinstance(partial_windows, dict) and bool(partial_windows))
        if has_partial_signal:
            return RC_RECOVERABLE_PARTIAL_RUN, "RECOVERABLE_PARTIAL_RUN: missing final outputs but partial checkpoint exists"
        return RC_INCOMPLETE_NO_PARENT, "INCOMPLETE_NO_PARENT: partial checkpoint exists but has no usable window data"

    if 52 in allowed and not (run_dir / "window_52").exists():
        return RC_INCOMPLETE_NO_PARENT, "INCOMPLETE_NO_PARENT: allowed includes 52 but window_52 directory is missing"

    return RC_INCOMPLETE_NO_PARENT, f"INCOMPLETE_NO_PARENT: missing required outputs {missing}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate required run artifacts exist.")
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists() or not run_dir.is_dir():
        print(f"ERROR: run dir not found: {run_dir}", file=sys.stderr)
        return 2

    rc, msg = classify(run_dir)
    if rc in {RC_COMPLETE, RC_RECOVERABLE_PARTIAL_RUN}:
        print(msg)
    else:
        print(f"ERROR: {msg}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
