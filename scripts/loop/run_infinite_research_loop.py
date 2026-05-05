#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import signal
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import run_multi_agent_iteration as rmi  # noqa: E402
from validators.validate_required_run_artifacts import (  # noqa: E402
    RC_COMPLETE,
    RC_FAIL_UNRECOVERABLE,
    RC_INCOMPLETE_NO_PARENT,
    RC_RECOVERABLE_PARTIAL_RUN,
    classify as classify_required_run_artifacts,
)
from scripts.safe_io import (  # noqa: E402
    safe_append_csv_row,
    safe_append_jsonl,
    safe_json_write,
    safe_text_write,
    single_instance_lock,
)


DEFAULT_CONFIG: Dict[str, Any] = {
    "windows": [4, 8, 24, 52],
    "forbidden_windows": [156],
    "strict_windows": True,
    "max_iterations": 0,
    "baseline_path": "state/current_baseline.json",
    "research_state_path": "state/research_state.json",
    "experiment_log_path": "trackers/experiment_log.csv",
    "dependencies_path": "config/parameter_dependencies.json",
    "runs_root": "runs/multi_agent_runs",
    "stop_on_baseline_change": False,
    "stop_on_156": True,
    "stop_on_promoted_to_baseline": False,
    "stop_on_fix_process_before_more_research": True,
    "stop_on_operational_failures": False,
    "max_consecutive_rejected_without_followup": 999,
    "max_consecutive_operational_failures": 2,
    "sleep_seconds_between_runs": 5,
    "stale_run_recovery_enabled": True,
    "stale_run_recovery_grace_seconds": 180,
    "single_instance_lock_enabled": True,
    "single_instance_lock_path": "state/autonomous_loop.lock",
    "single_instance_lock_stale_seconds": 28800,
    "safe_io_retries": 12,
    "safe_io_delay_seconds": 0.25,
    "iteration_timeout_seconds": 4500,
    "candidate_generation_escape": {
        "enabled": True,
        "max_consecutive_no_material_before_escape": 5,
        "max_consecutive_no_material_before_parent_reset": 10,
        "max_consecutive_no_material_before_axis_reset": 15,
        "max_consecutive_no_material_before_diagnostic_only": 25,
        "stop_batch_on_diagnostic_only": True,
        "quarantine_no_material_runs": True,
        "candidate_generation_failure_dir": "runs/candidate_generation_failures",
        "candidate_generation_failure_log_path": "state/candidate_generation_failures.csv",
        "remove_no_material_from_experiment_log": True,
        "do_not_append_no_material_to_exp_trace": True
    },
    "stop_on_fix_process_before_more_research": False,
    "stop_on_operational_warnings": False,
    "coordinator_output_invalid_policy": "recoverable",
    "parent_invalid_policy": "fallback_to_baseline",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _safe_io_retries() -> int:
    return int(DEFAULT_CONFIG.get("safe_io_retries", 12) or 12)


def _safe_io_delay() -> float:
    return float(DEFAULT_CONFIG.get("safe_io_delay_seconds", 0.25) or 0.25)


def save_json_atomic(path: Path, obj: Any) -> None:
    safe_json_write(path, obj, retries=_safe_io_retries(), delay_seconds=_safe_io_delay())


def write_text_atomic(path: Path, text: str) -> None:
    safe_text_write(path, text, retries=_safe_io_retries(), delay_seconds=_safe_io_delay())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_windows(raw: Any) -> List[int]:
    if isinstance(raw, list):
        vals = raw
    else:
        vals = [p.strip() for p in str(raw or "").split(",")]
    out: List[int] = []
    seen: set[int] = set()
    for item in vals:
        if item in {None, ""}:
            continue
        try:
            iv = int(item)
        except Exception:
            continue
        if iv <= 0 or iv in seen:
            continue
        seen.add(iv)
        out.append(iv)
    return out


def load_config(repo: Path, config_path: Optional[Path] = None) -> Dict[str, Any]:
    path = config_path or (repo / "config" / "autonomous_loop_config.json")
    data = load_json(path, {})
    if not isinstance(data, dict) or not data:
        data = dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    merged["windows"] = parse_windows(merged.get("windows"))
    merged["forbidden_windows"] = parse_windows(merged.get("forbidden_windows"))
    return merged


def effective_windows_from_args(args: argparse.Namespace, config: Dict[str, Any]) -> List[int]:
    """
    Resolve the effective window set for this supervisor session.

    If --windows is provided, CLI wins over config. Config may not add 156 or
    any other progressive window behind the user's back.
    """
    if args.windows:
        windows = parse_windows(args.windows)
        config["windows"] = windows
        config["windows_source"] = "cli"
        config["forbidden_windows"] = [156] if 156 not in windows else []
        return windows

    windows = parse_windows(config.get("windows", []))
    config["windows"] = windows
    config["windows_source"] = "config"
    config["forbidden_windows"] = parse_windows(config.get("forbidden_windows", [156]))
    return windows


def csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            return [dict(r) for r in reader]
    except Exception:
        return []


def parse_run_num(run_id: str) -> int:
    try:
        return rmi.parse_run_id(run_id)
    except Exception:
        return -1


def parse_run_id_from_dirname(dirname: str) -> str:
    try:
        return rmi.parse_run_id_from_dirname(dirname)
    except Exception:
        return ""


def latest_run_dirs_by_id(runs_root: Path) -> Dict[str, Path]:
    out: Dict[str, Path] = {}
    if not runs_root.exists():
        return out
    for d in sorted([p for p in runs_root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True):
        rid = d.name.split("_", 1)[0]
        if rid not in out:
            out[rid] = d
    return out


def load_run_json(run_dir: Path, fname: str) -> Dict[str, Any]:
    data = load_json(run_dir / fname, {})
    return data if isinstance(data, dict) else {}


def process_command_lines() -> List[str]:
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Select-Object -ExpandProperty CommandLine",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return []
        return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    except Exception:
        return []


def run_dir_has_live_process(run_dir: Path, command_lines: List[str]) -> bool:
    needle = str(run_dir).lower()
    return any(needle in line.lower() for line in command_lines)


def run_dir_needs_stale_recovery(run_dir: Path, stale_seconds: int, command_lines: List[str]) -> bool:
    if not run_dir.exists() or not run_dir.is_dir():
        return False
    if run_dir_has_live_process(run_dir, command_lines):
        return False
    if (run_dir / "coordinator_output.json").exists() and (run_dir / "run_status.json").exists():
        return False
    if not (run_dir / "run_live_status.log").exists():
        return False
    markers = ["executor_output.partial.json", "window_execution_plan.json", "coder_output.json"]
    if not any((run_dir / marker).exists() for marker in markers):
        return False
    try:
        newest = max(p.stat().st_mtime for p in run_dir.rglob("*") if p.is_file())
    except Exception:
        return False
    return (time.time() - newest) >= max(0, int(stale_seconds))


def recover_stale_incomplete_runs(repo: Path, runs_root: Path, config: Dict[str, Any]) -> List[str]:
    if not bool(config.get("stale_run_recovery_enabled", True)):
        return []
    grace = int(config.get("stale_run_recovery_grace_seconds", 180))
    command_lines = process_command_lines()
    recovered: List[str] = []
    run_dirs = sorted(
        [p for p in runs_root.iterdir() if p.is_dir()] if runs_root.exists() else [],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for run_dir in run_dirs[:20]:
        if not run_dir_needs_stale_recovery(run_dir, grace, command_lines):
            continue
        run_id = parse_run_id_from_dirname(run_dir.name)
        plan = load_json(run_dir / "window_execution_plan.json", {})
        requested = parse_windows((plan or {}).get("requested_windows", [])) if isinstance(plan, dict) else []
        allowed = parse_windows((plan or {}).get("allowed_windows", [])) if isinstance(plan, dict) else []
        progressive = parse_windows((plan or {}).get("progressive_plan", [])) if isinstance(plan, dict) else []
        if not progressive:
            progressive = allowed or requested
        try:
            rmi.ensure_controlled_abort_artifacts(
                run_dir=run_dir,
                run_id=run_id,
                requested_windows=requested,
                allowed_windows=allowed,
                progressive_windows=progressive,
                reason="stale_supervisor_recovery_no_live_process",
                status_hint="run_error",
            )
            recovered.append(run_id or run_dir.name)
        except Exception:
            continue
    if recovered:
        save_json_atomic(
            repo / "state" / "stale_run_recovery_last.json",
            {"recovered_run_ids": recovered, "updated_at": now_iso()},
        )
    return recovered


def run_has_required_core_artifacts(run_dir: Path) -> bool:
    required = ["executor_output.json", "coordinator_output.json", "experiment_manifest.json", "run_status.json", "window_execution_plan.json"]
    return all((run_dir / f).exists() for f in required)


def parent_candidate_contexts(repo: Path, research_state: Dict[str, Any], champion_runs: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    candidates: List[Tuple[str, Dict[str, Any]]] = []
    p_state = research_state.get("parent_state", {}) if isinstance(research_state.get("parent_state"), dict) else {}
    st = research_state.get("state_tracking", {}) if isinstance(research_state.get("state_tracking"), dict) else {}

    raw_ids = [
        ("research.parent_state.current_parent_run_id", rmi.clean_text(p_state.get("current_parent_run_id", ""))),
        ("research.parent_state.last_useful_run_id", rmi.clean_text(p_state.get("last_useful_run_id", ""))),
        ("research.last_followup_run_id", rmi.clean_text(st.get("last_followup_run_id", ""))),
        ("research.last_useful_run_id", rmi.clean_text(st.get("last_useful_run_id", ""))),
    ]
    seen: set[str] = set()
    for src, rid in raw_ids:
        if not rid or rid == "BASELINE_CLEAN" or rid in seen:
            continue
        seen.add(rid)
        ctx = rmi.get_run_context_by_run_id(repo, rid)
        if ctx:
            candidates.append((src, ctx))

    champ_ctx, champ_src = rmi.get_best_champion_context(repo, champion_runs or {})
    if champ_ctx:
        candidates.append((champ_src or "champion", champ_ctx))

    latest_ctx = rmi.get_latest_valid_run_context(repo)
    if latest_ctx:
        candidates.append(("latest_valid_scan", latest_ctx))

    dedup: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for src, ctx in candidates:
        rid = rmi.clean_text(ctx.get("run_id", ""))
        if not rid:
            continue
        if rid not in dedup or parse_run_num(rid) > parse_run_num(rmi.clean_text(dedup[rid][1].get("run_id", ""))):
            dedup[rid] = (src, ctx)
    ordered = sorted(
        dedup.values(),
        key=lambda item: parse_run_num(rmi.clean_text(item[1].get("run_id", ""))),
        reverse=True,
    )
    return ordered


def select_parent_context(
    repo: Path,
    research_state: Dict[str, Any],
    champion_runs: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], str, str, str]:
    if rmi.research_state_requests_baseline_parent(research_state):
        return None, "current_baseline", "", ""

    candidates = parent_candidate_contexts(repo, research_state, champion_runs)
    rejected_startup_parent_run_id = ""
    rejected_startup_parent_reason = ""
    if candidates:
        for src, ctx in candidates:
            guard = rmi.evaluate_startup_parent_depth_guard_52w(ctx)
            if not bool(guard.get("pass", False)):
                if not rejected_startup_parent_run_id:
                    rejected_startup_parent_run_id = rmi.clean_text(guard.get("run_id", "")) or rmi.clean_text((ctx or {}).get("run_id", ""))
                    rejected_startup_parent_reason = rmi.clean_text(guard.get("reason", "")) or "startup_parent_rejected_low_depth_52w"
                continue
            rid = rmi.clean_text((ctx or {}).get("run_id", ""))
            return ctx, f"{src}={rid}" if rid else src, rejected_startup_parent_run_id, rejected_startup_parent_reason
    return None, "current_baseline", rejected_startup_parent_run_id, rejected_startup_parent_reason


def preflight_supervisor_state(repo: Path, config: Dict[str, Any]) -> Dict[str, Any]:
    research_state_path, research_state = load_research_state(repo, config)
    paths_cfg = rmi.load_paths_config(repo)
    legacy_champion_runs_rel = rmi.cfg_get_str(
        paths_cfg,
        ["runs", "champion_runs_json"],
        "runs/champion_runs/champion_runs.json",
    )
    champion_runs_rel = rmi.cfg_get_str(
        paths_cfg,
        ["state", "champion_runs"],
        legacy_champion_runs_rel,
    )
    champion_runs_path = (repo / champion_runs_rel).resolve()
    champion_runs = load_json(champion_runs_path, {})
    if not isinstance(champion_runs, dict):
        champion_runs = {}
    parent_ctx, parent_source, rejected_startup_parent_run_id, rejected_startup_parent_reason = select_parent_context(
        repo, research_state, champion_runs
    )
    parent_valid = bool(parent_ctx) or parent_source == "current_baseline"
    parent_run_id = rmi.clean_text((parent_ctx or {}).get("run_id", "")) if parent_ctx else ""
    if not parent_run_id and parent_source == "current_baseline":
        parent_run_id = "BASELINE_CLEAN"
    effective_windows = parse_windows(config.get("windows", []))
    return {
        "research_state_path": research_state_path,
        "parent_ctx": parent_ctx,
        "parent_source": parent_source,
        "parent_valid": parent_valid,
        "selected_parent_run_id": parent_run_id,
        "rejected_startup_parent_run_id": rejected_startup_parent_run_id,
        "rejected_startup_parent_reason": rejected_startup_parent_reason,
        "effective_windows": effective_windows,
        "forbidden_windows": parse_windows(config.get("forbidden_windows", [])),
        "baseline_parent_requested": rmi.research_state_requests_baseline_parent(research_state),
    }


def is_forbidden_156_present(run_dir: Path) -> bool:
    plan = load_json(run_dir / "window_execution_plan.json", {})
    if not isinstance(plan, dict):
        return False
    for key in ("requested_windows", "allowed_windows", "planned_windows", "progressive_plan", "executed_windows"):
        vals = plan.get(key)
        if isinstance(vals, list):
            for v in vals:
                try:
                    if int(v) == 156:
                        return True
                except Exception:
                    continue
    return False


def validate_window_constraints(run_dir: Path, allowed_windows: List[int]) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "validators" / "validate_window_constraints.py"),
        "--run-dir",
        str(run_dir),
        "--allowed-windows",
        ",".join(str(int(x)) for x in allowed_windows),
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    msg = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, msg


def validate_coordinator_output(path: Path) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "validators" / "validate_coordinator_output.py"),
        "--path",
        str(path),
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    msg = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, msg


def validate_baseline_immutability(baseline_path: Path, expected_hash: str) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "validators" / "validate_baseline_immutability.py"),
        "--baseline",
        str(baseline_path),
        "--expected-hash",
        expected_hash,
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    msg = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, msg


def classify_artifacts(run_dir: Path) -> Tuple[int, str]:
    rc, msg = classify_required_run_artifacts(run_dir)
    return rc, msg


def update_research_parent_state(
    repo: Path,
    research_state_path: Path,
    selected_parent_run_id: str,
    parent_source: str = "",
) -> None:
    rs = load_json(research_state_path, {})
    if not isinstance(rs, dict):
        return
    p_state = rs.setdefault("parent_state", {})
    if not isinstance(p_state, dict):
        p_state = {}
        rs["parent_state"] = p_state
    if parent_source == "current_baseline":
        p_state["current_parent_run_id"] = None
        p_state["last_useful_run_id"] = None
        p_state["parent_source"] = "current_baseline"
        p_state["use_baseline_as_parent"] = True
    else:
        p_state["current_parent_run_id"] = selected_parent_run_id or "BASELINE_CLEAN"
        p_state["parent_source"] = parent_source or p_state.get("parent_source", "")
    if selected_parent_run_id and selected_parent_run_id != "BASELINE_CLEAN":
        p_state["last_useful_run_id"] = selected_parent_run_id
    rs["updated_at"] = now_iso()
    save_json_atomic(research_state_path, rs)


def write_loop_state(path: Path, payload: Dict[str, Any]) -> None:
    save_json_atomic(path, payload)


def append_trace(trace_path: Path, payload: Dict[str, Any]) -> None:
    safe_append_jsonl(trace_path, payload, retries=_safe_io_retries(), delay_seconds=_safe_io_delay())


def _candidate_escape_config(config: Dict[str, Any]) -> Dict[str, Any]:
    ce = config.get("candidate_generation_escape", {})
    return ce if isinstance(ce, dict) else {}


def _candidate_failure_header() -> List[str]:
    return [
        "at", "cgf_id", "original_run_id", "parent_run_id", "status", "reason",
        "escape_level", "consecutive_no_material_candidate", "quarantined_run_dir",
        "original_run_dir", "candidate_family", "candidate_axis", "experiment_log_rows_removed",
    ]


def _next_cgf_id(repo: Path, config: Dict[str, Any]) -> str:
    ce = _candidate_escape_config(config)
    log_path = (repo / str(ce.get("candidate_generation_failure_log_path", "state/candidate_generation_failures.csv"))).resolve()
    mx = 0
    if log_path.exists():
        try:
            with log_path.open("r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f, delimiter=";"):
                    raw = str(row.get("cgf_id", ""))
                    if raw.startswith("CGF_"):
                        try:
                            mx = max(mx, int(raw.split("_", 1)[1]))
                        except Exception:
                            pass
        except Exception:
            pass
    return f"CGF_{mx + 1:06d}"


def _remove_no_material_rows_from_experiment_log(exp_log_path: Path, run_id: str) -> int:
    run_id = rmi.clean_text(run_id)
    if not run_id or not exp_log_path.exists():
        return 0
    try:
        with exp_log_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            fieldnames = list(reader.fieldnames or [])
            rows = [dict(r) for r in reader]
        if not fieldnames:
            return 0
        kept: List[Dict[str, Any]] = []
        removed = 0
        for row in rows:
            same = rmi.clean_text(row.get("run_id", "")) == run_id
            status = rmi.clean_text(row.get("status", "")).lower()
            notes = rmi.clean_text(row.get("notes", "")).lower()
            no_material = "no_material" in status or "no_material" in notes or "no material" in notes
            if same and no_material:
                removed += 1
                continue
            kept.append(row)
        if not removed:
            return 0
        tmp_path = exp_log_path.with_name(f"{exp_log_path.name}.{os.getpid()}.{time.time_ns()}.rewrite.tmp")
        with tmp_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";", extrasaction="ignore")
            writer.writeheader()
            for row in kept:
                writer.writerow(row)
        os.replace(str(tmp_path), str(exp_log_path))
        return removed
    except Exception:
        return 0


def _quarantine_no_material_candidate_run(
    repo: Path,
    config: Dict[str, Any],
    result: Dict[str, Any],
    loop_state: Dict[str, Any],
    *,
    escape_level: str = "",
) -> Dict[str, Any]:
    ce = _candidate_escape_config(config)
    if not bool(ce.get("quarantine_no_material_runs", True)):
        return {}
    run_id = rmi.clean_text(result.get("run_id", ""))
    run_dir_raw = rmi.clean_text(result.get("run_dir", ""))
    if not run_id:
        return {}
    cgf_id = _next_cgf_id(repo, config)
    failure_root = (repo / str(ce.get("candidate_generation_failure_dir", "runs/candidate_generation_failures"))).resolve()
    failure_root.mkdir(parents=True, exist_ok=True)
    original_run_dir = Path(run_dir_raw).resolve() if run_dir_raw else None
    quarantine_dir = failure_root / f"{cgf_id}_{run_id}_{datetime.now().strftime('%y%m%d%H%M%S')}"
    moved = False
    if original_run_dir and original_run_dir.exists() and original_run_dir.is_dir():
        try:
            if quarantine_dir.exists():
                quarantine_dir = failure_root / f"{cgf_id}_{run_id}_{time.time_ns()}"
            shutil.move(str(original_run_dir), str(quarantine_dir))
            moved = True
        except Exception:
            quarantine_dir = original_run_dir
    reason = (
        rmi.clean_text(result.get("no_material_reason", ""))
        or rmi.clean_text(result.get("recommended_next_action", ""))
        or rmi.clean_text(result.get("status", ""))
        or "blocked_no_material_candidate"
    )
    removed = 0
    if bool(ce.get("remove_no_material_from_experiment_log", True)):
        removed = _remove_no_material_rows_from_experiment_log(load_experiment_log_path(repo, config), run_id)
    row = {
        "at": now_iso(),
        "cgf_id": cgf_id,
        "original_run_id": run_id,
        "parent_run_id": rmi.clean_text(result.get("parent_run_id", "")),
        "status": rmi.clean_text(result.get("status", "")),
        "reason": reason,
        "escape_level": escape_level,
        "consecutive_no_material_candidate": int(loop_state.get("consecutive_no_material_candidate", 0)),
        "quarantined_run_dir": str(quarantine_dir) if quarantine_dir else "",
        "original_run_dir": run_dir_raw,
        "candidate_family": rmi.clean_text(result.get("candidate_family", "")),
        "candidate_axis": rmi.clean_text(result.get("candidate_axis", "")),
        "experiment_log_rows_removed": removed,
    }
    safe_append_csv_row(
        (repo / str(ce.get("candidate_generation_failure_log_path", "state/candidate_generation_failures.csv"))).resolve(),
        _candidate_failure_header(), row, delimiter=";", retries=_safe_io_retries(), delay_seconds=_safe_io_delay(),
    )
    event = dict(row)
    event["action"] = "quarantine_no_material_candidate_run"
    event["moved"] = moved
    result["candidate_generation_failure_id"] = cgf_id
    result["quarantined_run_dir"] = str(quarantine_dir) if quarantine_dir else ""
    result["exp_consumption_prevented"] = bool(removed)
    loop_state["last_candidate_generation_failure"] = event
    save_json_atomic(repo / "state" / "last_candidate_generation_failure.json", event)
    return event


def write_candidate_generation_diagnostic(
    repo: Path, config: Dict[str, Any], loop_state: Dict[str, Any], result: Dict[str, Any],
    recent_results: List[Dict[str, Any]], *, reason: str, final: bool = False,
) -> Path:
    diag = {
        "at": now_iso(),
        "reason": reason,
        "final": bool(final),
        "last_run_id": result.get("run_id", ""),
        "last_cgf_id": result.get("candidate_generation_failure_id", ""),
        "parent_run_id": result.get("parent_run_id", ""),
        "current_parent_run_id": loop_state.get("current_parent_run_id", ""),
        "selected_parent_run_id": loop_state.get("selected_parent_run_id", ""),
        "consecutive_no_material_candidate": int(loop_state.get("consecutive_no_material_candidate", 0)),
        "candidate_generation_escape_event": loop_state.get("candidate_generation_escape_event", {}),
        "branch_exhausted_event": loop_state.get("branch_exhausted_event", {}),
        "recent_results": [
            {
                "run_id": r.get("run_id", ""), "cgf_id": r.get("candidate_generation_failure_id", ""),
                "status": r.get("status", ""), "parent_run_id": r.get("parent_run_id", ""),
                "recommended_next_action": r.get("recommended_next_action", ""),
                "main_friction": r.get("main_friction", ""), "branch_health": r.get("branch_health", ""),
                "windows_executed": r.get("windows_executed", []),
            } for r in recent_results[-25:]
        ],
        "recommended_actions": [
            "No seguir lanzando EXP si no hay candidato material.",
            "Revisar fallback_candidate_pool_considered y cooldowns activos.",
            "Cambiar parent/familia/eje antes de reintentar.",
            "Si el parent actual sigue agotado, usar baseline clean como parent temporal de exploracion.",
        ],
    }
    path = repo / "reports" / "candidate_generation_exhaustion_diagnostic.json"
    save_json_atomic(path, diag)
    md = [
        "# Candidate Generation Exhaustion Diagnostic", "",
        f"- at: `{diag['at']}`", f"- reason: `{reason}`", f"- final: `{bool(final)}`",
        f"- parent_run_id: `{diag.get('parent_run_id','')}`",
        f"- current_parent_run_id: `{diag.get('current_parent_run_id','')}`",
        f"- consecutive_no_material_candidate: `{diag.get('consecutive_no_material_candidate',0)}`",
        f"- last_run_id: `{diag.get('last_run_id','')}`", f"- last_cgf_id: `{diag.get('last_cgf_id','')}`",
        "", "## Recommended actions",
    ]
    for item in diag["recommended_actions"]:
        md.append(f"- {item}")
    md.extend(["", "## Recent results", "| run_id | cgf_id | status | parent | windows |", "| --- | --- | --- | --- | --- |"])
    for r in diag["recent_results"][-15:]:
        md.append(f"| {r.get('run_id','')} | {r.get('cgf_id','')} | {r.get('status','')} | {r.get('parent_run_id','')} | {','.join(str(x) for x in (r.get('windows_executed') or []))} |")
    safe_text_write(repo / "reports" / "candidate_generation_exhaustion_diagnostic.md", "\n".join(md) + "\n", retries=_safe_io_retries(), delay_seconds=_safe_io_delay())
    return path


def render_live_summary(state: Dict[str, Any], recent_runs: List[Dict[str, Any]], parent_info: Dict[str, Any]) -> str:
    selected_parent_run_id = (
        parent_info.get("parent_run_id")
        or parent_info.get("selected_parent_run_id")
        or state.get("selected_parent_run_id")
        or parent_info.get("run_id")
        or ""
    )
    selected_parent_source = (
        parent_info.get("parent_source")
        or parent_info.get("selected_parent_source")
        or state.get("selected_parent_source")
        or parent_info.get("source")
        or ""
    )

    if "parent_valid" in parent_info:
        parent_valid = bool(parent_info.get("parent_valid"))
    else:
        parent_valid = bool(parent_info.get("valid", False))

    lines = [
        "# Autonomous Loop Live Summary",
        "",
        f"- loop_status: `{state.get('loop_status', '')}`",
        f"- iterations_completed: `{state.get('iterations_completed', 0)}`",
        f"- consecutive_rejected_without_followup: `{state.get('consecutive_rejected_without_followup', 0)}`",
        f"- consecutive_operational_failures: `{state.get('consecutive_operational_failures', 0)}`",
        f"- current_parent_run_id: `{state.get('current_parent_run_id', '')}`",
        f"- last_run_id: `{state.get('last_run_id', '')}`",
        f"- stop_reason: `{state.get('stop_reason', '')}`",
        "",
        "## Parent",
        f"- selected_parent_run_id: `{selected_parent_run_id}`",
        f"- selected_parent_source: `{selected_parent_source}`",
        f"- parent_valid: `{parent_valid}`",
        "",
        "## Recent Runs",
    ]

    if not recent_runs:
        lines.append("- none yet")
    else:
        lines.append("| run_id | status | decision_type | next_action | followup | promotion |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for r in recent_runs[-5:]:
            lines.append(
                f"| {r.get('run_id','')} | {r.get('status','')} | {r.get('decision_type','')} | "
                f"{r.get('recommended_next_action','')} | {r.get('accepted_for_followup','')} | {r.get('promoted_to_baseline','')} |"
            )

    return "\n".join(lines) + "\n"


def render_final_summary(final: Dict[str, Any]) -> str:
    lines = [
        "# Autonomous Loop Final Summary",
        "",
        f"## Verdict",
        f"- status: `{final.get('status','')}`",
        f"- runs_executed: `{final.get('runs_executed', 0)}`",
        f"- stop_reason: `{final.get('stop_reason','')}`",
        f"- baseline_changed: `{final.get('baseline_changed', False)}`",
        f"- 156_executed: `{final.get('executed_156', False)}`",
        f"- incomplete_runs: `{len(final.get('incomplete_runs', []))}`",
        f"- no_parent_runs: `{len(final.get('no_parent_runs', []))}`",
        f"- accepted_for_followup_runs: `{len(final.get('accepted_for_followup_runs', []))}`",
        f"- pending_promotion_review: `{len(final.get('pending_promotion_review', []))}`",
        "",
        "## Best / Worst",
        f"- best_run: `{final.get('best_run_id','')}`",
        f"- worst_run: `{final.get('worst_run_id','')}`",
        "",
        "## Recommendation",
        f"- final_recommendation: `{final.get('recommendation','')}`",
    ]
    return "\n".join(lines) + "\n"


def find_new_run_dir(runs_root: Path, before: set[str]) -> Optional[Path]:
    if not runs_root.exists():
        return None
    candidates = [p for p in runs_root.iterdir() if p.is_dir() and p.name not in before]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def load_research_state(repo: Path, config: Dict[str, Any]) -> Tuple[Path, Dict[str, Any]]:
    research_state_rel = rmi.cfg_get_str(
        rmi.load_paths_config(repo),
        ["state", "research_state"],
        config.get("research_state_path", "state/research_state.json"),
    )
    research_state_path = (repo / research_state_rel).resolve()
    research_state = load_json(research_state_path, {})
    if not isinstance(research_state, dict):
        research_state = {}
    return research_state_path, research_state


def load_baseline_path(repo: Path, config: Dict[str, Any]) -> Path:
    baseline_rel = rmi.cfg_get_str(
        rmi.load_paths_config(repo),
        ["state", "current_baseline"],
        config.get("baseline_path", "state/current_baseline.json"),
    )
    return (repo / baseline_rel).resolve()


def load_experiment_log_path(repo: Path, config: Dict[str, Any]) -> Path:
    exp_rel = rmi.cfg_get_str(
        rmi.load_paths_config(repo),
        ["trackers", "experiment_log"],
        config.get("experiment_log_path", "trackers/experiment_log.csv"),
    )
    return (repo / exp_rel).resolve()


def load_dependencies_path(repo: Path, config: Dict[str, Any]) -> Path:
    dep_rel = rmi.cfg_get_str(
        rmi.load_paths_config(repo),
        ["config", "parameter_dependencies"],
        config.get("dependencies_path", "config/parameter_dependencies.json"),
    )
    return (repo / dep_rel).resolve()


def load_runs_root(repo: Path, config: Dict[str, Any]) -> Path:
    runs_rel = rmi.cfg_get_str(
        rmi.load_paths_config(repo),
        ["runs", "multi_agent_runs"],
        config.get("runs_root", "runs/multi_agent_runs"),
    )
    return (repo / runs_rel).resolve()


def run_one_iteration(repo: Path, config: Dict[str, Any], baseline_hash_before: str, dry_run: bool = False) -> Dict[str, Any]:
    baseline_path = load_baseline_path(repo, config)
    research_state_path, research_state = load_research_state(repo, config)
    exp_log_path = load_experiment_log_path(repo, config)
    runs_root = load_runs_root(repo, config)
    runs_root.mkdir(parents=True, exist_ok=True)
    paths_cfg = rmi.load_paths_config(repo)
    legacy_champion_runs_rel = rmi.cfg_get_str(
        paths_cfg,
        ["runs", "champion_runs_json"],
        "runs/champion_runs/champion_runs.json",
    )
    champion_runs_rel = rmi.cfg_get_str(
        paths_cfg,
        ["state", "champion_runs"],
        legacy_champion_runs_rel,
    )
    champion_runs_path = (repo / champion_runs_rel).resolve()
    champion_runs = load_json(champion_runs_path, {})
    if not isinstance(champion_runs, dict):
        champion_runs = {}

    parent_ctx, parent_source, rejected_startup_parent_run_id, rejected_startup_parent_reason = select_parent_context(
        repo, research_state, champion_runs
    )
    parent_run_id = rmi.clean_text((parent_ctx or {}).get("run_id", "")) or (
        "BASELINE_CLEAN" if parent_source == "current_baseline" else ""
    )
    parent_valid = bool(parent_ctx) or parent_source == "current_baseline"

    if not parent_valid:
        return {
            "status": "blocked_parent_invalid",
            "error_type": "parent_invalid",
            "run_id": "",
            "run_dir": "",
            "parent_run_id": parent_run_id,
            "parent_source": parent_source,
            "rejected_startup_parent_run_id": rejected_startup_parent_run_id,
            "rejected_startup_parent_reason": rejected_startup_parent_reason,
            "parent_valid": False,
            "windows": list(config.get("windows", [])),
            "forbidden_windows": list(config.get("forbidden_windows", [])),
            "baseline_hash_before": baseline_hash_before,
            "baseline_hash_after": sha256_file(baseline_path) if baseline_path.exists() else "",
        }

    if dry_run:
        return {
            "dry_run": True,
            "parent_run_id": parent_run_id,
            "parent_source": parent_source,
            "rejected_startup_parent_run_id": rejected_startup_parent_run_id,
            "rejected_startup_parent_reason": rejected_startup_parent_reason,
            "parent_valid": parent_valid,
            "baseline_hash_before": baseline_hash_before,
            "windows": list(config.get("windows", [])),
            "forbidden_windows": list(config.get("forbidden_windows", [])),
        }

    update_research_parent_state(repo, research_state_path, parent_run_id, parent_source=parent_source)
    before_dirs = {d.name for d in runs_root.iterdir() if d.is_dir()} if runs_root.exists() else set()

    cmd = [
        sys.executable,
        str(REPO_ROOT / "run_multi_agent_iteration.py"),
        "--repo",
        str(repo),
        "--baseline-json",
        str(baseline_path),
        "--experiment-log",
        str(exp_log_path),
        "--dependencies-json",
        str(load_dependencies_path(repo, config)),
        "--evaluation-windows",
        ",".join(str(int(x)) for x in config.get("windows", [])),
        "--year-validation-window-weeks",
        str(int(config.get("year_validation_window_weeks", 52))),
        "--long156-policy",
        str(config.get("long156_policy", "never")),
    ]
    iteration_timeout = int(config.get("iteration_timeout_seconds", 4500) or 4500)
    timeout_hit = False
    try:
        proc = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, timeout=iteration_timeout)
    except subprocess.TimeoutExpired as e:
        timeout_hit = True
        stdout = e.stdout.decode("utf-8", errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        stderr = (stderr + f"\nITERATION_TIMEOUT_AFTER_SECONDS={iteration_timeout}").strip()
        proc = subprocess.CompletedProcess(cmd, 124, stdout, stderr)
    after_dir = find_new_run_dir(runs_root, before_dirs)
    run_id = parse_run_id_from_dirname(after_dir.name) if after_dir else ""
    result: Dict[str, Any] = {
        "returncode": proc.returncode,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
        "run_dir": str(after_dir) if after_dir else "",
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "parent_source": parent_source,
        "parent_valid": parent_valid,
        "windows": list(config.get("windows", [])),
        "forbidden_windows": list(config.get("forbidden_windows", [])),
        "baseline_hash_before": baseline_hash_before,
        "baseline_hash_after": sha256_file(baseline_path) if baseline_path.exists() else "",
    }

    if timeout_hit:
        result["status"] = "RECOVERABLE_PARTIAL_RUN"
        result["error_type"] = "iteration_timeout"
        result["timeout_seconds"] = iteration_timeout
        result["no_parent"] = True
        if after_dir:
            save_json_atomic(
                after_dir / "recovery_status.json",
                {
                    "status": "RECOVERABLE_PARTIAL_RUN",
                    "reason": "iteration_timeout",
                    "timeout_seconds": iteration_timeout,
                    "safe_for_strategy_analysis": False,
                    "safe_for_process_analysis": True,
                    "do_not_use_as_parent": True,
                    "updated_at": now_iso(),
                },
            )
        return result

    if not after_dir:
        result["error_type"] = "run_dir_not_found"
        return result

    # Required artifact validator.
    art_rc, art_msg = classify_artifacts(after_dir)
    result["artifacts_rc"] = art_rc
    result["artifacts_msg"] = art_msg

    run_status = load_run_json(after_dir, "run_status.json")
    manifest = load_run_json(after_dir, "experiment_manifest.json")
    co = load_run_json(after_dir, "coordinator_output.json")
    eo = load_run_json(after_dir, "executor_output.json")
    recovery = load_run_json(after_dir, "recovery_status.json")
    plan = load_json(after_dir / "window_execution_plan.json", {})

    result["status"] = rmi.clean_text((run_status or {}).get("status", "")) or rmi.clean_text((manifest or {}).get("status", ""))
    result["decision_type"] = rmi.clean_text((co or {}).get("decision_type", "")) if co else ""
    result["accepted_for_followup"] = bool((co or {}).get("accepted_for_followup", False))
    result["promoted_to_baseline"] = bool((co or {}).get("promoted_to_baseline", False))
    result["do_not_use_as_parent"] = bool((((co or {}).get("compare", {}) or {}).get("do_not_use_as_parent", False)))
    result["branch_anchor_allowed"] = (((co or {}).get("compare", {}) or {}).get("branch_anchor_allowed", None))
    result["recommended_next_action"] = rmi.clean_text(((co or {}).get("auditor_v2_evaluation", {}) or {}).get("recommended_next_action", ""))
    result["recommended_change_directions"] = (co or {}).get("auditor_v2_evaluation", {}).get("recommended_change_directions", []) if isinstance((co or {}).get("auditor_v2_evaluation", {}), dict) else []
    result["overall_agent_score"] = ((co or {}).get("auditor_v2_evaluation", {}) or {}).get("overall_agent_score")
    result["research_value"] = ((co or {}).get("auditor_v2_evaluation", {}) or {}).get("research_value")
    result["branch_health"] = ((co or {}).get("auditor_v2_evaluation", {}) or {}).get("branch_health")
    result["main_friction"] = ((co or {}).get("auditor_v2_evaluation", {}) or {}).get("main_friction")
    result["windows_executed"] = (plan or {}).get("executed_windows", [])
    result["no_material_reason"] = "; ".join(str(x) for x in ((co or {}).get("reasons", []) or []))
    result["fallback_diagnosis"] = (co or {}).get("fallback_diagnosis", {}) if isinstance(co, dict) else {}
    result["fallback_candidate_pool_considered"] = (co or {}).get("fallback_candidate_pool_considered", []) if isinstance(co, dict) else []
    result["candidate_family"] = rmi.clean_text(((co or {}).get("proposal", {}) or {}).get("candidate_type", "")) if isinstance((co or {}).get("proposal", {}), dict) else ""
    result["candidate_axis"] = rmi.clean_text(((co or {}).get("main_change", {}) or {}).get("parameter", "")) if isinstance((co or {}).get("main_change", {}), dict) else ""

    if art_rc == RC_RECOVERABLE_PARTIAL_RUN:
        finalize_cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "recovery" / "finalize_incomplete_run.py"),
            "--run-dir",
            str(after_dir),
        ]
        fin = subprocess.run(finalize_cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=min(600, int(config.get("iteration_timeout_seconds", 4500) or 4500)))
        result["recovery_finalize_returncode"] = fin.returncode
        result["recovery_finalize_stdout"] = fin.stdout or ""
        result["recovery_finalize_stderr"] = fin.stderr or ""
        art_rc, art_msg = classify_artifacts(after_dir)
        result["artifacts_rc_after_recovery"] = art_rc
        result["artifacts_msg_after_recovery"] = art_msg
        co = load_run_json(after_dir, "coordinator_output.json")
        result["decision_type"] = rmi.clean_text((co or {}).get("decision_type", "")) if co else result.get("decision_type", "")
        result["accepted_for_followup"] = bool((co or {}).get("accepted_for_followup", False))
        result["promoted_to_baseline"] = bool((co or {}).get("promoted_to_baseline", False))
    result["do_not_use_as_parent"] = bool((((co or {}).get("compare", {}) or {}).get("do_not_use_as_parent", False)))
    result["branch_anchor_allowed"] = (((co or {}).get("compare", {}) or {}).get("branch_anchor_allowed", None))

    if art_msg == "BLOCKED_PREFLIGHT_COMPLETE":
        result["status"] = "BLOCKED_PREFLIGHT_COMPLETE"
    elif art_rc == RC_RECOVERABLE_PARTIAL_RUN:
        result["status"] = "RECOVERABLE_PARTIAL_RUN"
    elif art_rc == RC_INCOMPLETE_NO_PARENT:
        result["status"] = "INCOMPLETE_NO_PARENT"

    # If still no coordinator output, preserve process evidence only.
    if not (after_dir / "coordinator_output.json").exists():
        recovery_status = {
            "status": "incomplete_no_parent" if art_rc != RC_COMPLETE else "recoverable_no_coordinator",
            "reason": "missing_coordinator_output",
            "safe_for_strategy_analysis": False,
            "safe_for_process_analysis": True,
            "do_not_use_as_parent": True,
            "updated_at": now_iso(),
        }
        save_json_atomic(after_dir / "recovery_status.json", recovery_status)
        result["no_parent"] = True

    # Validate artifacts and baseline immutability only for runs with coordinator output.
    if (after_dir / "coordinator_output.json").exists():
        coord_rc, coord_msg = validate_coordinator_output(after_dir / "coordinator_output.json")
        result["coordinator_validation_rc"] = coord_rc
        result["coordinator_validation_msg"] = coord_msg
    else:
        result["coordinator_validation_rc"] = None
        result["coordinator_validation_msg"] = "skipped_missing_coordinator"

    base_rc, base_msg = validate_baseline_immutability(baseline_path, baseline_hash_before)
    result["baseline_validation_rc"] = base_rc
    result["baseline_validation_msg"] = base_msg

    if baseline_path.exists():
        result["baseline_hash_after"] = sha256_file(baseline_path)

    return result


def update_state_after_result(
    repo: Path,
    config: Dict[str, Any],
    loop_state: Dict[str, Any],
    result: Dict[str, Any],
) -> Dict[str, Any]:
    loop_state["updated_at"] = now_iso()
    loop_state["last_run_id"] = result.get("run_id", "") or loop_state.get("last_run_id", "")
    if result.get("status"):
        loop_state["last_run_status"] = result.get("status")
    if result.get("decision_type"):
        loop_state["last_decision_type"] = result.get("decision_type")

    branch_anchor_allowed = result.get("branch_anchor_allowed")
    if branch_anchor_allowed is None:
        branch_anchor_allowed = not bool(result.get("do_not_use_as_parent", False))

    parent_used = rmi.clean_text(result.get("parent_run_id", ""))
    parent_source = rmi.clean_text(result.get("parent_source", ""))
    if parent_used:
        loop_state["selected_parent_run_id"] = parent_used
        loop_state["selected_parent_source"] = parent_source
        loop_state["parent_valid"] = bool(result.get("parent_valid", False))
        # Keep audit state aligned with the selected parent even when the current
        # result is rejected. This does NOT move parent to the rejected run; it
        # records the parent used for comparison. Accepted useful runs below can
        # still advance current_parent_run_id to their own run_id.
        if parent_used != "BASELINE_CLEAN" and not (result.get("accepted_for_followup") and bool(branch_anchor_allowed)):
            loop_state["current_parent_run_id"] = parent_used

    if result.get("accepted_for_followup") and bool(branch_anchor_allowed):
        loop_state["consecutive_rejected_without_followup"] = 0
        loop_state["last_successful_run_id"] = result.get("run_id", "")
        loop_state["last_useful_run_id"] = result.get("run_id", "")
        loop_state["current_parent_run_id"] = result.get("run_id", "")
    elif result.get("accepted_for_followup") and not bool(branch_anchor_allowed):
        # Defensa extra: una corrida marcada do_not_use_as_parent nunca puede mover el parent.
        loop_state["last_rejected_parent_candidate_run_id"] = result.get("run_id", "")
        loop_state["last_rejected_parent_candidate_reason"] = "accepted_but_do_not_use_as_parent"
        loop_state["consecutive_rejected_without_followup"] = int(loop_state.get("consecutive_rejected_without_followup", 0)) + 1
    elif result.get("decision_type") == "rejected" and result.get("status") != "BLOCKED_PREFLIGHT_COMPLETE":
        loop_state["consecutive_rejected_without_followup"] = int(loop_state.get("consecutive_rejected_without_followup", 0)) + 1

    if result.get("status") in {"RECOVERABLE_PARTIAL_RUN", "INCOMPLETE_NO_PARENT"}:
        loop_state["consecutive_operational_failures"] = int(loop_state.get("consecutive_operational_failures", 0)) + 1
    elif result.get("status") == "BLOCKED_PREFLIGHT_COMPLETE":
        loop_state["consecutive_operational_warnings"] = int(loop_state.get("consecutive_operational_warnings", 0)) + 1
    else:
        loop_state["consecutive_operational_failures"] = 0 if result.get("status") in {"COMPLETE", "run_ok"} else int(loop_state.get("consecutive_operational_failures", 0))

    if result.get("promoted_to_baseline"):
        pending = loop_state.setdefault("pending_promotion_review", [])
        if isinstance(pending, list):
            pending.append(
                {
                    "run_id": result.get("run_id", ""),
                    "at": now_iso(),
                    "reason": "promoted_to_baseline_true_but_not_applied",
                }
            )

    if is_no_material_candidate_result(result):
        loop_state["consecutive_no_material_candidate"] = int(loop_state.get("consecutive_no_material_candidate", 0)) + 1
    elif result.get("accepted_for_followup") or result.get("windows_executed") or result.get("status") in {"COMPLETE", "run_ok"}:
        loop_state["consecutive_no_material_candidate"] = 0

    return loop_state


def collect_recent_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return results[-5:]


def is_no_material_candidate_result(result: Dict[str, Any]) -> bool:
    haystack = " ".join(
        str(result.get(k, ""))
        for k in (
            "status",
            "decision_type",
            "recommended_next_action",
            "main_friction",
            "branch_health",
            "error_type",
            "stdout",
            "stderr",
        )
    ).lower()
    if "blocked_no_material_candidate" in haystack or "no_material_candidate" in haystack:
        return True
    if result.get("main_friction") == "candidate_generation" and result.get("decision_type") == "rejected":
        windows = result.get("windows_executed") or []
        return not bool(windows)
    return False


def apply_candidate_generation_escape(
    repo: Path,
    config: Dict[str, Any],
    loop_state: Dict[str, Any],
    result: Dict[str, Any],
    *,
    reason: str,
    level: str,
) -> Dict[str, Any]:
    event = {
        "at": now_iso(),
        "level": level,
        "reason": reason,
        "last_run_id": result.get("run_id", ""),
        "parent_run_id": result.get("parent_run_id", ""),
        "consecutive_no_material_candidate": int(loop_state.get("consecutive_no_material_candidate", 0)),
        "next_mode": "controlled_exploration",
        "action": "force_controlled_exploration_and_research_state_escape",
    }
    loop_state["candidate_generation_escape_active"] = True
    loop_state["candidate_generation_escape_event"] = event
    loop_state["force_next_candidate_generation_mode"] = "controlled_exploration"
    loop_state["allow_one_cooldown_override"] = True
    loop_state["last_nonfatal_event"] = "candidate_generation_escape"

    event_path = repo / "state" / "candidate_generation_escape_event.json"
    save_json_atomic(event_path, event)

    research_state_path, research_state = load_research_state(repo, config)
    if isinstance(research_state, dict):
        branch = research_state.setdefault("branch_state", {})
        if isinstance(branch, dict):
            branch["current_mode"] = "controlled_exploration"
            branch["recommended_next_action"] = "controlled_exploration"
            branch["mode_reason"] = reason
            branch["escape_level"] = level
            branch["allow_one_cooldown_override"] = True
            branch["escape_event_at"] = event["at"]
            if level in {"escape", "parent_reset", "axis_reset", "diagnostic_only"}:
                branch["force_axis_reset"] = True
                branch["force_new_candidate_family"] = True
                branch["avoid_last_candidate_family"] = branch.get("last_candidate_family", "")
        parent_state = research_state.setdefault("parent_state", {})
        if isinstance(parent_state, dict) and level in {"parent_reset", "axis_reset", "diagnostic_only"}:
            parent_state["parent_exhausted_for_generation"] = True
            parent_state["parent_exhausted_at"] = event["at"]
            parent_state["parent_exhausted_reason"] = reason
        if isinstance(parent_state, dict) and level in {"parent_reset", "diagnostic_only"}:
            parent_state["previous_parent_run_id_before_escape"] = parent_state.get("current_parent_run_id", "")
            parent_state["current_parent_run_id"] = None
            parent_state["last_useful_run_id"] = None
            parent_state["parent_source"] = "current_baseline"
            parent_state["use_baseline_as_parent"] = True
            event["action"] = "reset_parent_to_baseline_clean_for_candidate_generation"
        if isinstance(branch, dict) and level in {"axis_reset", "diagnostic_only"}:
            branch["force_axis_reset"] = True
            branch["force_new_candidate_family"] = True
            branch["avoid_last_candidate_family"] = branch.get("last_candidate_family", "")
        research_state["updated_at"] = now_iso()
        save_json_atomic(research_state_path, research_state)
    return event


def recover_parent_invalid_to_baseline(repo: Path, config: Dict[str, Any], loop_state: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    event = {
        "at": now_iso(),
        "reason": "parent_invalid_fallback_to_baseline",
        "previous_parent_run_id": result.get("parent_run_id", ""),
        "parent_source": result.get("parent_source", ""),
        "action": "set_research_state_use_baseline_as_parent",
    }
    research_state_path, research_state = load_research_state(repo, config)
    if isinstance(research_state, dict):
        parent_state = research_state.setdefault("parent_state", {})
        if isinstance(parent_state, dict):
            parent_state["current_parent_run_id"] = None
            parent_state["last_useful_run_id"] = None
            parent_state["parent_source"] = "current_baseline"
            parent_state["use_baseline_as_parent"] = True
            parent_state["recovered_from_parent_invalid_at"] = event["at"]
        research_state["updated_at"] = now_iso()
        save_json_atomic(research_state_path, research_state)
    loop_state["parent_invalid_recovery_event"] = event
    loop_state["current_parent_run_id"] = "BASELINE_CLEAN"
    loop_state["selected_parent_run_id"] = "BASELINE_CLEAN"
    loop_state["selected_parent_source"] = "current_baseline"
    save_json_atomic(repo / "state" / "parent_invalid_recovery_event.json", event)
    return event


def candidate_escape_thresholds(config: Dict[str, Any]) -> Dict[str, int]:
    ce = config.get("candidate_generation_escape", {})
    if not isinstance(ce, dict):
        ce = {}
    return {
        "escape": int(ce.get("max_consecutive_no_material_before_escape", 5) or 5),
        "parent_reset": int(ce.get("max_consecutive_no_material_before_parent_reset", 10) or 10),
        "axis_reset": int(ce.get("max_consecutive_no_material_before_axis_reset", 15) or 15),
        "diagnostic_only": int(ce.get("max_consecutive_no_material_before_diagnostic_only", 25) or 25),
    }

def determine_stop_reason(config: Dict[str, Any], result: Dict[str, Any], loop_state: Dict[str, Any], baseline_changed: bool) -> Optional[str]:
    if baseline_changed and config.get("stop_on_baseline_change", True):
        return "baseline_changed"
    if result.get("promoted_to_baseline") and config.get("stop_on_promoted_to_baseline", True):
        return "pending_promotion_review"
    if result.get("recommended_next_action") == "fix_process_before_more_research" and config.get("stop_on_fix_process_before_more_research", True):
        return "fix_process_before_more_research"
    if result.get("status") == "BLOCKED_PREFLIGHT_COMPLETE":
        return None
    if result.get("status") in {"RECOVERABLE_PARTIAL_RUN", "INCOMPLETE_NO_PARENT"}:
        if not bool(config.get("stop_on_operational_failures", False)):
            return None
        if int(loop_state.get("consecutive_operational_failures", 0)) >= int(config.get("max_consecutive_operational_failures", 2)):
            return "operational_failures_threshold"
    if int(loop_state.get("consecutive_rejected_without_followup", 0)) >= int(config.get("max_consecutive_rejected_without_followup", 8)):
        loop_state["branch_exhausted_event"] = {"at": now_iso(), "reason": "too_many_rejections_without_followup", "next_mode": "controlled_exploration"}
        loop_state["force_next_candidate_generation_mode"] = "controlled_exploration"
        loop_state["consecutive_rejected_without_followup"] = 0
        return None
    if bool(config.get("stop_on_operational_warnings", False)) and int(loop_state.get("consecutive_operational_warnings", 0)) >= 3:
        return "too_many_operational_warnings"
    if result.get("error_type"):
        return result["error_type"]
    return None


def run_loop(repo: Path, config: Dict[str, Any], max_iterations: int, dry_run: bool = False) -> int:
    baseline_path = load_baseline_path(repo, config)
    baseline_hash_before = sha256_file(baseline_path) if baseline_path.exists() else ""
    runs_root = load_runs_root(repo, config)
    runs_root.mkdir(parents=True, exist_ok=True)
    logs_dir = repo / "logs" / "autonomous_loop"
    reports_dir = repo / "reports"
    state_path = repo / "state" / "autonomous_loop_state.json"
    trace_path = logs_dir / "loop_trace.jsonl"
    live_summary_path = reports_dir / "autonomous_loop_live_summary.md"
    final_summary_path = reports_dir / "autonomous_loop_final_summary.md"
    recovered_stale_runs = recover_stale_incomplete_runs(repo, runs_root, config) if not dry_run else []

    loop_state: Dict[str, Any] = {
        "loop_status": "dry_run" if dry_run else "running",
        "started_at": now_iso(),
        "updated_at": now_iso(),
        "iterations_completed": 0,
        "consecutive_rejected_without_followup": 0,
        "consecutive_operational_failures": 0,
        "consecutive_operational_warnings": 0,
        "consecutive_no_material_candidate": 0,
        "last_run_id": "",
        "last_successful_run_id": "",
        "last_useful_run_id": "",
        "current_parent_run_id": "",
        "selected_parent_run_id": "",
        "selected_parent_source": "",
        "parent_valid": False,
        "stop_reason": "",
        "pending_promotion_review": [],
        "baseline_hash_before": baseline_hash_before,
        "windows": list(config.get("windows", [])),
        "forbidden_windows": list(config.get("forbidden_windows", [])),
        "recovered_stale_runs_at_start": recovered_stale_runs,
    }
    if not dry_run:
        write_loop_state(state_path, loop_state)

    recent_results: List[Dict[str, Any]] = []
    final_payload: Dict[str, Any] = {
        "status": "PASS",
        "runs_executed": 0,
        "stop_reason": "",
        "baseline_changed": False,
        "executed_156": False,
        "incomplete_runs": [],
        "no_parent_runs": [],
        "accepted_for_followup_runs": [],
        "pending_promotion_review": [],
        "best_run_id": "",
        "worst_run_id": "",
        "recommendation": "seguir_loop",
        "recovered_stale_runs": recovered_stale_runs,
    }

    if not dry_run:
        running_payload = dict(final_payload)
        running_payload["status"] = "RUNNING"
        running_payload["stop_reason"] = "current_session_running"

        write_text_atomic(final_summary_path, render_final_summary(running_payload))
        write_text_atomic(
            live_summary_path,
            render_live_summary(
                loop_state,
                recent_results,
                {
                    "parent_run_id": "",
                    "parent_source": "",
                    "parent_valid": False,
                },
            ),
        )

    def _refresh_reports() -> None:
        if dry_run:
            return

        parent_info = recent_results[-1] if recent_results else {
            "parent_run_id": "",
            "parent_source": "",
            "parent_valid": False,
        }

        write_text_atomic(live_summary_path, render_live_summary(loop_state, recent_results, parent_info))
        save_json_atomic(state_path, loop_state)

    try:
        if dry_run:
            dry = run_one_iteration(repo, config, baseline_hash_before, dry_run=True)
            recent_results.append(dry)
            final_payload.update(
                {
                    "status": "DRY_RUN",
                    "runs_executed": 0,
                    "stop_reason": "dry_run_only",
                    "baseline_changed": False,
                    "executed_156": False,
                    "recommendation": "seguir_loop",
                }
            )
            return 0

        iterations_target = int(max_iterations)
        infinite = iterations_target == 0
        while infinite or loop_state["iterations_completed"] < iterations_target:
            result = run_one_iteration(repo, config, baseline_hash_before, dry_run=False)
            loop_state["iterations_completed"] = int(loop_state.get("iterations_completed", 0)) + 1
            loop_state["last_run_id"] = result.get("run_id", "")
            loop_state["last_run_status"] = result.get("status", "")
            loop_state["updated_at"] = now_iso()

            baseline_changed = False
            if baseline_path.exists() and baseline_hash_before:
                baseline_changed = sha256_file(baseline_path) != baseline_hash_before
            result["baseline_changed"] = baseline_changed
            result["windows_executed"] = result.get("windows_executed", [])
            recent_results.append(result)

            if result.get("error_type") == "parent_invalid":
                loop_state = update_state_after_result(repo, config, loop_state, result)
                if str(config.get("parent_invalid_policy", "fallback_to_baseline")).lower() == "fallback_to_baseline":
                    recover_parent_invalid_to_baseline(repo, config, loop_state, result)
                    final_payload["last_nonfatal_event"] = "parent_invalid_fallback_to_baseline"
                    _refresh_reports()
                    time.sleep(float(config.get("sleep_seconds_between_runs", 5)))
                    continue
                final_payload["status"] = "FAIL"
                final_payload["stop_reason"] = "parent_invalid"
                break

            should_append_exp_trace = result.get("run_id") and not (
                is_no_material_candidate_result(result) and bool(_candidate_escape_config(config).get("do_not_append_no_material_to_exp_trace", True))
            )
            if should_append_exp_trace:
                trace_payload = {
                    "timestamp": now_iso(),
                    "run_id": result.get("run_id", ""),
                    "run_dir": result.get("run_dir", ""),
                    "status": result.get("status", ""),
                    "decision_type": result.get("decision_type", ""),
                    "accepted_for_followup": bool(result.get("accepted_for_followup", False)),
                    "promoted_to_baseline": bool(result.get("promoted_to_baseline", False)),
                    "recommended_next_action": result.get("recommended_next_action", ""),
                    "recommended_change_directions": result.get("recommended_change_directions", []),
                    "overall_agent_score": result.get("overall_agent_score"),
                    "research_value": result.get("research_value"),
                    "branch_health": result.get("branch_health"),
                    "main_friction": result.get("main_friction"),
                    "parent_used": result.get("parent_run_id", ""),
                    "baseline_changed": baseline_changed,
                    "windows_executed": result.get("windows_executed", []),
                    "error_type": result.get("error_type", ""),
                }
                append_trace(trace_path, trace_payload)

            if result.get("status") == "BLOCKED_PREFLIGHT_COMPLETE":
                loop_state = update_state_after_result(repo, config, loop_state, result)
                loop_state["force_next_candidate_generation_mode"] = "controlled_exploration"
                loop_state["last_nonfatal_blocked_preflight_run_id"] = result.get("run_id", "")
                loop_state["last_nonfatal_blocked_preflight_at"] = now_iso()
                save_json_atomic(state_path, loop_state)
                final_payload["last_nonfatal_event"] = "blocked_preflight"
                _refresh_reports()
                time.sleep(float(config.get("sleep_seconds_between_runs", 5)))
                continue

            if result.get("artifacts_rc") == RC_RECOVERABLE_PARTIAL_RUN:
                result["no_parent"] = True

            if result.get("status") in {"RECOVERABLE_PARTIAL_RUN", "INCOMPLETE_NO_PARENT"}:
                result["no_parent"] = True
                no_parent_path = Path(result.get("run_dir", "")) / "recovery_status.json"
                if no_parent_path.parent.exists():
                    save_json_atomic(
                        no_parent_path,
                        {
                            "status": result.get("status", "incomplete_no_parent"),
                            "reason": "missing_required_outputs_or_partial",
                            "safe_for_strategy_analysis": False,
                            "safe_for_process_analysis": True,
                            "do_not_use_as_parent": True,
                            "updated_at": now_iso(),
                        },
                    )

            if result.get("coordinator_validation_rc") not in {None, 0}:
                result["error_type"] = "coordinator_validation_failed"
                result["status"] = "RECOVERABLE_PARTIAL_RUN"
                result["no_parent"] = True
                loop_state = update_state_after_result(repo, config, loop_state, result)
                if str(config.get("coordinator_output_invalid_policy", "recoverable")).lower() == "recoverable":
                    final_payload["last_nonfatal_event"] = "coordinator_output_invalid_recovered"
                    _refresh_reports()
                    time.sleep(float(config.get("sleep_seconds_between_runs", 5)))
                    continue
                final_payload["status"] = "FAIL"
                final_payload["stop_reason"] = "coordinator_output_invalid"
                break

            if result.get("promoted_to_baseline"):
                pending_path = Path(result.get("run_dir", "")) / "pending_promotion_review.json"
                if pending_path.parent.exists():
                    save_json_atomic(
                        pending_path,
                        {
                            "run_id": result.get("run_id", ""),
                            "at": now_iso(),
                            "reason": "promoted_to_baseline_true_but_not_applied_non_blocking",
                            "note": "Promotion candidate recorded; loop continues unless apply-baseline-promotion is explicit.",
                        },
                    )
                final_payload["pending_promotion_review"] = list(loop_state.get("pending_promotion_review", []))
                final_payload["last_nonfatal_event"] = "pending_promotion_review"

            if result.get("recommended_next_action") == "fix_process_before_more_research":
                loop_state = update_state_after_result(repo, config, loop_state, result)
                if bool(config.get("stop_on_fix_process_before_more_research", False)):
                    final_payload["status"] = "STOPPED_FOR_REVIEW"
                    final_payload["stop_reason"] = "fix_process_before_more_research"
                    break
                apply_candidate_generation_escape(
                    repo,
                    config,
                    loop_state,
                    result,
                    reason="fix_process_before_more_research_non_blocking",
                    level="process_recovery",
                )
                final_payload["last_nonfatal_event"] = "fix_process_before_more_research_non_blocking"
                _refresh_reports()
                time.sleep(float(config.get("sleep_seconds_between_runs", 5)))
                continue

            if result.get("status") in {"RECOVERABLE_PARTIAL_RUN", "INCOMPLETE_NO_PARENT"}:
                loop_state = update_state_after_result(repo, config, loop_state, result)
                final_payload["last_nonfatal_event"] = "incomplete_run_recovered"
                if bool(config.get("stop_on_operational_failures", False)) and int(loop_state.get("consecutive_operational_failures", 0)) >= int(config.get("max_consecutive_operational_failures", 2)):
                    final_payload["status"] = "FAIL"
                    final_payload["stop_reason"] = "operational_failures_threshold"
                    break
                _refresh_reports()
                time.sleep(float(config.get("sleep_seconds_between_runs", 5)))
                continue
            else:
                loop_state = update_state_after_result(repo, config, loop_state, result)

            if result.get("baseline_changed"):
                if bool(config.get("stop_on_baseline_change", False)):
                    final_payload["status"] = "FAIL"
                    final_payload["stop_reason"] = "baseline_changed"
                    break
                final_payload["last_nonfatal_event"] = "baseline_changed_non_blocking"

            if is_forbidden_156_present(Path(result.get("run_dir", ""))):
                final_payload["status"] = "FAIL"
                final_payload["stop_reason"] = "forbidden_window_156_detected"
                result["error_type"] = "forbidden_window_156_detected"
                break

            if is_no_material_candidate_result(result):
                ce_cfg = _candidate_escape_config(config)
                no_mat = int(loop_state.get("consecutive_no_material_candidate", 0))
                escape_level_for_quarantine = ""

                if bool(ce_cfg.get("enabled", True)):
                    thresholds = candidate_escape_thresholds(config)
                    if no_mat >= thresholds["diagnostic_only"]:
                        escape_level_for_quarantine = "diagnostic_only"
                    elif no_mat == thresholds["axis_reset"]:
                        escape_level_for_quarantine = "axis_reset"
                    elif no_mat >= thresholds["parent_reset"]:
                        escape_level_for_quarantine = "escape"
                    elif no_mat == thresholds["escape"]:
                        escape_level_for_quarantine = "escape"

                if bool(ce_cfg.get("quarantine_no_material_runs", True)):
                    _quarantine_no_material_candidate_run(repo, config, result, loop_state, escape_level=escape_level_for_quarantine)

                if bool(ce_cfg.get("enabled", True)):
                    thresholds = candidate_escape_thresholds(config)
                    if no_mat >= thresholds["parent_reset"]:
                        apply_candidate_generation_escape(
                            repo,
                            config,
                            loop_state,
                            result,
                            reason="candidate_generation_exhausted_needs_review",
                            level="escape",
                        )
                        write_candidate_generation_diagnostic(
                            repo,
                            config,
                            loop_state,
                            result,
                            recent_results,
                            reason="candidate_generation_exhausted_needs_review",
                            final=True,
                        )
                        final_payload["status"] = "STOPPED_FOR_REVIEW"
                        final_payload["stop_reason"] = "candidate_generation_exhausted_needs_review"
                        final_payload["recommendation"] = "stop_branch"
                        final_payload["last_nonfatal_event"] = "candidate_generation_exhausted_needs_review"
                        _refresh_reports()
                        break
                    elif no_mat >= thresholds["escape"]:
                        apply_candidate_generation_escape(
                            repo,
                            config,
                            loop_state,
                            result,
                            reason="candidate_generation_forced_orthogonal_after_no_material_streak",
                            level="escape",
                        )
                        write_candidate_generation_diagnostic(
                            repo,
                            config,
                            loop_state,
                            result,
                            recent_results,
                            reason="candidate_generation_forced_orthogonal_after_no_material_streak",
                            final=False,
                        )
                        _refresh_reports()
                        time.sleep(float(config.get("sleep_seconds_between_runs", 5)))
                        continue
                    elif no_mat == thresholds["axis_reset"]:
                        apply_candidate_generation_escape(repo, config, loop_state, result, reason="too_many_no_material_candidate_axis_reset", level="axis_reset")
                        write_candidate_generation_diagnostic(repo, config, loop_state, result, recent_results, reason="candidate_generation_axis_reset", final=False)
                        _refresh_reports()
                        time.sleep(float(config.get("sleep_seconds_between_runs", 5)))
                        continue
                    elif no_mat == thresholds["parent_reset"]:
                        apply_candidate_generation_escape(repo, config, loop_state, result, reason="too_many_no_material_candidate_parent_reset", level="parent_reset")
                        write_candidate_generation_diagnostic(repo, config, loop_state, result, recent_results, reason="candidate_generation_parent_reset", final=False)
                        _refresh_reports()
                        time.sleep(float(config.get("sleep_seconds_between_runs", 5)))
                        continue
                    elif no_mat == thresholds["escape"]:
                        apply_candidate_generation_escape(repo, config, loop_state, result, reason="too_many_no_material_candidate_escape", level="escape")
                        write_candidate_generation_diagnostic(repo, config, loop_state, result, recent_results, reason="candidate_generation_escape", final=False)
                        _refresh_reports()
                        time.sleep(float(config.get("sleep_seconds_between_runs", 5)))
                        continue

            if int(loop_state.get("consecutive_rejected_without_followup", 0)) >= int(config.get("max_consecutive_rejected_without_followup", 8)):
                branch_event = {
                    "at": now_iso(),
                    "last_run_id": result.get("run_id", ""),
                    "reason": "too_many_rejections_without_followup",
                    "next_mode": "controlled_exploration",
                }
                loop_state["branch_exhausted_event"] = branch_event
                loop_state["force_next_candidate_generation_mode"] = "controlled_exploration"
                loop_state["consecutive_rejected_without_followup"] = 0
                save_json_atomic(state_path, loop_state)
                event_path = repo / "state" / "branch_exhausted_event.json"
                save_json_atomic(event_path, branch_event)
                final_payload["last_nonfatal_event"] = "too_many_rejections_without_followup"
                _refresh_reports()
                time.sleep(float(config.get("sleep_seconds_between_runs", 5)))
                continue

            if int(loop_state.get("consecutive_operational_warnings", 0)) >= 3:
                if bool(config.get("stop_on_operational_warnings", False)):
                    final_payload["status"] = "STOPPED_FOR_REVIEW"
                    final_payload["stop_reason"] = "too_many_operational_warnings"
                    break
                loop_state["last_nonfatal_event"] = "operational_warnings_recovered"
                loop_state["consecutive_operational_warnings"] = 0
                _refresh_reports()
                time.sleep(float(config.get("sleep_seconds_between_runs", 5)))
                continue

            final_payload["runs_executed"] = int(loop_state.get("iterations_completed", 0))
            final_payload["baseline_changed"] = baseline_changed
            final_payload["executed_156"] = False
            if result.get("accepted_for_followup"):
                final_payload["accepted_for_followup_runs"].append(result.get("run_id", ""))
            if result.get("status") in {"RECOVERABLE_PARTIAL_RUN", "INCOMPLETE_NO_PARENT"}:
                final_payload["incomplete_runs"].append(result.get("run_id", ""))
                final_payload["no_parent_runs"].append(result.get("run_id", ""))
            if result.get("status") == "BLOCKED_PREFLIGHT_COMPLETE":
                final_payload["last_nonfatal_event"] = "blocked_preflight"
                _refresh_reports()
                time.sleep(float(config.get("sleep_seconds_between_runs", 5)))
                continue

            _refresh_reports()
            time.sleep(float(config.get("sleep_seconds_between_runs", 5)))

        if final_payload["status"] == "PASS":
            final_payload["runs_executed"] = int(loop_state.get("iterations_completed", 0))
            final_payload["baseline_changed"] = baseline_hash_before and baseline_path.exists() and sha256_file(baseline_path) != baseline_hash_before
            final_payload["executed_156"] = any(156 in (r.get("windows_executed", []) or []) for r in recent_results)
            final_payload["accepted_for_followup_runs"] = [r.get("run_id", "") for r in recent_results if r.get("accepted_for_followup")]
            final_payload["pending_promotion_review"] = list(loop_state.get("pending_promotion_review", []))
            run_error_runs = [r.get("run_id", "") for r in recent_results if r.get("status") == "run_error"]
            warning_runs = [
                r.get("run_id", "")
                for r in recent_results
                if r.get("status") in {"run_partial_valid", "insufficient_depth", "short_window_no_trades"}
            ]
            if run_error_runs:
                final_payload["status"] = "FAIL"
                final_payload["stop_reason"] = final_payload.get("stop_reason", "") or "run_error_detected"
                final_payload["recommendation"] = "fix_process_before_more_research"
            elif warning_runs:
                final_payload["status"] = "PASS_WITH_WARNINGS"
                final_payload["stop_reason"] = final_payload.get("stop_reason", "") or "warnings_present"
                final_payload["recommendation"] = "seguir_loop"
            if final_payload["status"] == "PASS":
                scored = [r for r in recent_results if r.get("run_id")]
                if scored:
                    best = max(scored, key=lambda r: float(r.get("overall_agent_score") or -1e9))
                    worst = min(scored, key=lambda r: float(r.get("overall_agent_score") if r.get("overall_agent_score") is not None else 1e9))
                    final_payload["best_run_id"] = best.get("run_id", "")
                    final_payload["worst_run_id"] = worst.get("run_id", "")
                final_payload["recommendation"] = "seguir_loop" if not final_payload["pending_promotion_review"] else "review_pending_promotion"

    except KeyboardInterrupt:
        loop_state["loop_status"] = "stopped"
        loop_state["stop_reason"] = "keyboard_interrupt"
        final_payload["status"] = "STOPPED_FOR_REVIEW"
        final_payload["stop_reason"] = "keyboard_interrupt"
    except Exception as e:
        loop_state["loop_status"] = "failed"
        loop_state["stop_reason"] = f"exception:{e}"
        final_payload["status"] = "FAIL"
        final_payload["stop_reason"] = f"exception:{e}"
        final_payload["error"] = str(e)
    finally:
        if not dry_run:
            final_payload["runs_executed"] = int(loop_state.get("iterations_completed", 0))
            final_payload["baseline_changed"] = bool(baseline_path.exists() and baseline_hash_before and sha256_file(baseline_path) != baseline_hash_before)
            final_payload["executed_156"] = any(156 in (r.get("windows_executed", []) or []) for r in recent_results)
            if not final_payload.get("best_run_id") and recent_results:
                scored = [r for r in recent_results if r.get("run_id")]
                if scored:
                    best = max(scored, key=lambda r: float(r.get("overall_agent_score") or -1e9))
                    worst = min(scored, key=lambda r: float(r.get("overall_agent_score") if r.get("overall_agent_score") is not None else 1e9))
                    final_payload["best_run_id"] = best.get("run_id", "")
                    final_payload["worst_run_id"] = worst.get("run_id", "")
            if not final_payload.get("accepted_for_followup_runs"):
                final_payload["accepted_for_followup_runs"] = [r.get("run_id", "") for r in recent_results if r.get("accepted_for_followup")]
            if not final_payload.get("pending_promotion_review"):
                final_payload["pending_promotion_review"] = list(loop_state.get("pending_promotion_review", []))
            stop_reason = rmi.clean_text(final_payload.get("stop_reason", ""))
            if final_payload["status"] == "STOPPED_FOR_REVIEW":
                if stop_reason == "pending_promotion_review":
                    final_payload["recommendation"] = "review_pending_promotion"
                elif stop_reason in {"fix_process_before_more_research", "blocked_preflight", "coordinator_output_invalid"}:
                    final_payload["recommendation"] = "fix_process_before_more_research"
                elif stop_reason == "candidate_generation_exhausted_needs_review":
                    final_payload["recommendation"] = "stop_branch"
                elif stop_reason == "too_many_rejections_without_followup":
                    final_payload["recommendation"] = "stop_branch"
                elif stop_reason == "too_many_operational_warnings":
                    final_payload["recommendation"] = "fix_process_before_more_research"
                else:
                    final_payload["recommendation"] = "auditar_batch_con_humano"
            elif final_payload["status"] == "FAIL":
                final_payload["recommendation"] = "fix_process_before_more_research"
            else:
                final_payload["recommendation"] = "seguir_loop"
            if final_payload["status"] == "PASS":
                loop_state["loop_status"] = "completed"
            elif final_payload["status"] == "PASS_WITH_WARNINGS":
                loop_state["loop_status"] = "completed_with_warnings"
            elif final_payload["status"] == "FAIL":
                loop_state["loop_status"] = "stopped_for_fail"
            elif final_payload["status"] == "STOPPED_FOR_REVIEW":
                loop_state["loop_status"] = "stopped_for_review"
            elif final_payload["status"] == "DRY_RUN":
                loop_state["loop_status"] = "dry_run_completed"

            loop_state["stop_reason"] = final_payload.get("stop_reason", "")
            loop_state["updated_at"] = now_iso()

            parent_info = recent_results[-1] if recent_results else {
                "parent_run_id": "",
                "parent_source": "",
                "parent_valid": False,
            }

            save_json_atomic(state_path, loop_state)
            write_text_atomic(live_summary_path, render_live_summary(loop_state, recent_results, parent_info))
            write_text_atomic(final_summary_path, render_final_summary(final_payload))
        return 0 if final_payload["status"] in {"PASS", "PASS_WITH_WARNINGS", "STOPPED_FOR_REVIEW", "DRY_RUN"} else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Run an autonomous controlled research loop with strict window safety.")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--config", default="")
    ap.add_argument("--windows", default="")
    ap.add_argument("--max-iterations", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    config_path = Path(args.config).resolve() if args.config else None
    config = load_config(repo, config_path=config_path)
    effective_windows = effective_windows_from_args(args, config)
    if args.max_iterations is not None:
        config["max_iterations"] = int(args.max_iterations)
    if not config.get("strict_windows", True):
        config["strict_windows"] = True
    if 156 in effective_windows:
        print("ERROR: 156 is forbidden in this supervisor.", file=sys.stderr)
        return 2

    preflight = preflight_supervisor_state(repo, config)
    if preflight.get("rejected_startup_parent_run_id"):
        print(
            "STARTUP_PARENT "
            f"rejected_startup_parent_run_id={preflight.get('rejected_startup_parent_run_id', '')} "
            f"rejected_startup_parent_reason={preflight.get('rejected_startup_parent_reason', '')} "
            f"selected_parent_run_id={preflight.get('selected_parent_run_id', '')} "
            f"selected_parent_source={preflight.get('parent_source', '')}",
            flush=True,
        )
    if not preflight["parent_valid"]:
        print(
            "ERROR: parent_valid=false; refusing to start supervisor before any run.",
            file=sys.stderr,
        )
        return 2
    if preflight["selected_parent_run_id"] and not preflight["parent_valid"]:
        print(
            "ERROR: selected_parent_run_id is present while parent_valid=false.",
            file=sys.stderr,
        )
        return 2
    if 156 in preflight["effective_windows"]:
        print("ERROR: effective_windows contains forbidden 156.", file=sys.stderr)
        return 2

    baseline_path = load_baseline_path(repo, config)
    if not baseline_path.exists():
        print(f"ERROR: baseline not found: {baseline_path}", file=sys.stderr)
        return 2

    lock_rel = str(config.get("single_instance_lock_path", "state/autonomous_loop.lock"))
    lock_path = (repo / lock_rel).resolve()
    with single_instance_lock(
        lock_path,
        enabled=bool(config.get("single_instance_lock_enabled", True)) and not bool(args.dry_run),
        stale_after_seconds=int(config.get("single_instance_lock_stale_seconds", 28800) or 28800),
        retries=1,
        delay_seconds=1.0,
    ):
        return run_loop(repo, config, int(config.get("max_iterations", 0)), dry_run=bool(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
