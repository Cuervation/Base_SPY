from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 2


def _require(d: Dict[str, Any], path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate state/research_state.json required fields.")
    ap.add_argument(
        "--path",
        default=str(Path("state") / "research_state.json"),
        help="Path to state research_state.json",
    )
    args = ap.parse_args()

    path = Path(args.path).resolve()
    if not path.exists():
        return _fail(f"missing state file: {path}")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return _fail(f"invalid JSON: {e}")
    if not isinstance(obj, dict):
        return _fail("research_state must be a JSON object")

    required = [
        "branch_state.current_mode",
        "branch_state.mode_reason",
        "branch_state.last_mode_change_at",
        "branch_state.last_mode_change_run_id",
        "branch_state.previous_mode",
        "branch_state.mode_stability_counter",
        "parent_state.current_parent_run_id",
        "parent_state.last_useful_run_id",
        "branch_anchor",
        "friction_state",
    ]
    missing = []
    for k in required:
        try:
            _require(obj, k)
        except KeyError:
            missing.append(k)
    if missing:
        for k in missing:
            print(f"ERROR: missing required field: {k}", file=sys.stderr)
        return 3

    # Minimal type checks
    if not isinstance(_require(obj, "branch_state.mode_stability_counter"), int):
        print("ERROR: branch_state.mode_stability_counter must be int", file=sys.stderr)
        return 4
    if not isinstance(_require(obj, "branch_anchor"), dict):
        print("ERROR: branch_anchor must be object", file=sys.stderr)
        return 4
    if not isinstance(_require(obj, "friction_state"), dict):
        print("ERROR: friction_state must be object", file=sys.stderr)
        return 4

    print("OK: state/research_state.json has required structure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

