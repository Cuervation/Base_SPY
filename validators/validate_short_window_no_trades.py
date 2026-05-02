from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate short_window_no_trades derived-window handling.")
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists() or not run_dir.is_dir():
        return _fail(f"run dir not found: {run_dir}")

    executor = _load_json(run_dir / "executor_output.json")
    partial = _load_json(run_dir / "executor_output.partial.json")
    run_status = _load_json(run_dir / "run_status.json")

    if not executor and not partial:
        return _fail("missing executor_output.json and executor_output.partial.json")

    windows = {}
    if isinstance(executor.get("windows"), dict):
        windows.update(executor["windows"])
    if isinstance(partial.get("windows"), dict):
        for k, v in partial["windows"].items():
            windows.setdefault(k, v if isinstance(v, dict) else {})

    found = False
    for wk, payload in windows.items():
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status", "")).strip()
        metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics"), dict) else {}
        trades = metrics.get("trades")
        reason = str(payload.get("reason", "")).strip()
        if status == "short_window_no_trades" or (trades in {0, 0.0} and int(wk) in {4, 8, 24}):
            found = True
            if status != "short_window_no_trades":
                return _fail(f"window {wk} with trades=0 must use status short_window_no_trades")
            if reason != "insufficient_short_window_activity":
                return _fail(f"window {wk} short_window_no_trades must set reason=insufficient_short_window_activity")
            depth_ok = payload.get("depth_ok", False)
            if depth_ok is True:
                return _fail(f"window {wk} short_window_no_trades must set depth_ok=false")

    if found:
        if str(run_status.get("status", "")).strip() == "run_error":
            return _fail("run_status.json must not be run_error for short_window_no_trades")
        print("OK: short_window_no_trades accepted as non-fatal evidence insufficiency")
        return 0

    print("OK: no short_window_no_trades windows found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
