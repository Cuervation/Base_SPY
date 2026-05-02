#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def save_json(path: Path, obj: Any) -> None:
    from scripts.safe_io import safe_json_write
    safe_json_write(path, obj, retries=12, delay_seconds=0.25)


def read_trace(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue
    return rows


def read_experiment_log(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f, delimiter=";")]


def is_useful(row: Dict[str, Any]) -> bool:
    if bool(row.get("accepted_for_followup")):
        return True
    decision = str(row.get("decision_type", "")).lower()
    if decision in {"accepted_for_followup", "promoted_to_baseline"}:
        return True
    return False


def is_no_material(row: Dict[str, Any]) -> bool:
    h = " ".join(str(row.get(k, "")) for k in ("status", "decision_type", "main_friction", "recommended_next_action", "error_type")).lower()
    return "no_material_candidate" in h or "blocked_no_material_candidate" in h


def main() -> int:
    ap = argparse.ArgumentParser(description="Reconcile autonomous_loop_state.json from loop_trace.jsonl and experiment_log.csv.")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--write", action="store_true", help="Actually write state/autonomous_loop_state.json. Without this, only writes the report.")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    trace_path = repo / "logs" / "autonomous_loop" / "loop_trace.jsonl"
    exp_path = repo / "trackers" / "experiment_log.csv"
    state_path = repo / "state" / "autonomous_loop_state.json"
    report_path = repo / "reports" / "reconciled_state_report.md"

    trace = read_trace(trace_path)
    exp = read_experiment_log(exp_path)
    old_state = load_json(state_path, {})
    if not isinstance(old_state, dict):
        old_state = {}

    last = trace[-1] if trace else {}
    last_run_id = str(last.get("run_id", "") or old_state.get("last_run_id", ""))
    last_status = str(last.get("status", "") or old_state.get("last_run_status", ""))
    useful = [r for r in trace if is_useful(r)]
    last_useful = useful[-1] if useful else {}
    last_useful_run_id = str(last_useful.get("run_id", "") or old_state.get("last_useful_run_id", ""))

    consecutive_no_material = 0
    for row in reversed(trace):
        if is_no_material(row):
            consecutive_no_material += 1
        else:
            break

    consecutive_rejected = 0
    for row in reversed(trace):
        if str(row.get("decision_type", "")).lower() == "rejected":
            consecutive_rejected += 1
        elif is_useful(row):
            break

    parent = str(last.get("parent_used", "") or old_state.get("current_parent_run_id", ""))
    if not parent and last_useful_run_id:
        parent = last_useful_run_id

    new_state = dict(old_state)
    new_state.update({
        "loop_status": "reconciled_ready",
        "updated_at": now_iso(),
        "last_run_id": last_run_id,
        "last_run_status": last_status,
        "last_successful_run_id": last_useful_run_id,
        "last_useful_run_id": last_useful_run_id,
        "current_parent_run_id": parent,
        "selected_parent_run_id": parent,
        "consecutive_no_material_candidate": consecutive_no_material,
        "consecutive_rejected_without_followup": consecutive_rejected,
        "reconciled_from_trace_at": now_iso(),
        "trace_rows_seen": len(trace),
        "experiment_log_rows_seen": len(exp),
        "stop_reason": "",
    })

    report = [
        "# Reconciled autonomous loop state",
        "",
        f"- generated_at: `{now_iso()}`",
        f"- trace_rows_seen: `{len(trace)}`",
        f"- experiment_log_rows_seen: `{len(exp)}`",
        f"- previous_state_last_run_id: `{old_state.get('last_run_id', '')}`",
        f"- trace_last_run_id: `{last_run_id}`",
        f"- trace_last_status: `{last_status}`",
        f"- last_useful_run_id: `{last_useful_run_id}`",
        f"- selected_parent_run_id: `{parent}`",
        f"- consecutive_no_material_candidate: `{consecutive_no_material}`",
        f"- consecutive_rejected_without_followup: `{consecutive_rejected}`",
        f"- write_applied: `{bool(args.write)}`",
        "",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report), encoding="utf-8")

    if args.write:
        save_json(state_path, new_state)
    else:
        preview_path = repo / "state" / "autonomous_loop_state.reconciled_preview.json"
        save_json(preview_path, new_state)

    print("\n".join(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
