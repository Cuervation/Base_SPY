#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


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


def read_cgf(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return [dict(r) for r in csv.DictReader(f, delimiter=";")]
    except Exception:
        return []


def is_no_material(row: Dict[str, Any]) -> bool:
    h = " ".join(str(row.get(k, "")) for k in ("status", "decision_type", "main_friction", "recommended_next_action", "error_type")).lower()
    return "no_material_candidate" in h or "blocked_no_material_candidate" in h


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit the last autonomous loop runs and CGF failures.")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--last", type=int, default=50)
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    trace_path = repo / "logs" / "autonomous_loop" / "loop_trace.jsonl"
    cgf_path = repo / "state" / "candidate_generation_failures.csv"
    report_path = repo / "reports" / "autonomy_batch_audit.md"

    trace = read_trace(trace_path)
    rows = trace[-max(1, int(args.last)):]
    cgf = read_cgf(cgf_path)
    cgf_recent = cgf[-max(1, int(args.last)):]

    status = Counter(str(r.get("status", "")) for r in rows)
    decision = Counter(str(r.get("decision_type", "")) for r in rows)
    parents = Counter(str(r.get("parent_used", "")) for r in rows)
    cgf_parents = Counter(str(r.get("parent_run_id", "")) for r in cgf_recent)
    no_mat_trace = sum(1 for r in rows if is_no_material(r))
    accepted = sum(1 for r in rows if bool(r.get("accepted_for_followup")))
    promoted = sum(1 for r in rows if bool(r.get("promoted_to_baseline")))
    timeouts = sum(1 for r in rows if str(r.get("error_type", "")).lower() == "iteration_timeout")

    no_mat_ratio = (no_mat_trace / len(rows)) if rows else 0.0
    cgf_count = len(cgf_recent)
    loop_health = "OK"
    if cgf_count >= 25:
        loop_health = "BAD: candidate_generation_exhausted_or_near_exhausted"
    elif rows and no_mat_ratio >= 0.80:
        loop_health = "BAD: too_many_no_material_candidate_in_exp_trace"
    elif rows and accepted == 0 and len(rows) >= 10 and cgf_count == 0:
        loop_health = "WARN: no accepted_for_followup in batch"

    lines = [
        "# Autonomy batch audit",
        "",
        f"- generated_at: `{now_iso()}`",
        f"- rows_in_trace_total: `{len(trace)}`",
        f"- rows_audited: `{len(rows)}`",
        f"- cgf_total: `{len(cgf)}`",
        f"- cgf_audited: `{len(cgf_recent)}`",
        f"- loop_health: `{loop_health}`",
        f"- no_material_candidate_in_exp_trace: `{no_mat_trace}`",
        f"- no_material_candidate_trace_ratio: `{no_mat_ratio:.2%}`",
        f"- accepted_for_followup: `{accepted}`",
        f"- promoted_to_baseline: `{promoted}`",
        f"- iteration_timeouts: `{timeouts}`",
        "",
        "## Status counts from EXP trace",
        "",
    ]
    for k, v in status.most_common():
        lines.append(f"- `{k}`: {v}")
    lines += ["", "## Decision counts from EXP trace", ""]
    for k, v in decision.most_common():
        lines.append(f"- `{k}`: {v}")
    lines += ["", "## Parent counts from EXP trace", ""]
    for k, v in parents.most_common(10):
        lines.append(f"- `{k}`: {v}")
    lines += ["", "## Recent CGF parent counts", ""]
    for k, v in cgf_parents.most_common(10):
        lines.append(f"- `{k}`: {v}")
    lines += ["", "## Recent CGF rows", "", "| cgf_id | original_run_id | parent | status | reason |", "| --- | --- | --- | --- | --- |"]
    for r in cgf_recent[-20:]:
        reason = str(r.get("reason", "")).replace("|", "\\|")[:120]
        lines.append(f"| {r.get('cgf_id','')} | {r.get('original_run_id','')} | {r.get('parent_run_id','')} | {r.get('status','')} | {reason} |")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
