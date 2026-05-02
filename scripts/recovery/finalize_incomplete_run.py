from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def parse_completed_from_log(log_path: Path) -> List[int]:
    if not log_path.exists():
        return []
    done: List[int] = []
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "EXECUTOR window_done" in line and "weeks=" in line:
            try:
                part = line.split("weeks=", 1)[1]
                w = int(part.split()[0].strip())
                if w not in done:
                    done.append(w)
            except Exception:
                continue
    return done


def parse_window_done_metrics(log_path: Path) -> Dict[str, Dict[str, Any]]:
    """
    Best-effort parse of EXECUTOR window_done lines from run_live_status.log.
    Produces a minimal windows dict compatible with recovery executor_output.json.
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not log_path.exists():
        return out
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "EXECUTOR window_done" not in line or "weeks=" not in line:
            continue
        try:
            # Example fragments:
            # weeks=52 status=run_ok ... actual_weeks_run=52 depth_ok=1 weeks_traded=23 trades=115 wins=36 losses=42 ties=37 spy_compare=1.49 window_sec=...
            parts = line.split("EXECUTOR window_done", 1)[1].strip().split()
            kv: Dict[str, str] = {}
            for p in parts:
                if "=" in p:
                    k, v = p.split("=", 1)
                    kv[k.strip()] = v.strip()
            w = int(kv.get("weeks", "0") or 0)
            if w <= 0:
                continue
            wk = str(w)
            out[wk] = {
                "status": kv.get("status", ""),
                "window": w,
                "requested_weeks": w,
                "actual_weeks_run": int(float(kv.get("actual_weeks_run", "0") or 0)) if kv.get("actual_weeks_run") else None,
                "depth_ok": bool(int(float(kv.get("depth_ok", "0") or 0))) if kv.get("depth_ok") else False,
                "test_start_used": kv.get("test_start_used", ""),
                "metrics": {
                    "weeks_traded": int(float(kv.get("weeks_traded", "0") or 0)) if kv.get("weeks_traded") else None,
                    "trades": int(float(kv.get("trades", "0") or 0)) if kv.get("trades") else None,
                    "wins": int(float(kv.get("wins", "0") or 0)) if kv.get("wins") else None,
                    "losses": int(float(kv.get("losses", "0") or 0)) if kv.get("losses") else None,
                    "ties": int(float(kv.get("ties", "0") or 0)) if kv.get("ties") else None,
                    "spy_compare": float(kv.get("spy_compare", "nan")) if kv.get("spy_compare") else None,
                },
                "errors": [],
                "execution_mode": "recovered_from_run_live_status",
            }
        except Exception:
            continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Finalize an incomplete run by reconstructing missing artifacts.")
    ap.add_argument("--run-dir", required=True, help="Run directory path (runs/multi_agent_runs/EXP_XXX_...)")
    ap.add_argument("--append-experiment-log", action="store_true", help="DO NOT use by default.")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists() or not run_dir.is_dir():
        print(f"ERROR: run dir not found: {run_dir}", file=sys.stderr)
        return 2

    plan = read_json(run_dir / "window_execution_plan.json", {})
    partial = read_json(run_dir / "executor_output.partial.json", {})
    live_log = run_dir / "run_live_status.log"
    completed_from_log = parse_completed_from_log(live_log)
    windows_from_log = parse_window_done_metrics(live_log)

    allowed = plan.get("allowed_windows") if isinstance(plan, dict) else None
    if not isinstance(allowed, list):
        allowed = []

    # Prefer per-window window_result.json
    windows: Dict[str, Any] = {}
    executed: List[int] = []
    for w in allowed:
        try:
            iw = int(w)
        except Exception:
            continue
        wr_path = run_dir / f"window_{iw:02d}" / "window_result.json"
        wr = read_json(wr_path, None)
        if isinstance(wr, dict) and wr.get("status"):
            executed.append(iw)
            windows[str(iw)] = {
                "status": wr.get("status"),
                "window": iw,
                "metrics": wr.get("metrics", {}) or {},
                "errors": wr.get("errors", []) or [],
                "execution_mode": "recovered_from_window_result",
            }

    if not windows and isinstance(partial, dict):
        pwin = partial.get("windows")
        if isinstance(pwin, dict):
            for k, v in pwin.items():
                try:
                    iw = int(k)
                except Exception:
                    continue
                if iw not in executed:
                    executed.append(iw)
                windows[str(iw)] = {
                    "status": (v or {}).get("status", ""),
                    "window": iw,
                    "metrics": (v or {}).get("metrics", {}) or {},
                    "errors": [],
                    "execution_mode": "recovered_from_executor_partial",
                }

    if not executed and completed_from_log:
        executed = list(completed_from_log)

    executor_out_path = run_dir / "executor_output.json"
    coord_path = run_dir / "coordinator_output.json"
    manifest_path = run_dir / "experiment_manifest.json"

    missing: List[str] = []
    for p in [executor_out_path, coord_path, manifest_path]:
        if not p.exists():
            missing.append(p.name)

    # If executor_output.json missing but we have enough to reconstruct a minimal one, do it.
    recovery_notes: List[str] = []
    if not executor_out_path.exists():
        if not windows and windows_from_log:
            windows = windows_from_log
            executed = sorted([int(k) for k in windows.keys() if str(k).isdigit()])
        if not windows:
            recovery_notes.append("cannot_build_executor_output: no windows data (window_result/partial/log)")
        else:
            ex_status = "run_partial_valid" if len(windows) > 0 else "run_error"
            executor_output = {
                "role": "executor",
                "status": ex_status,
                "run_id": run_dir.name.split("_", 1)[0],
                "script_executed": "",
                "command": "",
                "windows_policy": {
                    "requested": plan.get("requested_windows", []) if isinstance(plan, dict) else [],
                    "allowed": allowed,
                    "policy": "recovered_minimal",
                },
                "windows": windows,
                "errors": recovery_notes,
                "recovery": {"recovered": True, "at": datetime.now().isoformat(timespec="seconds")},
            }
            write_json_atomic(executor_out_path, executor_output)

    # Coordinator: do not attempt to re-run coordinator logic here (avoid side effects).
    coordinator_pending = False
    if not coord_path.exists():
        coordinator_pending = True

    # Manifest: minimal manifest for process visibility if missing.
    if not manifest_path.exists():
        manifest = {
            "run_id": run_dir.name.split("_", 1)[0],
            "run_dir": str(run_dir),
            "status": "recovered_incomplete" if coordinator_pending else "recovered_complete",
            "coordinator_pending": coordinator_pending,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        write_json_atomic(manifest_path, manifest)

    if args.append_experiment_log:
        print("WARNING: --append-experiment-log not implemented by default in recovery script.", file=sys.stderr)

    recovery_report = {
        "run_dir": str(run_dir),
        "missing_before": missing,
        "executor_output_exists": executor_out_path.exists(),
        "coordinator_output_exists": coord_path.exists(),
        "experiment_manifest_exists": manifest_path.exists(),
        "coordinator_pending": coordinator_pending,
        "executed_windows_detected": sorted(list({int(x) for x in executed})),
        "notes": recovery_notes,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json_atomic(run_dir / "recovery_report.json", recovery_report)

    if coordinator_pending:
        print("OK: recovered executor/manifest; coordinator_pending=true")
        return 0
    print("OK: recovered run artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
