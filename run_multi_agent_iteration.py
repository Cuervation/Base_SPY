#!/usr/bin/env python3
from __future__ import annotations

import atexit
import argparse
import csv
from collections import Counter
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scripts.safe_io import safe_append_csv_row, safe_json_write

_AUDIT_RECENT_ROWS: List[Dict[str, str]] = []
RESEARCH_MODES: set[str] = {
    "refine_current_branch",
    "controlled_exploration",
    "extend_validation",
    "fix_process_before_more_research",
    "champion_hold",
    "safe_recovery_mode",
}


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def save_json(path: Path, obj: Any) -> None:
    safe_json_write(path, obj, retries=12, delay_seconds=0.25)


def save_json_atomic(path: Path, obj: Any) -> None:
    safe_json_write(path, obj, retries=12, delay_seconds=0.25)


def load_paths_config(repo: Path) -> Dict[str, Any]:
    """
    Minimal path compatibility layer for the reorganized repo.
    - Prefer config/paths_config.json when present.
    - Fall back to legacy root-relative paths when missing.
    """
    cfg_path = (repo / "config" / "paths_config.json").resolve()
    data = load_json(cfg_path, {})
    return data if isinstance(data, dict) else {}


def cfg_get_str(cfg: Dict[str, Any], keys: List[str], default: str) -> str:
    cur: Any = cfg
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if isinstance(cur, str) and cur.strip() else default



def cfg_bool(value: Any, default: bool = False) -> bool:
    """Parse bool-ish config values without raising."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if not s:
        return default
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def write_window_execution_plan(path: Path, plan: Dict[str, Any]) -> None:
    # Keep plan always writable (auditable) even if the run aborts early.
    try:
        save_json_atomic(path, plan)
    except Exception:
        pass


def parse_parent_context_from_run_log(log_path: Path) -> Tuple[str, str]:
    parent_run_id = ""
    parent_script = ""
    if not log_path.exists():
        return parent_run_id, parent_script
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return parent_run_id, parent_script
    for line in reversed(lines):
        if "CONTEXT " not in line:
            continue
        m_run = re.search(r"parent_run_id=([^\s]+)", line)
        m_script = re.search(r"parent_script=([^\s]+)", line)
        if m_run:
            parent_run_id = clean_text(m_run.group(1))
        if m_script:
            parent_script = clean_text(m_script.group(1))
        if parent_run_id or parent_script:
            break
    return parent_run_id, parent_script


def find_candidate_script_in_run_dir(run_dir: Path, run_id: str) -> str:
    try:
        py_files = [p for p in run_dir.glob("*.py") if p.is_file()]
        if not py_files:
            return ""
        tagged = [p for p in py_files if f"_{run_id}" in p.stem or p.stem.endswith(run_id)]
        target = tagged if tagged else py_files
        target = sorted(target, key=lambda p: p.stat().st_mtime, reverse=True)
        return str(target[0])
    except Exception:
        return ""


def generated_script_path(directory: Path, base_stem: str, suffix: str, max_stem_len: int = 96) -> Path:
    clean_base = re.sub(r"[^A-Za-z0-9_.-]+", "_", clean_text(base_stem)).strip("._-")
    clean_suffix = re.sub(r"[^A-Za-z0-9_.-]+", "_", clean_text(suffix)).strip("._-")
    if not clean_suffix:
        clean_suffix = "candidate"
    stem = f"{clean_base}_{clean_suffix}" if clean_base else clean_suffix
    if len(stem) > max_stem_len:
        keep = max(1, max_stem_len - len(clean_suffix) - 1)
        clean_base = clean_base[:keep].rstrip("._-")
        stem = f"{clean_base}_{clean_suffix}" if clean_base else clean_suffix[-max_stem_len:]
    return directory / f"{stem}.py"


def build_executor_output_from_partial(
    *,
    run_dir: Path,
    run_id: str,
    requested_windows: List[int],
    allowed_windows: List[int],
    progressive_windows: List[int],
    reason: str,
) -> Optional[Dict[str, Any]]:
    partial = load_json(run_dir / "executor_output.partial.json", {})
    if not isinstance(partial, dict):
        return None
    raw_windows = partial.get("windows", {})
    if not isinstance(raw_windows, dict) or not raw_windows:
        return None

    windows_results: Dict[str, Any] = {}
    executed_windows: List[int] = []
    exec_errors: List[str] = []
    clean_reason = clean_text(reason)
    if clean_reason:
        exec_errors.append(clean_reason)

    for wk_raw, payload_raw in raw_windows.items():
        try:
            wk = int(wk_raw)
        except Exception:
            continue
        payload = payload_raw if isinstance(payload_raw, dict) else {}
        status = clean_text(payload.get("status", ""))
        if status not in {"run_ok", "insufficient_depth", "run_error", "blocked_window_not_allowed"}:
            status = "run_partial_valid"
        metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics"), dict) else {}
        actual_weeks = to_float(metrics.get("weeks_run"))
        actual_weeks_int: Optional[int] = int(round(actual_weeks)) if actual_weeks is not None else None
        depth_ok = bool(status == "run_ok")
        if actual_weeks_int is not None and actual_weeks_int < int(wk):
            depth_ok = False
            if status == "run_ok":
                status = "insufficient_depth"
        window_payload = {
            "status": status,
            "window": int(wk),
            "requested_weeks": int(wk),
            "actual_weeks_run": actual_weeks_int,
            "depth_ok": depth_ok,
            "test_start_used": "",
            "command": "",
            "stdout_log": str(run_dir / f"window_{int(wk):02d}" / "stdout.log"),
            "stderr_log": str(run_dir / f"window_{int(wk):02d}" / "stderr.log"),
            "outputs": {
                "excel": "",
                "txt": "",
                "artifacts_dir": str(run_dir / f"window_{int(wk):02d}"),
                "csv": {},
            },
            "metrics": metrics,
            "errors": [clean_reason] if clean_reason else [],
            "execution_mode": "recovered_from_executor_partial",
        }
        windows_results[str(int(wk))] = window_payload
        executed_windows.append(int(wk))

    if not windows_results:
        return None

    executor_status = classify_executor_run_status(windows_results, exec_errors)
    if any("blocked_window_not_allowed" in clean_text(e) for e in exec_errors):
        executor_status = "blocked_window_not_allowed"
    core_window = "52" if "52" in windows_results else (str(max(executed_windows)) if executed_windows else "52")
    core_metrics = (windows_results.get(core_window, {}) or {}).get("metrics", {})
    depth_summary = build_validation_depth_summary(
        windows_results=windows_results,
        requested_windows=requested_windows,
        progressive_windows=progressive_windows,
    )
    return {
        "role": "executor",
        "status": executor_status,
        "run_id": run_id,
        "script_executed": find_candidate_script_in_run_dir(run_dir, run_id),
        "command": "",
        "windows_policy": {
            "requested": [int(w) for w in requested_windows],
            "allowed": [int(w) for w in allowed_windows],
            "progressive_plan": [int(w) for w in progressive_windows],
            "policy": "recovered_from_partial_on_abort",
            "strict_progressive_windows": True,
        },
        "windows": windows_results,
        "core_metrics": core_metrics,
        "validation_depth_summary": depth_summary,
        "errors": exec_errors,
        "recovery": {
            "recovered": True,
            "source": "executor_output.partial.json",
            "at": datetime.now().isoformat(timespec="seconds"),
        },
    }


def ensure_controlled_abort_artifacts(
    *,
    run_dir: Path,
    run_id: str,
    requested_windows: List[int],
    allowed_windows: List[int],
    progressive_windows: List[int],
    reason: str,
    status_hint: str = "run_error",
) -> None:
    executor_path = run_dir / "executor_output.json"
    coordinator_path = run_dir / "coordinator_output.json"
    manifest_path = run_dir / "experiment_manifest.json"
    partial_path = run_dir / "executor_output.partial.json"
    run_status_path = run_dir / "run_status.json"

    plan = load_json(run_dir / "window_execution_plan.json", {})
    if isinstance(plan, dict):
        if not requested_windows:
            requested_windows = [int(w) for w in (plan.get("requested_windows") or []) if str(w).strip()]
        if not allowed_windows:
            allowed_windows = [int(w) for w in (plan.get("allowed_windows") or []) if str(w).strip()]
        if not progressive_windows:
            progressive_windows = [int(w) for w in (plan.get("allowed_windows") or []) if str(w).strip()]

    if not progressive_windows:
        progressive_windows = list(allowed_windows) if allowed_windows else list(requested_windows)

    existing_run_status = load_json(run_status_path, {})
    existing_manifest = load_json(manifest_path, {})
    blocked_preflight_complete = False
    if isinstance(existing_run_status, dict) and clean_text(existing_run_status.get("status", "")) == "blocked_preflight":
        blocked_preflight_complete = True
    if isinstance(existing_manifest, dict) and clean_text(existing_manifest.get("status", "")) == "blocked_preflight":
        blocked_preflight_complete = True

    if blocked_preflight_complete:
        recovery_status = {
            "status": "blocked_preflight_complete",
            "reason": clean_text(reason) or clean_text(existing_run_status.get("reason", "")) or "preflight_blocked",
            "safe_for_strategy_analysis": False,
            "safe_for_process_analysis": True,
            "do_not_use_as_parent": True,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            save_json_atomic(run_dir / "recovery_status.json", recovery_status)
        except Exception:
            pass
        try:
            if not run_status_path.exists():
                save_json_atomic(
                    run_status_path,
                    {
                        "status": "blocked_preflight",
                        "reason": recovery_status["reason"],
                        "completed_windows": [],
                        "missing_artifacts": [],
                        "finalized": True,
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                    },
                )
        except Exception:
            pass
        return

    if (not executor_path.exists()) and partial_path.exists():
        synthesized = build_executor_output_from_partial(
            run_dir=run_dir,
            run_id=run_id,
            requested_windows=requested_windows,
            allowed_windows=allowed_windows,
            progressive_windows=progressive_windows,
            reason=reason,
        )
        if isinstance(synthesized, dict):
            save_json_atomic(executor_path, synthesized)

    executor_output = load_json(executor_path, {})
    executor_status = clean_text(executor_output.get("status", "")) if isinstance(executor_output, dict) else ""
    if not executor_status:
        executor_status = clean_text(status_hint) or "run_error"

    if not manifest_path.exists():
        parent_run_id, parent_script = parse_parent_context_from_run_log(run_dir / "run_live_status.log")
        manifest = {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "parent_run_id": parent_run_id,
            "parent_script": parent_script,
            "status": executor_status,
            "decision_type": "rejected",
            "accepted_for_followup": False,
            "promoted_to_baseline": False,
            "gate_decision": "incomplete_run",
            "coordinator_pending": not coordinator_path.exists(),
            "incomplete_run": True,
            "incomplete_reason": clean_text(reason) or "controlled_abort_before_finalization",
            "compare_windows": [int(w) for w in requested_windows] if requested_windows else [],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        save_json_atomic(manifest_path, manifest)

    missing_required = []
    for fname in ["executor_output.json", "coordinator_output.json", "experiment_manifest.json"]:
        if not (run_dir / fname).exists():
            missing_required.append(fname)

    completed_windows: List[int] = []
    partial_obj = load_json(partial_path, {})
    if isinstance(partial_obj, dict):
        for x in (partial_obj.get("executed_windows") or []):
            try:
                completed_windows.append(int(x))
            except Exception:
                continue
    completed_windows = sorted(list(dict.fromkeys(completed_windows)))

    if missing_required:
        recovery_status = {
            "status": "incomplete_no_parent",
            "reason": clean_text(reason) or "missing_final_artifacts",
            "safe_for_strategy_analysis": False,
            "safe_for_process_analysis": True,
            "do_not_use_as_parent": True,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            save_json_atomic(run_dir / "recovery_status.json", recovery_status)
        except Exception:
            pass

    run_status = {
        "status": executor_status,
        "reason": clean_text(reason) or ("missing_required_outputs" if missing_required else "completed"),
        "completed_windows": completed_windows,
        "missing_artifacts": missing_required,
        "finalized": not bool(missing_required),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_json_atomic(run_dir / "run_status.json", run_status)


def to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and math.isnan(v):
            return None
        return float(v)
    s = str(v).strip().replace(",", ".")
    if not s:
        return None
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return float(s)
    return None


def csv_num(v: Any) -> str:
    n = to_float(v)
    if n is None:
        return ""
    return f"{n:.12g}".replace(".", ",")


def clean_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v).replace(";", ",").replace("\r", " ").replace("\n", " ").strip()


def truthy_flag(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return clean_text(v).lower() in {"1", "true", "yes", "y", "si", "sí"}


def research_state_requests_baseline_parent(research_state: Dict[str, Any]) -> bool:
    if not isinstance(research_state, dict):
        return False
    p_st = research_state.get("parent_state", {}) if isinstance(research_state.get("parent_state"), dict) else {}
    return truthy_flag(research_state.get("use_baseline_as_parent")) or truthy_flag(
        p_st.get("use_baseline_as_parent")
    )


def maybe_fix_mojibake(v: Any) -> str:
    s = clean_text(v)
    if not s:
        return s
    if "Ã" in s or "Â" in s or "â" in s:
        try:
            fixed = s.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
            if fixed:
                s = fixed
        except Exception:
            pass
    return s


def sanitize_text_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    out: List[str] = []
    for x in values:
        sx = maybe_fix_mojibake(x)
        if sx:
            out.append(sx)
    return out


def normalize_research_mode(value: Any, fallback: str = "refine_current_branch") -> str:
    v = clean_text(value)
    if v in RESEARCH_MODES:
        return v
    return fallback if fallback in RESEARCH_MODES else "refine_current_branch"


def map_recommended_action_to_mode(action: Any) -> str:
    a = clean_text(action)
    if a in RESEARCH_MODES:
        return a
    if a == "extend_validation":
        return "extend_validation"
    if a == "controlled_exploration":
        return "controlled_exploration"
    if a == "fix_process_before_more_research":
        return "fix_process_before_more_research"
    return "refine_current_branch"


def mode_to_analyst_style(current_mode: str) -> str:
    m = normalize_research_mode(current_mode)
    if m in {"controlled_exploration"}:
        return "explore"
    if m in {"safe_recovery_mode", "fix_process_before_more_research"}:
        return "recovery"
    if m in {"extend_validation", "champion_hold"}:
        return "validation"
    return "exploit"


def recent_acceptance_rate(rows: List[Dict[str, str]], lookback: int = 15) -> float:
    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = sorted_rows[-max(1, int(lookback)) :] if sorted_rows else []
    if not recent:
        return 0.0
    accepted = sum(1 for r in recent if clean_text(r.get("accepted_or_rejected", "")).lower() == "accepted")
    return float(accepted) / float(len(recent))


def count_recent_status(rows: List[Dict[str, str]], statuses: set[str], lookback: int = 10) -> int:
    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = sorted_rows[-max(1, int(lookback)) :] if sorted_rows else []
    target = {clean_text(s) for s in statuses}
    return sum(1 for r in recent if clean_text(r.get("status", "")) in target)


def count_consecutive_status_from_end(rows: List[Dict[str, str]], statuses: set[str]) -> int:
    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    target = {clean_text(s) for s in statuses}
    streak = 0
    for row in reversed(sorted_rows):
        if clean_text(row.get("status", "")) in target:
            streak += 1
            continue
        break
    return streak


def count_recent_useful_runs(rows: List[Dict[str, str]], lookback: int = 12) -> int:
    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = sorted_rows[-max(1, int(lookback)) :] if sorted_rows else []
    return sum(1 for r in recent if clean_text(r.get("accepted_or_rejected", "")).lower() == "accepted")


def count_recent_exhausted_subspaces(rows: List[Dict[str, str]], lookback: int = 15) -> int:
    exhausted = detect_recent_exhausted_subspaces(
        rows=rows,
        parent_run_id="",
        lookback=max(5, int(lookback)),
        min_repeats=3,
        min_reject_ratio=0.75,
    )
    return len(exhausted)


def estimate_parent_obvious_exhaustion(rows: List[Dict[str, str]], lookback: int = 12) -> bool:
    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = sorted_rows[-max(1, int(lookback)) :] if sorted_rows else []
    if len(recent) < 4:
        return False
    parent_counts: Dict[str, int] = {}
    parent_accepted: Dict[str, int] = {}
    parent_params: Dict[str, set[str]] = {}
    for r in recent:
        p = clean_text(r.get("parent_run_id", ""))
        if not p:
            continue
        parent_counts[p] = int(parent_counts.get(p, 0)) + 1
        if clean_text(r.get("accepted_or_rejected", "")).lower() == "accepted":
            parent_accepted[p] = int(parent_accepted.get(p, 0)) + 1
        mp = clean_text(r.get("main_parameter", ""))
        if p not in parent_params:
            parent_params[p] = set()
        if mp:
            parent_params[p].add(mp)
    for p, n in parent_counts.items():
        if n < 4:
            continue
        acc = int(parent_accepted.get(p, 0))
        acc_ratio = (float(acc) / float(n)) if n > 0 else 0.0
        touched = len(parent_params.get(p, set()))
        if acc_ratio <= 0.25 and touched <= 2:
            return True
    return False


def get_recent_changed_parameters(rows: List[Dict[str, str]], lookback: int = 8) -> List[str]:
    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = sorted_rows[-max(1, int(lookback)) :] if sorted_rows else []
    out: List[str] = []
    for r in recent:
        p = clean_text(r.get("main_parameter", ""))
        if p:
            out.append(p)
    return out


def get_recent_useful_main_parameter(rows: List[Dict[str, str]], lookback: int = 12) -> str:
    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = list(reversed(sorted_rows[-max(1, int(lookback)) :])) if sorted_rows else []
    for r in recent:
        if clean_text(r.get("accepted_or_rejected", "")).lower() != "accepted":
            continue
        p = clean_text(r.get("main_parameter", ""))
        if p:
            return p
    return ""


def load_watchdog_health_state(repo: Path) -> Dict[str, Any]:
    cfg = load_paths_config(repo)
    watchdog_dir = cfg_get_str(
        cfg, ["logs", "watchdog"], "logs/watchdog/multi_agent_watchdog_logs"
    )
    state_path = (repo / watchdog_dir / "watchdog_health_state.json").resolve()
    data = load_json(state_path, {})
    return data if isinstance(data, dict) else {}


def watchdog_indicates_safe_recovery(watchdog_state: Dict[str, Any]) -> bool:
    if not isinstance(watchdog_state, dict) or not watchdog_state:
        return False
    if bool(watchdog_state.get("safe_mode_active", False)):
        return True
    if bool(watchdog_state.get("hard_stuck_detected", False)):
        return True
    restart_count = int(to_float(watchdog_state.get("restart_count_last_24h")) or 0)
    if restart_count >= 3:
        return True
    last_reason = clean_text(
        watchdog_state.get("last_restart_reason", watchdog_state.get("last_reason", ""))
    ).lower()
    if last_reason in {"hard_stuck", "loop_down", "stale_no_python_workers"}:
        return True
    return False


def normalize_scalar(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and math.isnan(v):
            return ""
        return f"{float(v):.12g}"
    s = str(v).strip()
    if not s:
        return ""
    if re.fullmatch(r"(?i:true|false)", s):
        return s.lower()
    n = to_float(s)
    if n is not None:
        return f"{n:.12g}"
    return s


def os_cpu_count() -> int:
    return int(os.cpu_count() or 2)


def strip_py_inline_comment(rhs: str) -> str:
    out = []
    in_single = False
    in_double = False
    escaped = False
    for ch in rhs:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if (in_single or in_double) and ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if not in_double and ch == "'":
            in_single = not in_single
            out.append(ch)
            continue
        if not in_single and ch == '"':
            in_double = not in_double
            out.append(ch)
            continue
        if not in_single and not in_double and ch == "#":
            break
        out.append(ch)
    return "".join(out).strip()


def get_py_const_literal(text: str, name: str) -> Optional[str]:
    m = re.search(rf"(?m)^{re.escape(name)}\s*=\s*(.+?)\s*$", text)
    if not m:
        return None
    return strip_py_inline_comment(m.group(1)).strip()


def to_py_literal(v: Any) -> str:
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, (int, float)):
        return f"{float(v):.12g}"
    if v is None:
        return "None"
    s = str(v)
    n = to_float(s)
    if n is not None:
        return f"{n:.12g}"
    return json.dumps(s, ensure_ascii=False)


def set_py_const(text: str, name: str, rhs: str) -> str:
    pat = re.compile(rf"(?m)^{re.escape(name)}\s*=\s*.*$")
    if not pat.search(text):
        raise RuntimeError(f"No se encontro constante para patch: {name}")
    return pat.sub(lambda _m: f"{name} = {rhs}", text, count=1)


def insert_text_after_future_imports(text: str, block: str) -> str:
    lines = text.splitlines()
    insert_at: Optional[int] = None
    for idx, line in enumerate(lines):
        if line.startswith("from __future__ import "):
            insert_at = idx + 1
            while insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
            break
    if insert_at is None:
        return block.rstrip("\n") + "\n\n" + text
    merged = lines[:insert_at] + ["", block.rstrip("\n"), ""] + lines[insert_at:]
    return "\n".join(merged)


def parse_py_literal_basic(lit: Optional[str]) -> Any:
    if lit is None:
        return None
    s = str(lit).strip()
    if not s:
        return None
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    sl = s.lower()
    if sl == "true":
        return True
    if sl == "false":
        return False
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        try:
            n = float(s)
            if float(int(n)) == n:
                return int(n)
            return n
        except Exception:
            return s
    return s


_SPY_WEEK_INDEX_CACHE: Dict[str, Any] = {}
_SPY_WEEK_START_RESULT_CACHE: Dict[str, Optional[str]] = {}


def compute_last_n_weeks_start_date(
    weekly_csv: Optional[Path],
    test_end: Any,
    regime_weeks: int,
    require_next_within_test: bool,
) -> Optional[str]:
    if not weekly_csv or (not weekly_csv.exists()) or int(regime_weeks) <= 0:
        return None
    test_end_ts = None
    try:
        import pandas as pd  # Lazy import

        test_end_ts = pd.Timestamp(test_end)
    except Exception:
        return None
    cache_key = f"{str(weekly_csv.resolve())}|{weekly_csv.stat().st_mtime}|{weekly_csv.stat().st_size}"
    result_key = f"{cache_key}|{test_end_ts.strftime('%Y-%m-%d')}|{int(regime_weeks)}|{int(bool(require_next_within_test))}"
    if result_key in _SPY_WEEK_START_RESULT_CACHE:
        return _SPY_WEEK_START_RESULT_CACHE[result_key]

    spy_df = _SPY_WEEK_INDEX_CACHE.get(cache_key)
    if spy_df is None:
        try:
            import pandas as pd  # Lazy import

            parts = []
            usecols = ["ticker", "signal_date"]
            for chunk in pd.read_csv(weekly_csv, usecols=usecols, chunksize=200000):
                c = chunk[chunk["ticker"] == "SPY"].copy()
                if c.empty:
                    continue
                c["signal_date"] = pd.to_datetime(c["signal_date"], errors="coerce")
                c = c.dropna(subset=["signal_date"])
                if c.empty:
                    continue
                parts.append(c[["signal_date"]])
            if not parts:
                _SPY_WEEK_START_RESULT_CACHE[result_key] = None
                return None
            spy_df = (
                pd.concat(parts, ignore_index=True)
                .drop_duplicates(subset=["signal_date"])
                .sort_values("signal_date")
                .reset_index(drop=True)
            )
            # El weekly master no incluye next_signal_date; se deriva por desplazamiento temporal.
            spy_df["next_signal_date"] = spy_df["signal_date"].shift(-1)
            _SPY_WEEK_INDEX_CACHE[cache_key] = spy_df
        except Exception:
            return None
    try:
        import pandas as pd  # Lazy import

        w = spy_df.copy()
        w = w[w["signal_date"] <= test_end_ts].copy()
        if require_next_within_test:
            w = w[w["next_signal_date"].notna() & (w["next_signal_date"] <= test_end_ts)].copy()
        w = w.sort_values("signal_date")
        if w.empty:
            _SPY_WEEK_START_RESULT_CACHE[result_key] = None
            return None
        tail_n = w.tail(int(regime_weeks)).copy()
        if tail_n.empty:
            _SPY_WEEK_START_RESULT_CACHE[result_key] = None
            return None
        start_ts = pd.to_datetime(tail_n["signal_date"].iloc[0], errors="coerce")
        if pd.isna(start_ts):
            _SPY_WEEK_START_RESULT_CACHE[result_key] = None
            return None
        out = str(start_ts.strftime("%Y-%m-%d"))
        _SPY_WEEK_START_RESULT_CACHE[result_key] = out
        return out
    except Exception:
        _SPY_WEEK_START_RESULT_CACHE[result_key] = None
        return None


def load_script_config(script_path: Path, keys: List[str], default_cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(default_cfg)
    if not script_path.exists():
        return cfg
    text = script_path.read_text(encoding="utf-8", errors="ignore")
    for k in keys:
        lit = get_py_const_literal(text, k)
        if not lit:
            continue
        norm = normalize_scalar(lit)
        if norm == "true":
            cfg[k] = True
        elif norm == "false":
            cfg[k] = False
        elif re.fullmatch(r"-?\d+(\.\d+)?", norm):
            cfg[k] = float(norm)
        else:
            s = lit.strip()
            if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
                cfg[k] = s[1:-1]
            else:
                cfg[k] = lit
    return cfg


def compute_diff(cfg_from: Dict[str, Any], cfg_to: Dict[str, Any], keys: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for k in keys:
        a = normalize_scalar(cfg_from.get(k))
        b = normalize_scalar(cfg_to.get(k))
        if a != b:
            out.append({"parameter": k, "from": cfg_from.get(k), "to": cfg_to.get(k)})
    return out


def ensure_ties_total_in_summary(script_text: str) -> str:
    # Compatibilidad con scripts parent viejos: agrega ties_total al summary_total impreso en stdout.
    if '"ties_total"' in script_text:
        return script_text
    patt = re.compile(r'^(?P<indent>\s*)"none_total"\s*:\s*.*?,\s*$', flags=re.MULTILINE)
    m = patt.search(script_text)
    if not m:
        return script_text
    indent = m.group("indent")
    tie_line = (
        f'{indent}"ties_total": int((((pd.to_numeric(df_next_week_real_trades["net_return_pct"], errors="coerce") >= 0.0) '
        f'& (pd.to_numeric(df_next_week_real_trades["net_return_pct"], errors="coerce") <= 1.0)).fillna(False)).sum()) '
        f'if (not df_next_week_real_trades.empty and "net_return_pct" in df_next_week_real_trades.columns) else 0,'
    )
    return script_text[: m.end()] + "\n" + tie_line + script_text[m.end() :]


def parse_run_id(value: str) -> int:
    m = re.match(r"^EXP_(\d+)$", str(value))
    return int(m.group(1)) if m else -1


def parse_run_id_from_dirname(dirname: str) -> str:
    m = re.match(r"^(EXP_\d+)", dirname)
    return m.group(1) if m else ""


EXPERIMENT_LOG_HEADER = [
    "run_id",
    "date",
    "parent_run_id",
    "parent_script",
    "baseline_reference",
    "queue_test_id",
    "main_parameter",
    "main_from",
    "main_to",
    "dependent_parameter",
    "dependent_from",
    "dependent_to",
    "expected_effect",
    "status",
    "preflight_pass",
    "no_op_detected",
    "effective_change_check",
    "w8_weeks_traded",
    "w24_weeks_traded",
    "w52_weeks_traded",
    "w8_trades",
    "w24_trades",
    "w52_trades",
    "w8_wins",
    "w24_wins",
    "w52_wins",
    "w8_losses",
    "w24_losses",
    "w52_losses",
    "w8_ties",
    "w24_ties",
    "w52_ties",
    "w8_pnl",
    "w24_pnl",
    "w52_pnl",
    "w8_spy_compare",
    "w24_spy_compare",
    "w52_spy_compare",
    "accepted_or_rejected",
    "notes",
    "run_dir",
]


def ensure_experiment_log(path: Path) -> None:
    if path.exists():
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(EXPERIMENT_LOG_HEADER)


def read_experiment_log(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def append_experiment_row(path: Path, row: Dict[str, Any]) -> None:
    header = list(EXPERIMENT_LOG_HEADER)
    clean_row = {k: clean_text(row.get(k, "")) for k in header}
    safe_append_csv_row(path, header, clean_row, delimiter=";", retries=12, delay_seconds=0.20)


def next_run_id(rows: List[Dict[str, str]], runs_root: Optional[Path] = None) -> str:
    mx = -1
    for r in rows:
        mx = max(mx, parse_run_id(r.get("run_id", "")))
    if runs_root and runs_root.exists():
        try:
            for run_dir in runs_root.iterdir():
                if run_dir.is_dir():
                    mx = max(mx, parse_run_id(parse_run_id_from_dirname(run_dir.name)))
        except Exception:
            pass
    return f"EXP_{mx+1:03d}" if mx >= 0 else "EXP_001"


def get_latest_weekly_csv(repo: Path) -> Optional[Path]:
    files = sorted(repo.glob("sp500_feature_store_weekly_master_all_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _build_valid_run_context_from_dir(run_dir: Path) -> Optional[Dict[str, Any]]:
    eo_path = run_dir / "executor_output.json"
    co_path = run_dir / "coordinator_output.json"
    recovery_path = run_dir / "recovery_status.json"
    run_status_path = run_dir / "run_status.json"
    manifest_path = run_dir / "experiment_manifest.json"
    if not eo_path.exists() or (not co_path.exists()):
        return None
    recovery = load_json(recovery_path, {})
    if isinstance(recovery, dict) and bool(recovery.get("do_not_use_as_parent", False)):
        return None
    run_status = load_json(run_status_path, {})
    if isinstance(run_status, dict) and clean_text(run_status.get("status", "")) in {"blocked_preflight", "blocked_preflight_complete"}:
        return None
    manifest = load_json(manifest_path, {})
    if isinstance(manifest, dict) and clean_text(manifest.get("status", "")) in {"blocked_preflight"}:
        return None
    eo = load_json(eo_path, {})
    eo_status = clean_text(eo.get("status", ""))
    if eo_status not in {"run_ok", "run_partial_valid"}:
        return None
    co = load_json(co_path, {})
    co_decision = clean_text(co.get("decision_type", ""))
    if co_decision not in {"accepted_for_followup", "promoted_to_baseline"}:
        return None
    candidate_script = eo.get("script_executed") or co.get("candidate_script") or ""
    if not candidate_script:
        return None
    script_path = Path(candidate_script)
    if not script_path.exists():
        return None
    return {
        "run_id": parse_run_id_from_dirname(run_dir.name),
        "run_dir": str(run_dir),
        "script_path": str(script_path),
        "executor_output": eo,
        "coordinator_output": co,
    }


def get_latest_valid_run_context(repo: Path) -> Optional[Dict[str, Any]]:
    cfg = load_paths_config(repo)
    runs_root_rel = cfg_get_str(cfg, ["runs", "multi_agent_runs"], "runs/multi_agent_runs")
    runs_root = (repo / runs_root_rel).resolve()
    if not runs_root.exists():
        # Legacy fallback (pre-restructure)
        runs_root = (repo / "multi_agent_runs").resolve()
    if not runs_root.exists():
        return None
    dirs = sorted([d for d in runs_root.iterdir() if d.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    for d in dirs:
        ctx = _build_valid_run_context_from_dir(d)
        if ctx:
            return ctx
    return None


def get_run_context_by_run_id(repo: Path, run_id: str) -> Optional[Dict[str, Any]]:
    rid = clean_text(run_id)
    if not rid or parse_run_id(rid) < 0:
        return None
    cfg = load_paths_config(repo)
    runs_root_rel = cfg_get_str(cfg, ["runs", "multi_agent_runs"], "runs/multi_agent_runs")
    runs_root = (repo / runs_root_rel).resolve()
    if not runs_root.exists():
        runs_root = (repo / "multi_agent_runs").resolve()
    if not runs_root.exists():
        return None
    dirs = sorted(
        [d for d in runs_root.iterdir() if d.is_dir() and d.name.startswith(f"{rid}_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for d in dirs:
        ctx = _build_valid_run_context_from_dir(d)
        if ctx:
            return ctx
    return None


CHAMPION_SLOTS: List[str] = [
    "best_w52_spy_compare_run_id",
    "best_balance_quality_frequency_run_id",
    "best_multi_year_real_run_id",
    "best_orthogonal_exploration_run_id",
    "best_recent_followup_run_id",
]


def default_champion_runs() -> Dict[str, Any]:
    return {
        "version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "champions": {slot: "" for slot in CHAMPION_SLOTS},
        "metadata": {slot: {} for slot in CHAMPION_SLOTS},
    }


def ensure_champion_runs(path: Path) -> Dict[str, Any]:
    data = load_json(path, {})
    if not isinstance(data, dict) or not data:
        data = default_champion_runs()
        save_json(path, data)
        return data
    changed = False
    if "version" not in data:
        data["version"] = 1
        changed = True
    if "updated_at" not in data:
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        changed = True
    if "champions" not in data or not isinstance(data.get("champions"), dict):
        data["champions"] = {}
        changed = True
    if "metadata" not in data or not isinstance(data.get("metadata"), dict):
        data["metadata"] = {}
        changed = True
    for slot in CHAMPION_SLOTS:
        if slot not in data["champions"]:
            data["champions"][slot] = ""
            changed = True
        if slot not in data["metadata"] or not isinstance(data["metadata"].get(slot), dict):
            data["metadata"][slot] = {}
            changed = True
        meta = data["metadata"].get(slot, {})
        if isinstance(meta, dict) and meta:
            decision = clean_text(meta.get("decision_type", ""))
            champion_followup = bool(meta.get("champion_for_followup", False))
            defaults = {
                "run_id": clean_text(data["champions"].get(slot, "")),
                "main_change": "",
                "w24_spy_compare": None,
                "w52_spy_compare": meta.get("w52_spy_compare"),
                "w52_pnl": None,
                "status": "",
                "accepted_for_followup": decision == "accepted_for_followup",
                "promoted_to_baseline": decision == "promoted_to_baseline",
                "champion_for_followup": champion_followup,
                "reusable_parent": bool(
                    meta.get("reusable_parent", False)
                    or champion_followup
                    or decision in {"accepted_for_followup", "promoted_to_baseline"}
                ),
                "why_it_is_a_champion": clean_text(meta.get("reason", "")),
            }
            for k, v in defaults.items():
                if k not in meta:
                    meta[k] = v
                    changed = True
            if bool(defaults["reusable_parent"]) and not bool(meta.get("reusable_parent", False)):
                meta["reusable_parent"] = True
                changed = True
    if changed:
        save_json(path, data)
    return data


def _champion_run_id_candidates(champion_runs: Dict[str, Any]) -> List[Tuple[str, str]]:
    champions = champion_runs.get("champions", {}) if isinstance(champion_runs, dict) else {}
    if not isinstance(champions, dict):
        champions = {}
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for slot in CHAMPION_SLOTS:
        rid = clean_text(champions.get(slot, ""))
        if not rid or rid in seen:
            continue
        seen.add(rid)
        out.append((slot, rid))
    return out


def _w52_map_from_rows(rows: List[Dict[str, str]]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    for r in rows or []:
        rid = clean_text(r.get("run_id", ""))
        if not rid:
            continue
        out[rid] = to_float(r.get("w52_spy_compare"))
    return out


def has_three_recent_worse_than_parent(
    rows: List[Dict[str, str]],
    parent_run_id: str,
    lookback: int = 20,
) -> bool:
    target_parent = clean_text(parent_run_id)
    if not target_parent or target_parent == "BASELINE_CLEAN":
        return False
    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = sorted_rows[-max(3, int(lookback)) :] if sorted_rows else []
    w52_map = _w52_map_from_rows(sorted_rows)
    parent_spy = to_float(w52_map.get(target_parent))
    if parent_spy is None:
        return False
    seq: List[Dict[str, Any]] = []
    for r in recent:
        if clean_text(r.get("status", "")) not in {"run_ok", "run_partial_valid"}:
            continue
        row_parent = clean_text(r.get("parent_run_id", ""))
        if row_parent != target_parent:
            continue
        rid = clean_text(r.get("run_id", ""))
        row_spy = to_float(r.get("w52_spy_compare"))
        decision = clean_text(r.get("accepted_or_rejected", "")).lower()
        delta = (float(row_spy) - float(parent_spy)) if (row_spy is not None and parent_spy is not None) else None
        seq.append({"run_id": rid, "delta": delta, "decision": decision})
    if len(seq) < 3:
        return False
    last3 = seq[-3:]
    for item in last3:
        d = to_float(item.get("delta"))
        if d is None:
            return False
        if not (float(d) < -0.05):
            return False
    return True


def get_best_champion_context(
    repo: Path,
    champion_runs: Dict[str, Any],
    exclude_run_id: str = "",
) -> Tuple[Optional[Dict[str, Any]], str]:
    candidates: List[Tuple[int, str, str, Dict[str, Any]]] = []
    excluded = clean_text(exclude_run_id)
    for slot, rid in _champion_run_id_candidates(champion_runs):
        if excluded and clean_text(rid) == excluded:
            continue
        ctx = get_run_context_by_run_id(repo, rid)
        if not ctx:
            continue
        ctx_rid = clean_text(ctx.get("run_id", "")) or rid
        rn = parse_run_id(ctx_rid)
        candidates.append((rn, slot, ctx_rid, ctx))
    if not candidates:
        return None, "champion_runs:none"
    candidates.sort(key=lambda x: x[0], reverse=True)
    _, slot, rid, ctx = candidates[0]
    return ctx, f"champion_runs:{slot}={rid}"


def get_preferred_parent_context(
    repo: Path,
    baseline: Dict[str, Any],
    research_state: Dict[str, Any],
    champion_runs: Optional[Dict[str, Any]] = None,
    rows: Optional[List[Dict[str, str]]] = None,
) -> Tuple[Optional[Dict[str, Any]], str, str, str]:
    if research_state_requests_baseline_parent(research_state):
        return None, "current_baseline", "", ""

    b_st = baseline.get("state_tracking", {}) if isinstance(baseline.get("state_tracking"), dict) else {}
    r_st = research_state.get("state_tracking", {}) if isinstance(research_state.get("state_tracking"), dict) else {}
    p_st = research_state.get("parent_state", {}) if isinstance(research_state.get("parent_state"), dict) else {}
    ordered_candidates = [
        ("research.parent_state.current_parent_run_id", clean_text(p_st.get("current_parent_run_id", ""))),
        ("research.parent_state.last_useful_run_id", clean_text(p_st.get("last_useful_run_id", ""))),
        ("research.last_followup_run_id", clean_text(r_st.get("last_followup_run_id", ""))),
        ("research.last_useful_run_id", clean_text(r_st.get("last_useful_run_id", ""))),
        ("baseline.last_followup_run_id", clean_text(b_st.get("last_followup_run_id", ""))),
        ("baseline.last_useful_run_id", clean_text(b_st.get("last_useful_run_id", ""))),
    ]
    seen: set[str] = set()
    best_ctx: Optional[Dict[str, Any]] = None
    best_src: str = ""
    best_rid: str = ""
    rejected_startup_parent_run_id = ""
    rejected_startup_parent_reason = ""
    for src, rid in ordered_candidates:
        if not rid or rid == "BASELINE_CLEAN" or rid in seen:
            continue
        seen.add(rid)
        ctx = get_run_context_by_run_id(repo, rid)
        if not ctx:
            if not rejected_startup_parent_run_id:
                rejected_startup_parent_run_id = rid
                rejected_startup_parent_reason = "startup_parent_rejected_low_depth_52w"
            continue
        guard = evaluate_startup_parent_depth_guard_52w(ctx)
        if not bool(guard.get("pass", False)):
            if not rejected_startup_parent_run_id:
                rejected_startup_parent_run_id = clean_text(guard.get("run_id", "")) or rid
                rejected_startup_parent_reason = clean_text(guard.get("reason", "")) or "startup_parent_rejected_low_depth_52w"
            continue
        best_ctx = ctx
        best_src = src
        best_rid = clean_text(ctx.get("run_id", "")) or rid
        break
    champion_ctx, champion_src = get_best_champion_context(repo, champion_runs or {})
    if champion_ctx and not bool(evaluate_startup_parent_depth_guard_52w(champion_ctx).get("pass", False)):
        if not rejected_startup_parent_run_id:
            champ_guard = evaluate_startup_parent_depth_guard_52w(champion_ctx)
            rejected_startup_parent_run_id = clean_text(champ_guard.get("run_id", "")) or clean_text(champion_ctx.get("run_id", ""))
            rejected_startup_parent_reason = clean_text(champ_guard.get("reason", "")) or "startup_parent_rejected_low_depth_52w"
        champion_ctx = None
    if best_ctx and champion_ctx:
        current_parent_rid = clean_text(best_ctx.get("run_id", ""))
        if has_three_recent_worse_than_parent(rows or [], current_parent_rid):
            if clean_text(champion_ctx.get("run_id", "")) == current_parent_rid:
                alt_ctx, alt_src = get_best_champion_context(
                    repo,
                    champion_runs or {},
                    exclude_run_id=current_parent_rid,
                )
                if alt_ctx:
                    return alt_ctx, f"{alt_src};trigger=three_recent_worse_than_parent:{current_parent_rid}", rejected_startup_parent_run_id, rejected_startup_parent_reason
            return champion_ctx, f"{champion_src};trigger=three_recent_worse_than_parent:{current_parent_rid}", rejected_startup_parent_run_id, rejected_startup_parent_reason
        return best_ctx, f"state_tracking:{best_src}={best_rid}", rejected_startup_parent_run_id, rejected_startup_parent_reason
    if best_ctx:
        return best_ctx, f"state_tracking:{best_src}={best_rid}", rejected_startup_parent_run_id, rejected_startup_parent_reason
    if champion_ctx:
        return champion_ctx, champion_src, rejected_startup_parent_run_id, rejected_startup_parent_reason
    return None, "current_baseline", rejected_startup_parent_run_id, rejected_startup_parent_reason


def default_clean_baseline(repo: Path) -> Dict[str, Any]:
    return {
        "version": 3,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "validation_phase": "year1",
        "project": "SPY context strategy",
        "baseline_script": "spy_context_asset_profile_configurable_regime_weeks_gated_close_vs_sma50_1_5_FIXED_GATES.py",
        "tie_rule": {"tie_low_pct": 0.0, "tie_high_pct": 1.0},
        "active_config": {
            "REGIME_WEEKS_TO_RUN": 52,
            "PARALLEL_REGIME_WORKERS": 2,
            "ENABLE_SPY_CHANNEL_R2_GATE": True,
            "MIN_SPY_CHANNEL_R2": 0.55,
            "ENABLE_AVG_PROFILE_DISTANCE_GATE": True,
            "MAX_AVG_PROFILE_DISTANCE": 0.20,
            "ENABLE_CLOSE_VS_SMA50_FILTER": False,
            "MAX_CLOSE_VS_SMA50_PCT": 1.5,
            "TOP_CANDIDATES_NEXT_WEEK": 5,
            "STRATEGY_FAMILY": "profile_match",
            "MOMENTUM_MIN_RET_4W_PCT": -5.0,
            "MOMENTUM_MAX_CLOSE_VS_SMA20W_PCT": 25.0,
            "MOMENTUM_W_RET_4W": 0.45,
            "MOMENTUM_W_RET_8W": 0.35,
            "MOMENTUM_W_TREND": 0.20,
            "TOP_SIMILAR_SPY_WEEKS": 20,
            "MIN_SIMILAR_WEEKS_REQUIRED": 5,
            "PROFILE_MODE": "p25_p75",
            "PROFILE_EXPANSION_FACTOR": 0.10,
            "ENABLE_VAR_CHANNEL_R2": True,
            "ENABLE_VAR_CHANNEL_SLOPE_PCT": True,
            "ENABLE_VAR_CLOSE_VS_SMA50_PCT": True,
            "ENABLE_VAR_CLOSE_SMA_50_SLOPE_5D_PCT": True,
            "ENABLE_VAR_WEEKLY_RANGE_PCT": True,
            "ENABLE_VAR_RET_2W_PCT": True,
            "ENABLE_VAR_CLOSE_VS_SMA4W_PCT": True,
            "ENABLE_VAR_RET_4W_PCT": False,
            "ENABLE_VAR_CLOSE_VS_SMA8W_PCT": False,
            "ENABLE_VAR_CLOSE_VS_SMA20W_PCT": False,
            "ENABLE_VAR_ATR_14W_PCT": False,
            "ENABLE_VAR_VOLUME_RATIO_VS_SMA13W": False,
            "ENABLE_VAR_DIST_TO_HIGH_26W_PCT": False,
            "INITIAL_TP_PCT": 0.05,
            "INITIAL_SL_PCT": 0.05,
            "FIRST_LOCKED_SL_PCT": 0.01,
            "TRAIL_STEP_PCT": 0.05,
        },
        "validation_policy": {
            "windows": [4, 8, 24, 52],
            "must_compare_vs_spy": True,
            "long_window_policy": {
                "treat_insufficient_depth_as_non_fatal": True,
                "minimum_usable_strong_window": 52,
                "require_real_depth_for_156": True,
                "run_156_policy": "cadence_only",
                "run_156_cadence_useful_runs": 4,
                "run_156_min_w52_spy_compare": 0.5,
                "run_156_min_w52_weeks_traded": 20,
                "run_156_min_w52_trades": 15,
            },
            "runtime_performance": {
                "strict_progressive_windows": True,
                "window_reuse_enabled": True,
                "fast_artifacts_enabled": True,
                "xlsx_cadence_runs": 5,
                "tracker_xlsx_refresh_enabled": False,
                "window_xlsx_artifacts_enabled": False,
                "profile_cadence_runs": 10,
            },
        },
        "baseline_reference": {
            "run_id": "BASELINE_CLEAN",
            "script": str((repo / "spy_context_asset_profile_configurable_regime_weeks_gated_close_vs_sma50_1_5_FIXED_GATES.py").resolve()),
            "accepted_at": datetime.now().isoformat(timespec="seconds"),
        },
        # Compatibilidad con versiones previas.
        "last_accepted_run_id": "BASELINE_CLEAN",
        "state_tracking": {
            "last_useful_run_id": "BASELINE_CLEAN",
            "last_followup_run_id": "",
            "last_promoted_baseline_run_id": "BASELINE_CLEAN",
            "last_successful_executor_run_id": "BASELINE_CLEAN",
            "last_completed_initial_test_id": "",
        },
        "branch_anchor": default_branch_anchor_state(),
        "research_governance": {
            "enabled": True,
            "embedded_in_coordinator": True,
            "required_scores": [
                "process_reliability_score",
                "analyst_quality_score",
                "coordinator_quality_score",
                "research_effectiveness_score",
                "overall_agent_score",
            ],
            "required_meta_fields": [
                "research_value",
                "branch_health",
                "learning_signal",
                "stagnation_risk",
                "main_friction",
                "recommended_next_action",
                "recommended_change_directions",
            ],
        },
        "promotion_policy": {
            "accepted_for_followup_requires": [
                "material_change_detected",
                "useful_learning_or_evidence",
                "usable_validation_depth",
            ],
            "promoted_to_baseline_requires": [
                "robust_improvement_vs_parent",
                "consistent_compare_vs_spy",
                "not_short_term_only",
                "enough_validation_depth",
            ],
        },
        "notes": [
            "Baseline limpio de reinicio multiagente.",
            "No confundir last_followup_run_id con last_promoted_baseline_run_id.",
            "Si 156 queda insufficient_depth pero 52 es valida, preservar la corrida como usable para follow-up.",
        ],
    }


def ensure_baseline(path: Path, repo: Path) -> Dict[str, Any]:
    base = load_json(path, {})
    if not base:
        # Read-only baseline policy: never materialize a missing/invalid baseline
        # back to disk unless an explicit promotion is being applied later.
        return default_clean_baseline(repo)
    if "active_config" not in base or not isinstance(base.get("active_config"), dict):
        return default_clean_baseline(repo)

    defaults = default_clean_baseline(repo)

    def _merge_missing(dst: Dict[str, Any], src: Dict[str, Any]) -> bool:
        changed_local = False
        for k, v in src.items():
            if k not in dst:
                dst[k] = v
                changed_local = True
                continue
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                if _merge_missing(dst[k], v):
                    changed_local = True
        return changed_local

    changed = _merge_missing(base, defaults)
    if "state_tracking" not in base or not isinstance(base.get("state_tracking"), dict):
        base["state_tracking"] = dict(defaults.get("state_tracking", {}))
        changed = True
    if "validation_policy" not in base or not isinstance(base.get("validation_policy"), dict):
        base["validation_policy"] = dict(defaults.get("validation_policy", {}))
        changed = True
    if "research_governance" not in base or not isinstance(base.get("research_governance"), dict):
        base["research_governance"] = dict(defaults.get("research_governance", {}))
        changed = True
    # Do not persist automatic repairs to the baseline file.
    return base


def default_research_state() -> Dict[str, Any]:
    return {
        "version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "project": "SPY context strategy",
        "branch_state": {
            "active_branch_id": "main",
            "branch_health": "alive_but_noisy",
            "learning_signal": "medium",
            "stagnation_risk": "medium",
            "main_friction": "none",
            "recommended_next_action": "refine_current_branch",
            "current_mode": "refine_current_branch",
            "mode_reason": "default_initial_mode",
            "last_mode_change_at": "",
            "last_mode_change_run_id": "",
            "previous_mode": "",
            "mode_stability_counter": 0,
            "branch_anchor_active": False,
            "anchor_parameter": "",
            "anchor_value": None,
            "anchor_hold_iterations": 0,
        },
        "state_tracking": {
            "last_useful_run_id": "BASELINE_CLEAN",
            "last_followup_run_id": "",
            "last_promoted_baseline_run_id": "BASELINE_CLEAN",
            "last_successful_executor_run_id": "BASELINE_CLEAN",
            "last_completed_initial_test_id": "",
        },
        "parent_state": {
            "current_parent_run_id": "BASELINE_CLEAN",
            "last_useful_run_id": "BASELINE_CLEAN",
        },
        "latest_scores": {
            "process_reliability_score": None,
            "analyst_quality_score": None,
            "coordinator_quality_score": None,
            "research_effectiveness_score": None,
            "overall_agent_score": None,
        },
        "latest_learning_summary": {
            "research_value": "",
            "what_was_learned": [],
            "what_is_not_working": [],
            "process_warnings": [],
            "recommended_change_directions": [],
        },
        "branch_anchor": default_branch_anchor_state(),
        "branch_memory": [],
        "guardrails": {
            "do_not_reset_to_initial_queue_if_useful_run_exists": True,
            "do_not_treat_insufficient_depth_as_fatal_by_default": True,
            "do_not_confuse_duplicate_with_true_zigzag": True,
            "preserve_52w_evidence_if_156_not_real": True,
        },
    }


def ensure_research_state(path: Path, baseline: Dict[str, Any]) -> Dict[str, Any]:
    rs = load_json(path, {})
    if not isinstance(rs, dict) or not rs:
        rs = default_research_state()
    defaults = default_research_state()

    def _merge_missing(dst: Dict[str, Any], src: Dict[str, Any]) -> bool:
        changed_local = False
        for k, v in src.items():
            if k not in dst:
                dst[k] = v
                changed_local = True
                continue
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                if _merge_missing(dst[k], v):
                    changed_local = True
        return changed_local

    changed = _merge_missing(rs, defaults)
    # Sincroniza referencias mínimas de baseline para continuidad.
    st = rs.get("state_tracking", {}) if isinstance(rs.get("state_tracking"), dict) else {}
    b_st = baseline.get("state_tracking", {}) if isinstance(baseline.get("state_tracking"), dict) else {}
    if b_st:
        for k in [
            "last_useful_run_id",
            "last_followup_run_id",
            "last_promoted_baseline_run_id",
            "last_successful_executor_run_id",
            "last_completed_initial_test_id",
        ]:
            if clean_text(st.get(k, "")) == "" and clean_text(b_st.get(k, "")) != "":
                st[k] = b_st.get(k)
                changed = True
        rs["state_tracking"] = st
    if changed:
        rs["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_json(path, rs)
    return rs


def transition_key(parameter: Any, from_value: Any, to_value: Any) -> Tuple[str, str, str]:
    return (
        clean_text(parameter),
        normalize_scalar(from_value),
        normalize_scalar(to_value),
    )


def default_parameter_effect_memory() -> Dict[str, Any]:
    return {
        "version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "transitions": [],
    }


def _default_parameter_effect_entry(parameter: str, from_value: Any, to_value: Any) -> Dict[str, Any]:
    return {
        "parameter": clean_text(parameter),
        "from_value": normalize_scalar(from_value),
        "to_value": normalize_scalar(to_value),
        "total_attempts": 0,
        "accepted_count": 0,
        "rejected_count": 0,
        "avg_delta_w24_spy_compare": None,
        "avg_delta_w52_spy_compare": None,
        "avg_delta_w52_pnl": None,
        "avg_delta_w52_trades": None,
        "avg_delta_w52_avg_net_return_pct": None,
        "last_run_ids": [],
        "best_run_id": "",
        "best_context_summary": "",
        "branch_health_when_tested": "",
        "main_friction_when_tested": "",
        "current_effect_class": "neutral",
        # Persistencia explícita para follow-up fuerte con profundidad larga insuficiente.
        "champion_for_followup": False,
        "reusable_parent": False,
        # Campos auxiliares para promedio incremental robusto.
        "_samples": {
            "avg_delta_w24_spy_compare": 0,
            "avg_delta_w52_spy_compare": 0,
            "avg_delta_w52_pnl": 0,
            "avg_delta_w52_trades": 0,
            "avg_delta_w52_avg_net_return_pct": 0,
        },
        "_best_delta_w52_spy_compare": None,
    }


def ensure_parameter_effect_memory(path: Path) -> Dict[str, Any]:
    data = load_json(path, {})
    if not isinstance(data, dict) or not data:
        data = default_parameter_effect_memory()
        save_json(path, data)
        return data
    if "version" not in data:
        data["version"] = 1
    if "updated_at" not in data:
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if "transitions" not in data or not isinstance(data.get("transitions"), list):
        data["transitions"] = []
    changed = False
    cleaned: List[Dict[str, Any]] = []
    for raw in data.get("transitions", []):
        if not isinstance(raw, dict):
            changed = True
            continue
        param = clean_text(raw.get("parameter", ""))
        from_value = normalize_scalar(raw.get("from_value"))
        to_value = normalize_scalar(raw.get("to_value"))
        if not param:
            changed = True
            continue
        defaults = _default_parameter_effect_entry(param, from_value, to_value)
        base = dict(raw)
        for k, v in defaults.items():
            if k not in base:
                base[k] = v
        base["parameter"] = param
        base["from_value"] = from_value
        base["to_value"] = to_value
        if not isinstance(base.get("last_run_ids"), list):
            base["last_run_ids"] = []
        base["last_run_ids"] = [clean_text(x) for x in (base.get("last_run_ids") or []) if clean_text(x)]
        if "_samples" not in base or not isinstance(base.get("_samples"), dict):
            base["_samples"] = dict(_default_parameter_effect_entry(param, from_value, to_value).get("_samples", {}))
        for sk in list(_default_parameter_effect_entry(param, from_value, to_value).get("_samples", {}).keys()):
            base["_samples"][sk] = int(to_float((base.get("_samples", {}) or {}).get(sk)) or 0)
        base["total_attempts"] = int(to_float(base.get("total_attempts")) or 0)
        base["accepted_count"] = int(to_float(base.get("accepted_count")) or 0)
        base["rejected_count"] = int(to_float(base.get("rejected_count")) or 0)
        cleaned.append(base)
    if cleaned != data.get("transitions", []):
        data["transitions"] = cleaned
        changed = True
    if changed:
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_json(path, data)
    return data


def _effect_entries(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = data.get("transitions", []) if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return []
    return rows


def get_parameter_effect_entry(
    data: Dict[str, Any],
    parameter: Any,
    from_value: Any,
    to_value: Any,
    create_if_missing: bool = False,
) -> Optional[Dict[str, Any]]:
    key = transition_key(parameter, from_value, to_value)
    for row in _effect_entries(data):
        row_key = transition_key(row.get("parameter"), row.get("from_value"), row.get("to_value"))
        if row_key == key:
            return row
    if not create_if_missing:
        return None
    entry = _default_parameter_effect_entry(key[0], key[1], key[2])
    if "transitions" not in data or not isinstance(data.get("transitions"), list):
        data["transitions"] = []
    data["transitions"].append(entry)
    return entry


def _update_running_avg(entry: Dict[str, Any], field: str, sample_field: str, value: Optional[float]) -> None:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return
    samples = entry.get("_samples", {}) if isinstance(entry.get("_samples"), dict) else {}
    n = int(to_float(samples.get(sample_field)) or 0)
    current_avg = to_float(entry.get(field))
    if current_avg is None or not math.isfinite(float(current_avg)):
        new_avg = float(value)
    else:
        new_avg = ((float(current_avg) * n) + float(value)) / float(n + 1)
    entry[field] = round(float(new_avg), 6)
    samples[sample_field] = n + 1
    entry["_samples"] = samples


def classify_parameter_effect_class(entry: Dict[str, Any]) -> str:
    attempts = int(to_float(entry.get("total_attempts")) or 0)
    accepted = int(to_float(entry.get("accepted_count")) or 0)
    rejected = int(to_float(entry.get("rejected_count")) or 0)
    reject_ratio = (float(rejected) / float(attempts)) if attempts > 0 else 0.0
    accept_ratio = (float(accepted) / float(attempts)) if attempts > 0 else 0.0
    d_spy = to_float(entry.get("avg_delta_w52_spy_compare"))
    d_avg = to_float(entry.get("avg_delta_w52_avg_net_return_pct"))
    champion_flag = bool(entry.get("champion_for_followup", False))

    if attempts >= 3 and reject_ratio >= 0.75:
        return "exhausted"
    if champion_flag and d_spy is not None and d_spy >= 0.5:
        return "strong_positive"
    if d_spy is not None and d_spy <= -0.25 and reject_ratio >= 0.60:
        return "harmful"
    if d_spy is not None and d_spy >= 0.60 and accept_ratio >= 0.50:
        return "strong_positive"
    if d_spy is not None and d_spy >= 0.15 and accept_ratio >= 0.35:
        return "mild_positive"
    if accepted > 0 and rejected > 0 and d_spy is not None and abs(d_spy) < 0.20:
        return "unstable"
    if (
        d_spy is not None
        and abs(d_spy) < 0.10
        and (d_avg is None or abs(d_avg) < 0.10)
    ):
        return "neutral"
    if reject_ratio >= 0.60:
        return "harmful"
    return "neutral"


def parameter_effect_hard_block_reason(
    entry: Optional[Dict[str, Any]],
    *,
    min_attempts: int = 3,
    min_rejected: int = 3,
) -> str:
    """
    Hard block a transition when learning memory says it is exhausted.

    This is intentionally stricter than scoring: once a parameter transition
    repeatedly produced rejected / no-useful outcomes, candidate generation must
    not spend another 52w run on the same axis unless a future explicit override
    is implemented and documented.
    """
    if not isinstance(entry, dict) or not entry:
        return ""
    cls = clean_text(entry.get("current_effect_class", "")).lower()
    attempts = int(to_float(entry.get("total_attempts")) or 0)
    accepted = int(to_float(entry.get("accepted_count")) or 0)
    rejected = int(to_float(entry.get("rejected_count")) or 0)

    if cls == "exhausted":
        return f"parameter_effect_memory_exhausted attempts={attempts} accepted={accepted} rejected={rejected}"
    if attempts >= int(min_attempts) and accepted == 0 and rejected >= int(min_rejected):
        return f"parameter_effect_memory_zero_acceptance attempts={attempts} accepted={accepted} rejected={rejected}"
    if cls == "harmful" and attempts >= int(min_attempts) and accepted == 0 and rejected >= int(min_rejected):
        return f"parameter_effect_memory_harmful_zero_acceptance attempts={attempts} accepted={accepted} rejected={rejected}"
    return ""


def build_memory_hard_blocked_transition_keys(
    effect_memory_state: Dict[str, Any],
) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    """Return transitions that must be blocked before scoring candidates."""
    blocked: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for entry in _effect_entries(effect_memory_state):
        if not isinstance(entry, dict):
            continue
        key = transition_key(entry.get("parameter"), entry.get("from_value"), entry.get("to_value"))
        if not key[0]:
            continue
        reason = parameter_effect_hard_block_reason(entry)
        if not reason:
            continue
        blocked[key] = {
            "reason": reason,
            "current_effect_class": clean_text(entry.get("current_effect_class", "")),
            "total_attempts": int(to_float(entry.get("total_attempts")) or 0),
            "accepted_count": int(to_float(entry.get("accepted_count")) or 0),
            "rejected_count": int(to_float(entry.get("rejected_count")) or 0),
            "last_run_ids": [clean_text(x) for x in (entry.get("last_run_ids") or []) if clean_text(x)][-6:],
        }
    return blocked


def default_subspace_cooldowns() -> Dict[str, Any]:
    return {
        "version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "default_cooldown_iterations": 8,
        "cooldowns": [],
    }


def _default_cooldown_entry(parameter: str, from_value: Any, to_value: Any) -> Dict[str, Any]:
    return {
        "parameter": clean_text(parameter),
        "from_value": normalize_scalar(from_value),
        "to_value": normalize_scalar(to_value),
        "cooldown_active": False,
        "cooldown_until_iteration": 0,
        "reason": "",
        "reject_ratio": 0.0,
        "last_run_ids": [],
        "override_only_if": "evidence_based_retry_explicit | new_parent_champion | orthogonal_context_change",
    }


def ensure_subspace_cooldowns(path: Path) -> Dict[str, Any]:
    data = load_json(path, {})
    if not isinstance(data, dict) or not data:
        data = default_subspace_cooldowns()
        save_json(path, data)
        return data
    if "version" not in data:
        data["version"] = 1
    if "updated_at" not in data:
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if "default_cooldown_iterations" not in data:
        data["default_cooldown_iterations"] = 8
    if "cooldowns" not in data or not isinstance(data.get("cooldowns"), list):
        data["cooldowns"] = []
    changed = False
    rows: List[Dict[str, Any]] = []
    for raw in data.get("cooldowns", []):
        if not isinstance(raw, dict):
            changed = True
            continue
        param = clean_text(raw.get("parameter", ""))
        from_value = normalize_scalar(raw.get("from_value"))
        to_value = normalize_scalar(raw.get("to_value"))
        if not param:
            changed = True
            continue
        defaults = _default_cooldown_entry(param, from_value, to_value)
        row = dict(raw)
        for k, v in defaults.items():
            if k not in row:
                row[k] = v
        row["parameter"] = param
        row["from_value"] = from_value
        row["to_value"] = to_value
        row["cooldown_active"] = bool(row.get("cooldown_active", False))
        row["cooldown_until_iteration"] = int(to_float(row.get("cooldown_until_iteration")) or 0)
        row["reject_ratio"] = round(float(to_float(row.get("reject_ratio")) or 0.0), 6)
        if not isinstance(row.get("last_run_ids"), list):
            row["last_run_ids"] = []
        row["last_run_ids"] = [clean_text(x) for x in (row.get("last_run_ids") or []) if clean_text(x)]
        rows.append(row)
    if rows != data.get("cooldowns", []):
        data["cooldowns"] = rows
        changed = True
    if changed:
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_json(path, data)
    return data


def _cooldown_entries(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = data.get("cooldowns", []) if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return []
    return rows


def get_subspace_cooldown_entry(
    data: Dict[str, Any],
    parameter: Any,
    from_value: Any,
    to_value: Any,
    create_if_missing: bool = False,
) -> Optional[Dict[str, Any]]:
    key = transition_key(parameter, from_value, to_value)
    for row in _cooldown_entries(data):
        row_key = transition_key(row.get("parameter"), row.get("from_value"), row.get("to_value"))
        if row_key == key:
            return row
    if not create_if_missing:
        return None
    row = _default_cooldown_entry(key[0], key[1], key[2])
    if "cooldowns" not in data or not isinstance(data.get("cooldowns"), list):
        data["cooldowns"] = []
    data["cooldowns"].append(row)
    return row


def get_active_cooldown_keys(cooldowns_state: Dict[str, Any], current_iteration: int) -> set[Tuple[str, str, str]]:
    active: set[Tuple[str, str, str]] = set()
    for row in _cooldown_entries(cooldowns_state):
        is_active = bool(row.get("cooldown_active", False))
        until_it = int(to_float(row.get("cooldown_until_iteration")) or 0)
        if is_active and int(current_iteration) <= until_it:
            active.add(transition_key(row.get("parameter"), row.get("from_value"), row.get("to_value")))
    return active


def build_parameter_effect_summary(effect_memory_state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in _effect_entries(effect_memory_state):
        p = clean_text(row.get("parameter", ""))
        if not p:
            continue
        if p not in out:
            out[p] = {
                "attempts": 0,
                "accepted": 0,
                "rejected": 0,
                "avg_delta_w52_spy_compare_acc": 0.0,
                "avg_delta_w52_spy_compare_n": 0,
                "harmful_like": 0,
                "strong_positive_like": 0,
            }
        rec = out[p]
        attempts = int(to_float(row.get("total_attempts")) or 0)
        rec["attempts"] += attempts
        rec["accepted"] += int(to_float(row.get("accepted_count")) or 0)
        rec["rejected"] += int(to_float(row.get("rejected_count")) or 0)
        d_spy = to_float(row.get("avg_delta_w52_spy_compare"))
        if d_spy is not None:
            rec["avg_delta_w52_spy_compare_acc"] += float(d_spy)
            rec["avg_delta_w52_spy_compare_n"] += 1
        effect_cls = clean_text(row.get("current_effect_class", ""))
        if effect_cls in {"harmful", "exhausted"}:
            rec["harmful_like"] += 1
        if effect_cls in {"strong_positive", "mild_positive"}:
            rec["strong_positive_like"] += 1
    for p, rec in out.items():
        n = int(rec.get("avg_delta_w52_spy_compare_n") or 0)
        rec["avg_delta_w52_spy_compare"] = round(
            (float(rec.get("avg_delta_w52_spy_compare_acc", 0.0)) / float(n)) if n > 0 else 0.0,
            6,
        )
        rec["accept_ratio"] = round(
            (float(rec.get("accepted", 0)) / float(rec.get("attempts", 0))) if int(rec.get("attempts", 0)) > 0 else 0.0,
            6,
        )
    return out


def default_branch_anchor_state() -> Dict[str, Any]:
    return {
        "active": False,
        "parameter": "",
        "value": None,
        "hold_iterations": 3,
        "remaining_iterations": 0,
        "activated_run_id": "",
        "activated_at": "",
        "reason": "",
        "locked_by_duplicate_throttling": False,
    }


def normalize_branch_anchor(anchor_value: Any) -> Dict[str, Any]:
    default_anchor = default_branch_anchor_state()
    anchor = anchor_value if isinstance(anchor_value, dict) else {}
    if not isinstance(anchor, dict):
        anchor = {}
    out = dict(default_anchor)
    for k in default_anchor.keys():
        if k in anchor:
            out[k] = anchor.get(k)
    out["active"] = bool(out.get("active", False))
    out["hold_iterations"] = max(1, int(to_float(out.get("hold_iterations")) or 3))
    out["remaining_iterations"] = max(0, int(to_float(out.get("remaining_iterations")) or 0))
    out["parameter"] = clean_text(out.get("parameter", ""))
    out["locked_by_duplicate_throttling"] = bool(out.get("locked_by_duplicate_throttling", False))
    if out["remaining_iterations"] <= 0:
        out["active"] = False
    if not out["active"]:
        out["remaining_iterations"] = 0
        out["locked_by_duplicate_throttling"] = False
    return out


def _parse_iso_ts(value: Any) -> Optional[datetime]:
    s = clean_text(value)
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def choose_canonical_branch_anchor(
    baseline_anchor: Any,
    research_anchor: Any,
) -> Dict[str, Any]:
    b = normalize_branch_anchor(baseline_anchor)
    r = normalize_branch_anchor(research_anchor)
    if b == r:
        return b
    b_active = bool(b.get("active", False))
    r_active = bool(r.get("active", False))
    if b_active and not r_active:
        return b
    if r_active and not b_active:
        return r
    if b_active and r_active:
        b_ts = _parse_iso_ts(b.get("activated_at"))
        r_ts = _parse_iso_ts(r.get("activated_at"))
        if b_ts and r_ts:
            return b if b_ts >= r_ts else r
        if b_ts and not r_ts:
            return b
        if r_ts and not b_ts:
            return r
        return r
    b_ts = _parse_iso_ts(b.get("activated_at"))
    r_ts = _parse_iso_ts(r.get("activated_at"))
    if b_ts and r_ts:
        return b if b_ts >= r_ts else r
    if b_ts and not r_ts:
        return b
    if r_ts and not b_ts:
        return r
    return r


def reconcile_branch_anchor_state(
    baseline: Dict[str, Any],
    research_state: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    baseline_anchor_raw = baseline.get("branch_anchor", {}) if isinstance(baseline, dict) else {}
    research_anchor_raw = research_state.get("branch_anchor", {}) if isinstance(research_state, dict) else {}
    canonical = choose_canonical_branch_anchor(baseline_anchor_raw, research_anchor_raw)

    changed = False
    # Baseline immutability: never write branch_anchor into baseline during normal runs.
    if normalize_branch_anchor(research_anchor_raw) != canonical:
        research_state["branch_anchor"] = dict(canonical)
        changed = True

    rs_branch = research_state.get("branch_state", {}) if isinstance(research_state.get("branch_state"), dict) else {}
    if not isinstance(rs_branch, dict):
        rs_branch = {}
    target_active = bool(canonical.get("active", False))
    target_param = clean_text(canonical.get("parameter", ""))
    target_value = canonical.get("value")
    target_hold = int(
        to_float(canonical.get("remaining_iterations"))
        or (to_float(canonical.get("hold_iterations")) if target_active else 0)
        or 0
    )
    if bool(rs_branch.get("branch_anchor_active", False)) != target_active:
        rs_branch["branch_anchor_active"] = target_active
        changed = True
    if clean_text(rs_branch.get("anchor_parameter", "")) != target_param:
        rs_branch["anchor_parameter"] = target_param
        changed = True
    if normalize_scalar(rs_branch.get("anchor_value")) != normalize_scalar(target_value):
        rs_branch["anchor_value"] = target_value
        changed = True
    if int(to_float(rs_branch.get("anchor_hold_iterations")) or 0) != target_hold:
        rs_branch["anchor_hold_iterations"] = target_hold
        changed = True
    research_state["branch_state"] = rs_branch

    return dict(canonical), changed


def get_branch_anchor_state(research_state: Dict[str, Any]) -> Dict[str, Any]:
    anchor = research_state.get("branch_anchor", {}) if isinstance(research_state, dict) else {}
    out = normalize_branch_anchor(anchor)
    return out


def evaluate_duplicate_throttling(
    rows: List[Dict[str, str]],
    current_status: str = "",
    lookback: int = 15,
) -> Dict[str, Any]:
    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = sorted_rows[-max(1, int(lookback)) :] if sorted_rows else []
    statuses = [clean_text(r.get("status", "")) for r in recent if clean_text(r.get("status", ""))]
    cs = clean_text(current_status)
    if cs:
        statuses.append(cs)
    total = len(statuses)
    blocked_duplicate = sum(1 for s in statuses if s == "blocked_duplicate")
    ratio = (blocked_duplicate / total) if total > 0 else 0.0
    active = bool(total >= 5 and ratio >= 0.20)
    return {
        "lookback": int(lookback),
        "window_count": total,
        "blocked_duplicate_count": blocked_duplicate,
        "blocked_duplicate_ratio": round(ratio, 6),
        "active": active,
    }


def evaluate_branch_anchor_conflict(
    proposal: Dict[str, Any],
    branch_anchor: Dict[str, Any],
) -> Dict[str, Any]:
    anchor = dict(branch_anchor or {})
    if not bool(anchor.get("active", False)):
        return {"blocked": False, "reasons": [], "details": []}
    remaining = int(to_float(anchor.get("remaining_iterations")) or 0)
    anchor_param = clean_text(anchor.get("parameter", ""))
    anchor_value_norm = normalize_scalar(anchor.get("value"))
    if remaining <= 0 or not anchor_param:
        return {"blocked": False, "reasons": [], "details": []}

    evidence_rollback = bool(proposal.get("revert_explicit", False)) and bool(clean_text(proposal.get("revert_justification", "")))
    details: List[Dict[str, Any]] = []
    reasons: List[str] = []
    forbidden_top_pairs = {(3, 4), (3, 5), (2, 5), (5, 2)}

    for role in ["main_change", "dependent_change"]:
        ch = proposal.get(role) or {}
        param = clean_text(ch.get("parameter", ""))
        if param != anchor_param:
            continue
        from_value = ch.get("from_value")
        to_value = ch.get("to_value")
        from_norm = normalize_scalar(from_value)
        to_norm = normalize_scalar(to_value)
        blocked = False
        reason = ""

        if to_norm != anchor_value_norm:
            blocked = True
            reason = (
                f"branch_anchor_locked:{param}:{from_norm}->{to_norm};"
                f"anchor={anchor_value_norm};remaining={remaining}"
            )

        if param == "TOP_CANDIDATES_NEXT_WEEK":
            fi = to_float(from_value)
            ti = to_float(to_value)
            if fi is not None and ti is not None:
                pair = (int(round(fi)), int(round(ti)))
                if pair in forbidden_top_pairs:
                    blocked = True
                    reason = f"branch_anchor_forbidden_transition:{param}:{pair[0]}->{pair[1]}"

        if blocked and evidence_rollback:
            blocked = False
            reason = f"branch_anchor_override:evidence_based_rollback:{param}:{from_norm}->{to_norm}"

        details.append(
            {
                "role": role,
                "parameter": param,
                "from_value": from_value,
                "to_value": to_value,
                "normalized_from_value": from_norm,
                "normalized_to_value": to_norm,
                "anchor_value": anchor.get("value"),
                "anchor_remaining_iterations": remaining,
                "blocked": blocked,
                "reason": reason,
            }
        )
        if blocked and reason:
            reasons.append(reason)

    return {"blocked": len(reasons) > 0, "reasons": reasons, "details": details}


def should_activate_branch_anchor(
    decision_type: str,
    compare_obj: Dict[str, Any],
    proposal: Optional[Dict[str, Any]],
    rows: List[Dict[str, str]],
) -> Dict[str, Any]:
    p = proposal or {}
    main = p.get("main_change") or {}
    param = clean_text(main.get("parameter", ""))
    from_value = main.get("from_value")
    to_value = main.get("to_value")
    if not param:
        return {
            "activate": False,
            "reason": "",
            "parameter": "",
            "anchor_value": None,
            "hold_iterations": 3,
            "trigger": "none",
        }

    vs_last = (compare_obj.get("vs_last_valid_w52", {}) if isinstance(compare_obj, dict) else {}) or {}
    delta_spy = to_float(((vs_last.get("spy_compare") or {}).get("delta")))

    cond_promoted = decision_type == "promoted_to_baseline"
    cond_followup_spy = decision_type == "accepted_for_followup" and (delta_spy is not None and delta_spy > 0.05)

    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = sorted_rows[-12:] if sorted_rows else []
    target_norm = normalize_scalar(to_value)
    direction = None
    f_num = to_float(from_value)
    t_num = to_float(to_value)
    if f_num is not None and t_num is not None and t_num != f_num:
        direction = 1 if (t_num - f_num) > 0 else -1
    same_value_improve = 0
    same_direction_improve = 0
    for r in recent:
        if clean_text(r.get("accepted_or_rejected", "")).lower() != "accepted":
            continue
        if clean_text(r.get("main_parameter", "")) != param:
            continue
        spy = to_float(r.get("w52_spy_compare"))
        if spy is None or spy <= 0:
            continue
        if normalize_scalar(r.get("main_to")) == target_norm:
            same_value_improve += 1
        if direction is not None:
            rf = to_float(r.get("main_from"))
            rt = to_float(r.get("main_to"))
            if rf is not None and rt is not None and rt != rf:
                rdir = 1 if (rt - rf) > 0 else -1
                if rdir == direction:
                    same_direction_improve += 1
    cond_repeated = same_value_improve >= 2 or same_direction_improve >= 2

    activate = bool(cond_promoted or cond_followup_spy or cond_repeated)
    trigger = "none"
    if cond_promoted:
        trigger = "promoted_to_baseline"
    elif cond_followup_spy:
        trigger = "accepted_for_followup_w52_spy_improved"
    elif cond_repeated:
        trigger = "repeated_useful_direction"

    # Respetar valor persistido real del ancla; sin hardcodes por parámetro.
    anchor_value: Any = to_value

    return {
        "activate": activate,
        "reason": (
            f"trigger={trigger}; param={param}; to={normalize_scalar(anchor_value)}; "
            f"same_value_improve={same_value_improve}; same_direction_improve={same_direction_improve}"
            if activate
            else ""
        ),
        "parameter": param,
        "anchor_value": anchor_value,
        "hold_iterations": 3,
        "trigger": trigger,
        "same_value_improve": same_value_improve,
        "same_direction_improve": same_direction_improve,
    }


def initialize_test_queue(path: Path) -> None:
    if path.exists():
        return
    queue = [
        {
            "id": "TEST_A",
            "status": "pending",
            "objective": "Probar de forma real si limitar extension mejora la calidad del basket.",
            "main_change": {
                "parameter": "ENABLE_CLOSE_VS_SMA50_FILTER",
                "to_value": True,
                "meaning": "Activa filtro de extension por SMA50.",
                "purpose": "Evitar candidatos sobre-extendidos.",
                "why_improve": "Puede mejorar calidad del basket.",
            },
            "dependent_change": {
                "parameter": "MAX_CLOSE_VS_SMA50_PCT",
                "to_value": 0.5,
                "dependency_reason": "semantic_scale_metric",
                "meaning": "Umbral operativo del filtro activado.",
            },
            "expected_effect": "Menor ruido de basket, con posible costo de frecuencia.",
        },
        {
            "id": "TEST_B",
            "status": "pending",
            "objective": "Probar de forma limpia si zscore_distance mejora matching y ranking interno.",
            "main_change": {
                "parameter": "PROFILE_MODE",
                "to_value": "zscore_distance",
                "meaning": "Cambia la metrica de distancia del perfil.",
                "purpose": "Evaluar matching continuo por z-score.",
                "why_improve": "Podria mejorar discriminacion del ranking.",
            },
            "dependent_change": {
                "parameter": "ENABLE_AVG_PROFILE_DISTANCE_GATE",
                "to_value": False,
                "dependency_reason": "semantic_scale_metric",
                "meaning": "Desactivar temporalmente gate dependiente para test valido.",
            },
            "expected_effect": "Aislar impacto del nuevo PROFILE_MODE sin sesgo de gate no recalibrado.",
        },
    ]
    save_json(path, queue)


def validate_main_change_materiality(proposal: Dict[str, Any]) -> Dict[str, Any]:
    main = proposal.get("main_change") or {}
    param = clean_text(main.get("parameter", ""))
    from_value = main.get("from_value")
    to_value = main.get("to_value")
    normalized_from = normalize_scalar(from_value)
    normalized_to = normalize_scalar(to_value)
    is_material = bool(param) and normalized_from != normalized_to
    invalid_no_op = bool(param) and not is_material
    error = ""
    if invalid_no_op:
        error = f"proposal_main_change_no_op:{param}:{normalized_from}->{normalized_to}"
    return {
        "main_parameter": param,
        "from_value": from_value,
        "to_value": to_value,
        "normalized_from_value": normalized_from,
        "normalized_to_value": normalized_to,
        "material_change_detected": is_material,
        "invalid_no_op": invalid_no_op,
        "error": error,
    }


def _next_change_dependency_requirement(parameter: str) -> Tuple[str, Any, str]:
    param = clean_text(parameter)
    dependency_map = {
        "MAX_CLOSE_VS_SMA50_PCT": ("ENABLE_CLOSE_VS_SMA50_FILTER", True, "semantic_scale_metric"),
        "MIN_SPY_CHANNEL_R2": ("ENABLE_SPY_CHANNEL_R2_GATE", True, "semantic_scale_metric"),
        "MAX_AVG_PROFILE_DISTANCE": ("ENABLE_AVG_PROFILE_DISTANCE_GATE", True, "semantic_scale_metric"),
    }
    return dependency_map.get(param, ("", None, ""))


def ensure_analyst_output_contract(proposal: Dict[str, Any], windows: List[int]) -> Dict[str, Any]:
    out = dict(proposal or {})
    main = out.get("main_change")
    main_param = clean_text((main or {}).get("parameter", "")) if isinstance(main, dict) else ""
    if not clean_text(out.get("status", "")):
        out["status"] = "proposal_ready" if main_param else "no_material_candidate_found"
    if not clean_text(out.get("role", "")):
        out["role"] = "analyst"
    if not clean_text(out.get("research_mode_context", "")):
        afu = out.get("auditor_feedback_used", {}) if isinstance(out.get("auditor_feedback_used"), dict) else {}
        out["research_mode_context"] = normalize_research_mode(
            map_recommended_action_to_mode(afu.get("recommended_next_action", "refine_current_branch"))
        )
    if not clean_text(out.get("mode", "")):
        out["mode"] = mode_to_analyst_style(clean_text(out.get("research_mode_context", "")) or "refine_current_branch")
    if not clean_text(out.get("change_intent", "")):
        out["change_intent"] = infer_change_intent_from_mode(clean_text(out.get("research_mode_context", "")))
    if not clean_text(out.get("source", "")):
        out["source"] = "adaptive_fallback"
    if not clean_text(out.get("proposal_source", "")):
        out["proposal_source"] = clean_text(out.get("source", "")) or "adaptive_fallback"

    fd = out.get("fallback_diagnosis", {}) if isinstance(out.get("fallback_diagnosis"), dict) else {}
    impl = out.get("implementation_check") if isinstance(out.get("implementation_check"), dict) else {}
    out["implementation_check"] = {
        "flags_verified": list(impl.get("flags_verified", []) or []),
        "gates_verified": list(impl.get("gates_verified", []) or []),
        "inactive_logic_detected": list(impl.get("inactive_logic_detected", []) or []),
        "notes": clean_text(impl.get("notes", "")) or clean_text(fd.get("implementation_check", "")),
    }

    ev = out.get("evidence_summary") if isinstance(out.get("evidence_summary"), dict) else {}
    out["evidence_summary"] = {
        "good_vs_bad_weeks": clean_text(ev.get("good_vs_bad_weeks", "")) or clean_text(fd.get("good_vs_bad_weeks", "")),
        "winners_vs_losers": clean_text(ev.get("winners_vs_losers", "")) or clean_text(fd.get("winners_vs_losers", "")),
        "rank_degradation": clean_text(ev.get("rank_degradation", "")) or clean_text(fd.get("rank_degradation", "")),
        "individual_candidate_findings": clean_text(ev.get("individual_candidate_findings", "")),
        "parent_vs_baseline": clean_text(ev.get("parent_vs_baseline", "")) or clean_text(fd.get("parent_vs_baseline", "")),
    }

    if not clean_text(out.get("problem_layer", "")):
        if clean_text(out.get("status", "")) == "no_material_candidate_found":
            afu = out.get("auditor_feedback_used", {}) if isinstance(out.get("auditor_feedback_used"), dict) else {}
            main_friction = clean_text(afu.get("main_friction", ""))
            out["problem_layer"] = "process_blocked" if main_friction and main_friction != "none" else "mixed"
        elif main_param in {"TOP_CANDIDATES_NEXT_WEEK"}:
            out["problem_layer"] = "basket_quality"
        elif main_param in {"MAX_CLOSE_VS_SMA50_PCT", "ENABLE_CLOSE_VS_SMA50_FILTER"}:
            out["problem_layer"] = "individual_candidate_quality"
        elif main_param:
            out["problem_layer"] = "weekly_regime"
        else:
            out["problem_layer"] = "mixed"

    if "optional_secondary_change" not in out or not isinstance(out.get("optional_secondary_change"), dict):
        out["optional_secondary_change"] = {
            "parameter": "",
            "from_value": None,
            "to_value": None,
            "dependency_reason": "",
            "meaning": "",
        }

    if not clean_text(out.get("why_this_and_not_other_change", "")):
        out["why_this_and_not_other_change"] = clean_text(out.get("fallback_selected_reason", ""))

    if not isinstance(out.get("compare_windows"), list) or not out.get("compare_windows"):
        out["compare_windows"] = [int(w) for w in windows]
    if "compare_vs_spy" not in out:
        out["compare_vs_spy"] = True
    if "prioritize_robustness_over_short_term" not in out:
        out["prioritize_robustness_over_short_term"] = True
    if "fallback_candidate_pool_considered" not in out or not isinstance(out.get("fallback_candidate_pool_considered"), list):
        out["fallback_candidate_pool_considered"] = []
    if "fallback_selected_reason" not in out:
        out["fallback_selected_reason"] = ""
    if "selection_trace" not in out or not isinstance(out.get("selection_trace"), dict):
        out["selection_trace"] = {
            "current_mode": normalize_research_mode(clean_text(out.get("research_mode_context", ""))),
            "change_intent": clean_text(out.get("change_intent", "")),
            "selection_reason": clean_text(out.get("fallback_selected_reason", "")),
            "orthogonal_force_active": False,
            "recommended_change_directions": [],
            "historical_memory_used": {},
            "alternatives_discarded": [],
        }

    if "proposal_validation" not in out or not isinstance(out.get("proposal_validation"), dict):
        out["proposal_validation"] = validate_main_change_materiality(out)
    return out


def build_no_material_candidate_proposal(
    parent_cfg: Dict[str, Any],
    last_valid_ctx: Optional[Dict[str, Any]],
    windows: List[int],
    source: str,
    diagnosis: str,
    reason: str,
    current_mode: str = "refine_current_branch",
    fallback_diagnosis: Optional[Dict[str, Any]] = None,
    fallback_candidate_pool_considered: Optional[List[Dict[str, Any]]] = None,
    candidate_generation_diagnostic_output: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    last_run_id = ""
    if last_valid_ctx:
        last_run_id = str(last_valid_ctx.get("run_id", ""))
    if fallback_diagnosis is None:
        fallback_diagnosis = {}
    if fallback_candidate_pool_considered is None:
        fallback_candidate_pool_considered = []
    return {
        "role": "analyst",
        "status": "no_material_candidate_found",
        "proposal_status": "no_material_candidate_found",
        "mode": mode_to_analyst_style(current_mode),
        "research_mode_context": normalize_research_mode(current_mode),
        "change_intent": infer_change_intent_from_mode(current_mode),
        "source": source,
        "queue_test_id": "",
        "parent_run_id": last_run_id,
        "analysis_reference_run_id": last_run_id,
        "diagnosis": diagnosis,
        "hypothesis": reason,
        "main_change": None,
        "dependent_change": None,
        "expected_effect": "Sin propuesta valida: se evita emitir no-op.",
        "compare_windows": windows,
        "compare_vs_spy": True,
        "prioritize_robustness_over_short_term": True,
        "revert_explicit": False,
        "revert_justification": "",
        "proposal_config": dict(parent_cfg),
        "fallback_diagnosis": fallback_diagnosis,
        "fallback_candidate_pool_considered": fallback_candidate_pool_considered,
        "fallback_selected_reason": reason,
        "candidate_generation_diagnostic_output": candidate_generation_diagnostic_output or {},
        "next_change_present": False,
        "next_change_consumed": False,
        "next_change_rejected": False,
        "next_change_rejected_reason": "",
        "next_change_zigzag_override": False,
        "next_change_zigzag_override_reason": "",
        "next_change_recent_feedback_override": False,
        "recent_feedback_ignored_reason": "",
        "original_recent_feedback_reason": "",
        "original_rejection_reason": "",
        "next_change_parameter": "",
        "next_change_from": None,
        "next_change_to": None,
        "selection_trace": {
            "current_mode": normalize_research_mode(current_mode),
            "change_intent": infer_change_intent_from_mode(current_mode),
            "selection_reason": reason,
            "orthogonal_force_active": bool((fallback_diagnosis or {}).get("orthogonal_force_active", False)),
            "recommended_change_directions": sanitize_text_list((fallback_diagnosis or {}).get("recommended_change_directions", []) or [])[:3],
            "historical_memory_used": {
                "parameter_effect_summary_top": ((fallback_diagnosis or {}).get("parameter_effect_memory_used", []) or [])[:5],
                "active_cooldown_subspaces": ((fallback_diagnosis or {}).get("active_cooldown_subspaces", []) or [])[:8],
            },
            "alternatives_discarded": [],
        },
    }


def apply_next_change_trace(proposal: Dict[str, Any], next_change_audit: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(proposal or {})
    audit = dict(next_change_audit or {})
    next_change_present = bool(audit.get("next_change_present", False))
    if not next_change_present:
        next_change_present = bool(
            clean_text(audit.get("next_change_parameter", ""))
            or audit.get("next_change_from") is not None
            or audit.get("next_change_to") is not None
        )

    out.update(
        {
            "next_change_present": next_change_present,
            "next_change_consumed": bool(audit.get("next_change_consumed", False)),
            "next_change_rejected": bool(audit.get("next_change_rejected", False)),
            "next_change_rejected_reason": clean_text(audit.get("next_change_rejected_reason", "")),
            "next_change_zigzag_override": bool(audit.get("next_change_zigzag_override", False)),
            "next_change_zigzag_override_reason": clean_text(audit.get("next_change_zigzag_override_reason", "")),
            "next_change_recent_feedback_override": bool(audit.get("next_change_recent_feedback_override", False)),
            "recent_feedback_ignored_reason": clean_text(audit.get("recent_feedback_ignored_reason", "")),
            "original_recent_feedback_reason": clean_text(audit.get("original_recent_feedback_reason", "")),
            "original_rejection_reason": clean_text(audit.get("original_rejection_reason", "")),
            "next_change_parameter": clean_text(audit.get("next_change_parameter", "")),
            "next_change_from": audit.get("next_change_from"),
            "next_change_to": audit.get("next_change_to"),
        }
    )
    if next_change_present:
        if bool(out.get("next_change_consumed", False)):
            out["proposal_source"] = "next_change"
        elif bool(out.get("next_change_rejected", False)):
            out["proposal_source"] = "fallback_after_next_change_rejected"

    cgd = out.get("candidate_generation_diagnostic_output")
    if isinstance(cgd, dict):
        cgd.update(
            {
                "next_change_present": next_change_present,
                "next_change_consumed": bool(out.get("next_change_consumed", False)),
                "next_change_rejected": bool(out.get("next_change_rejected", False)),
                "next_change_rejected_reason": clean_text(out.get("next_change_rejected_reason", "")),
                "next_change_zigzag_override": bool(out.get("next_change_zigzag_override", False)),
                "next_change_zigzag_override_reason": clean_text(out.get("next_change_zigzag_override_reason", "")),
                "next_change_recent_feedback_override": bool(out.get("next_change_recent_feedback_override", False)),
                "recent_feedback_ignored_reason": clean_text(out.get("recent_feedback_ignored_reason", "")),
                "original_recent_feedback_reason": clean_text(out.get("original_recent_feedback_reason", "")),
                "original_rejection_reason": clean_text(out.get("original_rejection_reason", "")),
                "next_change_parameter": clean_text(out.get("next_change_parameter", "")),
                "next_change_from": out.get("next_change_from"),
                "next_change_to": out.get("next_change_to"),
                "proposal_source": clean_text(out.get("proposal_source", "")),
            }
        )
        out["candidate_generation_diagnostic_output"] = cgd
    return out


def get_window_metrics_from_ctx(ctx: Optional[Dict[str, Any]], window: int) -> Dict[str, Any]:
    if not ctx:
        return {}
    eo = ctx.get("executor_output") or {}
    return (eo.get("windows", {}).get(str(window), {}) or {}).get("metrics", {}) or {}


def evaluate_startup_parent_depth_guard_52w(candidate_ctx: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    metrics_52 = get_window_metrics_from_ctx(candidate_ctx, 52)
    weeks_traded = to_float(metrics_52.get("weeks_traded"))
    trades = to_float(metrics_52.get("trades"))
    excluded_ratio = None
    if weeks_traded is not None and float(weeks_traded) >= 0:
        excluded_ratio = max(0.0, 1.0 - (float(weeks_traded) / 52.0))

    weeks_ok = weeks_traded is not None and float(weeks_traded) >= 20.0
    trades_ok = trades is not None and float(trades) >= 15.0
    excluded_ok = excluded_ratio is not None and float(excluded_ratio) <= 0.50
    passed = bool(weeks_ok and trades_ok and excluded_ok)

    blockers: List[str] = []
    if not weeks_ok:
        blockers.append("w52_weeks_traded_below_parent_minimum")
    if not trades_ok:
        blockers.append("w52_trades_below_parent_minimum")
    if not excluded_ok:
        blockers.append("w52_excluded_ratio_above_parent_maximum")

    run_id = clean_text((candidate_ctx or {}).get("run_id", ""))
    return {
        "pass": passed,
        "reason": "" if passed else "startup_parent_rejected_low_depth_52w",
        "run_id": run_id,
        "weeks_traded": weeks_traded,
        "trades": trades,
        "excluded_ratio": (round(float(excluded_ratio), 6) if excluded_ratio is not None else None),
        "blockers": blockers,
    }


def diagnose_parent_outcome_for_fallback(
    parent_metrics: Dict[str, Any],
    compare_vs_parent: Optional[Dict[str, Any]],
    compare_vs_spy: Optional[float],
) -> Dict[str, Any]:
    compare_vs_parent = compare_vs_parent or {}
    weeks_traded = to_float(parent_metrics.get("weeks_traded")) or 0.0
    trades = to_float(parent_metrics.get("trades")) or 0.0
    avg_ret = to_float(parent_metrics.get("avg_net_return_pct")) or 0.0
    spy_cmp_metric = to_float(parent_metrics.get("spy_compare"))
    spy_cmp = to_float(compare_vs_spy)
    if spy_cmp is None:
        spy_cmp = spy_cmp_metric if spy_cmp_metric is not None else 0.0

    delta_avg = to_float((compare_vs_parent.get("avg_net_return_pct") or {}).get("delta"))
    delta_spy = to_float((compare_vs_parent.get("spy_compare") or {}).get("delta"))
    parent_recently_rejected = bool(compare_vs_parent.get("parent_recently_rejected", False))

    category = "no_clear_signal"
    reason = "No hay una señal dominante; conviene un ajuste conservador y material."

    if weeks_traded <= 12 and avg_ret >= 1.0 and spy_cmp > 0:
        category = "low_frequency_high_quality"
        reason = "Poca frecuencia pero calidad aceptable: conviene alivio controlado de filtros."
    elif weeks_traded >= 24 and (avg_ret < 0.7 or spy_cmp <= 0):
        category = "high_frequency_low_edge"
        reason = "Alta frecuencia con edge debil: conviene tightening de calidad."
    elif spy_cmp <= 0:
        category = "weak_vs_spy"
        reason = "Debilidad vs SPY: conviene priorizar mejoras de edge."
    elif (delta_avg is not None and delta_avg < 0) and (delta_spy is not None and delta_spy < 0):
        category = "mixed_quality"
        reason = "El edge reciente se deterioro: conviene refinamiento de calidad."
    elif parent_recently_rejected and (delta_spy is not None and delta_spy < 0):
        category = "mixed_quality"
        reason = "La ultima rama desde este parent deterioro vs SPY: conviene evitar repetir y priorizar calidad."

    return {
        "category": category,
        "reason": reason,
        "metrics_snapshot": {
            "weeks_traded_52": weeks_traded,
            "trades_52": trades,
            "avg_net_return_pct_52": avg_ret,
            "spy_compare_52": spy_cmp,
            "delta_avg_net_return_pct_vs_parent_52": delta_avg,
            "delta_spy_compare_vs_parent_52": delta_spy,
        },
    }


def compose_fallback_diagnosis_contract(
    parent_cfg: Dict[str, Any],
    fallback_diagnosis: Dict[str, Any],
    behavior_diag: Dict[str, Any],
    analysis_reference_run_id: str,
    parent_w24: Dict[str, Any],
    parent_w52: Dict[str, Any],
) -> Dict[str, Any]:
    def _fmt(v: Any) -> str:
        t = clean_text(v)
        return t if t else "n/a"

    impl_parts: List[str] = []
    for flag, value_key in [
        ("ENABLE_SPY_CHANNEL_R2_GATE", "MIN_SPY_CHANNEL_R2"),
        ("ENABLE_AVG_PROFILE_DISTANCE_GATE", "MAX_AVG_PROFILE_DISTANCE"),
        ("ENABLE_CLOSE_VS_SMA50_FILTER", "MAX_CLOSE_VS_SMA50_PCT"),
    ]:
        enabled = normalize_scalar(parent_cfg.get(flag)) == "true"
        impl_parts.append(f"{flag}={'ON' if enabled else 'OFF'}")
        if enabled:
            impl_parts.append(f"{value_key}={_fmt(parent_cfg.get(value_key))}")

    week_split = behavior_diag.get("week_quality_split", {}) if isinstance(behavior_diag, dict) else {}
    trade_split = behavior_diag.get("trade_quality_split", {}) if isinstance(behavior_diag, dict) else {}
    rank_diag = behavior_diag.get("rank_degradation", {}) if isinstance(behavior_diag, dict) else {}
    gate_diag = behavior_diag.get("gate_activity_check", {}) if isinstance(behavior_diag, dict) else {}

    good_bad_txt = (
        f"available={bool(week_split.get('available', False))}; "
        f"good_weeks={_fmt(week_split.get('good_weeks_count'))}; "
        f"bad_weeks={_fmt(week_split.get('bad_weeks_count'))}; "
        f"notes=feature_stats_present={bool((week_split.get('feature_stats') or {}))}"
    )
    winners_losers_txt = (
        f"available={bool(trade_split.get('available', False))}; "
        f"winners={_fmt(trade_split.get('winners_count'))}; "
        f"losers={_fmt(trade_split.get('losers_count'))}; "
        f"ties_rule=0-1pct"
    )
    rank_txt = (
        f"available={bool(rank_diag.get('available', False))}; "
        f"rapid_degradation={bool(rank_diag.get('rapid_degradation', False))}; "
        f"ranks={_fmt(len(rank_diag.get('by_rank', []) if isinstance(rank_diag.get('by_rank', []), list) else []))}"
    )
    parent_baseline_txt = (
        f"analysis_reference_run_id={_fmt(analysis_reference_run_id)}; "
        f"parent_w24_spy={_fmt(parent_w24.get('spy_compare'))}; "
        f"parent_w52_spy={_fmt(parent_w52.get('spy_compare'))}; "
        f"parent_w52_avg_net={_fmt(parent_w52.get('avg_net_return_pct'))}"
    )

    contract = {
        "implementation_check": "; ".join(impl_parts),
        "good_vs_bad_weeks": good_bad_txt,
        "winners_vs_losers": winners_losers_txt,
        "rank_degradation": rank_txt,
        "parent_vs_baseline": parent_baseline_txt,
        "gate_activity_snapshot": gate_diag,
        "category": clean_text(fallback_diagnosis.get("category", "")),
        "reason": clean_text(fallback_diagnosis.get("reason", "")),
        "metrics_snapshot": fallback_diagnosis.get("metrics_snapshot", {}),
        "second_layer_required": bool(fallback_diagnosis.get("second_layer_required", False)),
        "second_layer_executed": bool(fallback_diagnosis.get("second_layer_executed", False)),
    }
    return contract


def collect_recent_coordinator_feedback(rows: List[Dict[str, str]], lookback: int = 20) -> Dict[str, Any]:
    sorted_rows = sorted(rows, key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = list(reversed(sorted_rows[-lookback:])) if sorted_rows else []
    blocked_statuses = {
        "blocked_no_op",
        "blocked_zigzag",
        "blocked_duplicate",
        "blocked_preflight",
        "blocked_branch_anchor",
        "no_material_candidate_found",
        "blocked_no_material_candidate",
    }
    blocked_transitions: set[Tuple[str, str, str]] = set()
    blocked_transition_details: List[Dict[str, str]] = []
    rejected_executed_transitions: set[Tuple[str, str, str]] = set()
    blocked_notes: List[str] = []
    for r in recent:
        status = clean_text(r.get("status", ""))
        if status not in blocked_statuses:
            # Registrar también transiciones ejecutadas y rechazadas para evitar
            # reciclar subespacios que no están aportando aprendizaje.
            accepted_flag = clean_text(r.get("accepted_or_rejected", "")).lower()
            if status in {"run_ok", "run_partial_valid"} and accepted_flag == "rejected":
                param_exec = clean_text(r.get("main_parameter", ""))
                to_norm_exec = normalize_scalar(r.get("main_to"))
                from_norm_exec = normalize_scalar(r.get("main_from"))
                if param_exec:
                    rejected_executed_transitions.add((param_exec, from_norm_exec, to_norm_exec))
            continue
        param = clean_text(r.get("main_parameter", ""))
        from_norm = normalize_scalar(r.get("main_from"))
        to_norm = normalize_scalar(r.get("main_to"))
        if param:
            blocked_transitions.add((param, to_norm, status))
        note = clean_text(r.get("notes", ""))
        if param:
            blocked_transition_details.append(
                {
                    "run_id": clean_text(r.get("run_id", "")),
                    "parameter": param,
                    "from": from_norm,
                    "to": to_norm,
                    "status": status,
                    "reason": note,
                }
            )
        if note:
            blocked_notes.append(note)
    return {
        "recent_blocked_transitions": blocked_transitions,
        "recent_blocked_transition_details": blocked_transition_details,
        "recent_rejected_executed_transitions": rejected_executed_transitions,
        "recent_blocked_notes": blocked_notes[:10],
        "recent_rows_count": len(recent),
    }


def is_recent_feedback_only_zigzag_for_same_next_change(
    recent_feedback: Dict[str, Any],
    parameter: str,
    from_value: Any,
    to_value: Any,
    next_change: Dict[str, Any],
) -> Dict[str, Any]:
    param = clean_text(parameter)
    from_norm = normalize_scalar(from_value)
    to_norm = normalize_scalar(to_value)
    details = recent_feedback.get("recent_blocked_transition_details", []) if isinstance(recent_feedback, dict) else []
    if not isinstance(details, list):
        details = []

    matching_param_to = [
        d for d in details
        if clean_text(d.get("parameter", "")) == param and normalize_scalar(d.get("to")) == to_norm
    ]
    if not matching_param_to:
        legacy_matches = [
            x for x in (recent_feedback.get("recent_blocked_transitions", set()) if isinstance(recent_feedback, dict) else set())
            if len(x) >= 3 and clean_text(x[0]) == param and normalize_scalar(x[1]) == to_norm
        ]
        matching_param_to = [
            {
                "run_id": "",
                "parameter": param,
                "from": "",
                "to": to_norm,
                "status": clean_text(x[2]),
                "reason": "",
            }
            for x in legacy_matches
        ]
    if not matching_param_to:
        return {"allowed": False, "reason": "no_matching_recent_feedback", "original_reason": ""}

    same_transition = [d for d in matching_param_to if normalize_scalar(d.get("from")) == from_norm]
    if not same_transition:
        return {
            "allowed": False,
            "reason": "recent_feedback_different_transition",
            "original_reason": "; ".join(
                f"{clean_text(d.get('run_id', ''))}:{clean_text(d.get('status', ''))}:{clean_text(d.get('reason', ''))}"
                for d in matching_param_to
            ),
        }

    override_reason = clean_text(next_change.get("override_reason", "")) or clean_text(next_change.get("evidence_reason", ""))
    evidence_items = next_change.get("evidence", [])
    has_override = bool(next_change.get("allow_zigzag_countermove", False)) and bool(override_reason)
    has_evidence = isinstance(evidence_items, list) and bool(evidence_items)
    if not has_override or not has_evidence:
        return {
            "allowed": False,
            "reason": "missing_zigzag_override_evidence",
            "original_reason": "; ".join(
                f"{clean_text(d.get('run_id', ''))}:{clean_text(d.get('status', ''))}:{clean_text(d.get('reason', ''))}"
                for d in same_transition
            ),
        }

    if any(clean_text(d.get("status", "")) != "blocked_zigzag" for d in same_transition):
        return {
            "allowed": False,
            "reason": "recent_feedback_has_non_zigzag_block",
            "original_reason": "; ".join(
                f"{clean_text(d.get('run_id', ''))}:{clean_text(d.get('status', ''))}:{clean_text(d.get('reason', ''))}"
                for d in same_transition
            ),
        }

    original_reason = "; ".join(
        f"{clean_text(d.get('run_id', ''))}:{clean_text(d.get('status', ''))}:{clean_text(d.get('reason', ''))}"
        for d in same_transition
    )
    return {
        "allowed": True,
        "reason": "previous_blocked_zigzag_same_transition_with_evidence_override",
        "original_reason": original_reason,
    }


def detect_recent_exhausted_subspaces(
    rows: List[Dict[str, str]],
    parent_run_id: str = "",
    lookback: int = 50,
    min_repeats: int = 3,
    min_reject_ratio: float = 0.75,
) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    """
    Detecta transiciones repetidas con bajo valor incremental reciente.
    Key: (parameter, normalized_from, normalized_to)

    Parent is intentionally ignored for this guardrail. Parent selection and
    duplicate/cooldown blocking serve different purposes: rejected transitions
    should be blocked globally in the lookback window even if parent_run_id is
    stale or inconsistent across trackers.
    """
    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = sorted_rows[-max(1, int(lookback)) :] if sorted_rows else []
    stats: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for r in recent:
        status = clean_text(r.get("status", ""))
        if status not in {"run_ok", "run_partial_valid"}:
            continue
        param = clean_text(r.get("main_parameter", ""))
        if not param:
            continue
        f_norm = normalize_scalar(r.get("main_from"))
        t_norm = normalize_scalar(r.get("main_to"))
        key = (param, f_norm, t_norm)
        if key not in stats:
            stats[key] = {
                "count": 0,
                "rejected": 0,
                "accepted": 0,
                "run_ids": [],
                "latest_status": "",
            }
        entry = stats[key]
        entry["count"] = int(entry.get("count", 0)) + 1
        accepted_flag = clean_text(r.get("accepted_or_rejected", "")).lower()
        if accepted_flag == "accepted":
            entry["accepted"] = int(entry.get("accepted", 0)) + 1
        else:
            entry["rejected"] = int(entry.get("rejected", 0)) + 1
        rid = clean_text(r.get("run_id", ""))
        if rid:
            entry["run_ids"] = (entry.get("run_ids") or []) + [rid]
        entry["latest_status"] = status

    exhausted: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for key, entry in stats.items():
        count = int(entry.get("count", 0))
        if count < int(min_repeats):
            continue
        rejected = int(entry.get("rejected", 0))
        ratio = (rejected / count) if count > 0 else 0.0
        if ratio < float(min_reject_ratio):
            continue
        exhausted[key] = {
            **entry,
            "reject_ratio": round(ratio, 6),
        }
    return exhausted


def _safe_mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return float(sum(values) / len(values))


def load_parent_behavior_diagnostics(
    last_valid_ctx: Optional[Dict[str, Any]],
    tie_low: float = 0.0,
    tie_high: float = 1.0,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "status": "not_available",
        "source_run_id": clean_text((last_valid_ctx or {}).get("run_id", "")),
        "rank_degradation": {"available": False, "rapid_degradation": False, "by_rank": []},
        "week_quality_split": {"available": False},
        "trade_quality_split": {"available": False},
        "gate_activity_check": {"available": False},
        "diagnostic_notes": [],
    }
    if not last_valid_ctx:
        out["diagnostic_notes"].append("No hay parent valido para analisis de segunda capa.")
        return out

    try:
        import pandas as pd  # Lazy import
    except Exception:
        out["diagnostic_notes"].append("pandas no disponible para diagnostico de segunda capa.")
        return out

    windows = (last_valid_ctx.get("executor_output") or {}).get("windows", {}) or {}
    preferred = ["52", "24", "8", "4", "156"]
    xlsx_path: Optional[Path] = None
    artifacts_dir: Optional[Path] = None
    for k in preferred + sorted(list(windows.keys())):
        payload = windows.get(str(k), {}) or {}
        p = Path(str((payload.get("outputs") or {}).get("excel", "")))
        if p.exists():
            xlsx_path = p
            break
        ad = Path(str((payload.get("outputs") or {}).get("artifacts_dir", "")))
        if artifacts_dir is None and ad.exists():
            artifacts_dir = ad
    if artifacts_dir is None:
        for k in preferred + sorted(list(windows.keys())):
            payload = windows.get(str(k), {}) or {}
            ad = Path(str((payload.get("outputs") or {}).get("artifacts_dir", "")))
            if ad.exists():
                artifacts_dir = ad
                break

    def _load_df(sheet_name: str, stem_name: str) -> pd.DataFrame:
        if xlsx_path is not None:
            try:
                return pd.read_excel(xlsx_path, sheet_name=sheet_name)
            except Exception:
                pass
        if artifacts_dir is not None:
            csv_p = find_latest_csv_for_stem(artifacts_dir, stem_name)
            if csv_p is not None and csv_p.exists():
                try:
                    return pd.read_csv(csv_p, sep=";", decimal=",")
                except Exception:
                    return pd.DataFrame()
        return pd.DataFrame()

    weekly_df = _load_df("08_summary_by_regime_week", "08_summary_by_regime_week")
    trades_df = _load_df("07_next_week_real_trades", "07_next_week_real_trades")
    candidates_df = _load_df("06_next_week_candidates", "06_next_week_candidates")
    if weekly_df.empty and trades_df.empty and candidates_df.empty:
        out["diagnostic_notes"].append("No se encontraron artefactos validos del parent (xlsx/csv) para diagnostico de segunda capa.")
        return out

    # Weeks: buenas vs malas
    if not weekly_df.empty and "avg_net_return_pct" in weekly_df.columns:
        w = weekly_df.copy()
        w["avg_net_return_pct"] = pd.to_numeric(w["avg_net_return_pct"], errors="coerce")
        if "should_trade_week" in w.columns:
            w["should_trade_week"] = pd.to_numeric(w["should_trade_week"], errors="coerce")
            w = w[w["should_trade_week"] == 1].copy()
        good = w[w["avg_net_return_pct"] > tie_high].copy()
        bad = w[w["avg_net_return_pct"] < tie_low].copy()
        cols = [
            "spy_channel_r2",
            "avg_profile_distance",
            "avg_close_vs_sma50_candidates",
            "max_close_vs_sma50_candidates",
        ]
        stats: Dict[str, Any] = {}
        for c in cols:
            if c not in w.columns:
                continue
            g = pd.to_numeric(good[c], errors="coerce").dropna().tolist()
            b = pd.to_numeric(bad[c], errors="coerce").dropna().tolist()
            stats[c] = {
                "good_mean": _safe_mean([float(x) for x in g]),
                "bad_mean": _safe_mean([float(x) for x in b]),
                "delta_good_minus_bad": (
                    (_safe_mean([float(x) for x in g]) - _safe_mean([float(x) for x in b]))
                    if (_safe_mean([float(x) for x in g]) is not None and _safe_mean([float(x) for x in b]) is not None)
                    else None
                ),
            }
        out["week_quality_split"] = {
            "available": True,
            "weeks_traded_count": int(len(w)),
            "good_weeks_count": int(len(good)),
            "bad_weeks_count": int(len(bad)),
            "feature_stats": stats,
        }

    # Trades: ganadores vs perdedores + rank degradation.
    if not trades_df.empty and "net_return_pct" in trades_df.columns:
        t = trades_df.copy()
        t["net_return_pct"] = pd.to_numeric(t["net_return_pct"], errors="coerce")
        winners = t[t["net_return_pct"] > tie_high].copy()
        losers = t[t["net_return_pct"] < tie_low].copy()
        cols = ["current_candidate_rank", "close_vs_sma50_pct", "profile_distance", "spy_channel_r2"]
        stats: Dict[str, Any] = {}
        for c in cols:
            if c not in t.columns:
                continue
            w_vals = pd.to_numeric(winners[c], errors="coerce").dropna().tolist()
            l_vals = pd.to_numeric(losers[c], errors="coerce").dropna().tolist()
            stats[c] = {
                "winners_mean": _safe_mean([float(x) for x in w_vals]),
                "losers_mean": _safe_mean([float(x) for x in l_vals]),
                "delta_winners_minus_losers": (
                    (_safe_mean([float(x) for x in w_vals]) - _safe_mean([float(x) for x in l_vals]))
                    if (_safe_mean([float(x) for x in w_vals]) is not None and _safe_mean([float(x) for x in l_vals]) is not None)
                    else None
                ),
            }
        out["trade_quality_split"] = {
            "available": True,
            "trades_count": int(len(t)),
            "winners_count": int(len(winners)),
            "losers_count": int(len(losers)),
            "feature_stats": stats,
        }

        if "current_candidate_rank" in t.columns:
            g = t.copy()
            g["current_candidate_rank"] = pd.to_numeric(g["current_candidate_rank"], errors="coerce")
            g = g.dropna(subset=["current_candidate_rank", "net_return_pct"]).copy()
            by_rank = []
            for rk, df_r in g.groupby("current_candidate_rank"):
                by_rank.append(
                    {
                        "rank": int(round(float(rk))),
                        "trades": int(len(df_r)),
                        "avg_net_return_pct": (float(df_r["net_return_pct"].mean()) if pd.notna(df_r["net_return_pct"].mean()) else math.nan),
                    }
                )
            by_rank = sorted(by_rank, key=lambda x: x["rank"])
            rapid = False
            if by_rank:
                r1 = next((x for x in by_rank if x["rank"] == 1 and math.isfinite(x["avg_net_return_pct"])), None)
                rmax = next((x for x in reversed(by_rank) if math.isfinite(x["avg_net_return_pct"])), None)
                if r1 and rmax and rmax["rank"] > r1["rank"]:
                    rapid = float(r1["avg_net_return_pct"]) - float(rmax["avg_net_return_pct"]) >= 0.4
            out["rank_degradation"] = {
                "available": True,
                "rapid_degradation": rapid,
                "by_rank": by_rank,
            }

    # Gate activity check
    if not weekly_df.empty:
        gate_info: Dict[str, Any] = {"available": True}
        for gate_col, enabled_col in [
            ("spy_channel_r2_gate_pass", "spy_channel_r2_gate_enabled"),
            ("avg_profile_distance_gate_pass", "avg_profile_distance_gate_enabled"),
        ]:
            if gate_col in weekly_df.columns:
                gp = pd.to_numeric(weekly_df[gate_col], errors="coerce")
                fail = int((gp != 1).fillna(True).sum())
                gate_info[gate_col] = {"fails": fail}
            if enabled_col in weekly_df.columns:
                e = pd.to_numeric(weekly_df[enabled_col], errors="coerce")
                gate_info[enabled_col] = {"enabled_ratio": (float(e.fillna(0).mean()) if pd.notna(e.fillna(0).mean()) else math.nan)}
        out["gate_activity_check"] = gate_info

    if not candidates_df.empty and "skip_reason" in candidates_df.columns:
        out["diagnostic_notes"].append("Se revisaron candidates/skip_reason para validar que los gates operen realmente.")

    out["status"] = "ok"
    out["source_excel"] = str(xlsx_path) if xlsx_path else ""
    out["source_artifacts_dir"] = str(artifacts_dir) if artifacts_dir else ""
    return out


def score_fallback_candidate(
    diagnosis_category: str,
    candidate_type: str,
    parameter: str,
    from_value: Any,
    to_value: Any,
    transition_classification: str,
    layer: str,
    behavior_diag: Optional[Dict[str, Any]] = None,
    branch_health: str = "",
    exhausted_subspaces: Optional[Dict[Tuple[str, str, str], Dict[str, Any]]] = None,
    parameter_effect_entry: Optional[Dict[str, Any]] = None,
    parameter_effect_summary: Optional[Dict[str, Any]] = None,
    parameter_recent_attempts: int = 0,
    cooldown_active: bool = False,
) -> float:
    behavior_diag = behavior_diag or {}
    exhausted_subspaces = exhausted_subspaces or {}
    parameter_effect_summary = parameter_effect_summary or {}
    parameter_effect_entry = parameter_effect_entry or {}
    branch_health_norm = clean_text(branch_health)
    base = 1.0
    if layer == "layer_2":
        base += 0.4
    if transition_classification == "monotonic_refinement":
        base += 0.8
    elif transition_classification == "evidence_based_rollback":
        base += 0.55
    elif transition_classification == "controlled_exploration":
        base += 0.35

    if candidate_type == "gate_reactivation":
        base += 0.9
    elif candidate_type == "rank_adjustment":
        base += 0.7
    elif candidate_type == "quality_tightening":
        base += 0.5
    elif candidate_type == "controlled_reopening":
        base += 0.35
    elif candidate_type == "weekly_gate_recalibration":
        base += 0.55

    if branch_health_norm in {"stagnating", "blocked_by_process"}:
        if candidate_type in {"gate_reactivation", "quality_tightening", "weekly_gate_recalibration"}:
            base += 1.0

    rank_diag = behavior_diag.get("rank_degradation", {}) if isinstance(behavior_diag, dict) else {}
    if parameter == "TOP_CANDIDATES_NEXT_WEEK" and bool(rank_diag.get("rapid_degradation", False)):
        base += 1.25

    if parameter == "MAX_CLOSE_VS_SMA50_PCT":
        from_n = to_float(from_value)
        to_n = to_float(to_value)
        if diagnosis_category in {"high_frequency_low_edge", "weak_vs_spy", "mixed_quality"}:
            base += 3.0
            if from_n is not None and to_n is not None and to_n < from_n:
                base += 1.5
        elif diagnosis_category == "low_frequency_high_quality":
            base += 1.5
            if from_n is not None and to_n is not None and to_n > from_n:
                base += 1.0
    elif parameter == "TOP_CANDIDATES_NEXT_WEEK":
        from_n = to_float(from_value)
        to_n = to_float(to_value)
        if diagnosis_category in {"high_frequency_low_edge", "weak_vs_spy", "mixed_quality"}:
            base += 2.5
            if from_n is not None and to_n is not None and to_n < from_n:
                base += 1.0
        elif diagnosis_category == "low_frequency_high_quality":
            base += 2.0
            if from_n is not None and to_n is not None and to_n > from_n:
                base += 1.0
    elif parameter == "MIN_SPY_CHANNEL_R2":
        from_n = to_float(from_value)
        to_n = to_float(to_value)
        if diagnosis_category in {"high_frequency_low_edge", "weak_vs_spy"}:
            base += 2.0
            if from_n is not None and to_n is not None and to_n > from_n:
                base += 1.0
        elif diagnosis_category == "low_frequency_high_quality":
            base += 2.0
            if from_n is not None and to_n is not None and to_n < from_n:
                base += 1.0
    elif parameter == "TOP_SIMILAR_SPY_WEEKS":
        # Menor sesgo a la ventana de similares para evitar whipsaw de subespacios repetidos.
        base += 0.25
        if diagnosis_category == "no_clear_signal":
            base += 0.15
        if branch_health_norm in {"stagnating", "blocked_by_process"}:
            base -= 1.0
    elif parameter == "MAX_AVG_PROFILE_DISTANCE":
        if diagnosis_category == "low_frequency_high_quality":
            base += 2.0
        else:
            base += 1.0

    key = (clean_text(parameter), normalize_scalar(from_value), normalize_scalar(to_value))
    if key in exhausted_subspaces:
        # Penalización fuerte por subespacio agotado (igual se filtra antes; esto es defensa extra).
        base -= 3.5

    if cooldown_active:
        # Defensa extra: nunca debería ganar score si está en cooldown activo.
        base -= 6.0

    effect_class = clean_text(parameter_effect_entry.get("current_effect_class", ""))
    effect_delta_spy = to_float(parameter_effect_entry.get("avg_delta_w52_spy_compare"))
    effect_accept_ratio = to_float(parameter_effect_entry.get("accept_ratio"))
    if effect_accept_ratio is None:
        attempts = to_float(parameter_effect_entry.get("total_attempts")) or 0.0
        accepted = to_float(parameter_effect_entry.get("accepted_count")) or 0.0
        effect_accept_ratio = (accepted / attempts) if attempts > 0 else 0.0

    if effect_class == "strong_positive":
        base += 2.0
    elif effect_class == "mild_positive":
        base += 1.0
    elif effect_class == "neutral":
        base += 0.15
    elif effect_class == "unstable":
        base -= 0.4
    elif effect_class == "harmful":
        base -= 1.8
    elif effect_class == "exhausted":
        base -= 3.0

    if effect_delta_spy is not None:
        if effect_delta_spy >= 0.40:
            base += 1.2
        elif effect_delta_spy >= 0.10:
            base += 0.5
        elif effect_delta_spy <= -0.20:
            base -= 1.0

    if (effect_accept_ratio or 0.0) >= 0.60:
        base += 0.4
    elif (effect_accept_ratio or 0.0) <= 0.20 and (to_float(parameter_effect_entry.get("total_attempts")) or 0.0) >= 3:
        base -= 0.7

    param_summary = parameter_effect_summary.get(clean_text(parameter), {}) if isinstance(parameter_effect_summary, dict) else {}
    param_attempts = int(to_float(param_summary.get("attempts")) or 0)
    param_avg_spy = to_float(param_summary.get("avg_delta_w52_spy_compare"))
    harmful_like = int(to_float(param_summary.get("harmful_like")) or 0)
    strong_positive_like = int(to_float(param_summary.get("strong_positive_like")) or 0)
    if param_attempts >= 6 and harmful_like > strong_positive_like:
        base -= 0.75
    if param_avg_spy is not None and param_avg_spy >= 0.20:
        base += 0.55
    elif param_avg_spy is not None and param_avg_spy <= -0.20:
        base -= 0.65

    # Evita sobre-explotar el mismo eje cuando ya tuvo demasiados intentos en la rama reciente.
    if int(parameter_recent_attempts) >= 4:
        base -= 0.8
    elif int(parameter_recent_attempts) >= 3:
        base -= 0.45

    return base


def mode_score_adjustment(
    current_mode: str,
    candidate_type: str,
    parameter: str,
    transition_classification: str,
    parameter_recent_attempts: int,
    recent_param_counts: Optional[Dict[str, int]] = None,
    last_useful_param: str = "",
) -> float:
    mode = normalize_research_mode(current_mode)
    candidate_t = clean_text(candidate_type)
    param = clean_text(parameter)
    recent_param_counts = recent_param_counts or {}
    is_orthogonal = int(recent_param_counts.get(param, 0)) == 0
    is_monotonic = clean_text(transition_classification) == "monotonic_refinement"
    adj = 0.0

    if mode == "refine_current_branch":
        if is_monotonic:
            adj += 1.2
        if candidate_t in {"quality_tightening", "weekly_gate_recalibration"}:
            adj += 0.7
        if candidate_t in {"controlled_exploration", "controlled_reopening"}:
            adj -= 0.8
    elif mode == "controlled_exploration":
        if is_orthogonal:
            adj += 1.1
        if candidate_t in {"controlled_exploration", "controlled_reopening", "gate_reactivation"}:
            adj += 0.65
        if int(parameter_recent_attempts) >= 3:
            adj -= 1.1
    elif mode == "extend_validation":
        if is_monotonic:
            adj += 1.0
        if candidate_t in {"quality_tightening", "weekly_gate_recalibration"}:
            adj += 0.55
        if candidate_t in {"controlled_exploration", "gate_reactivation"}:
            adj -= 1.0
    elif mode == "fix_process_before_more_research":
        if candidate_t in {"quality_tightening", "weekly_gate_recalibration"}:
            adj += 0.35
        if candidate_t in {"controlled_exploration", "rank_adjustment"}:
            adj -= 0.9
    elif mode == "champion_hold":
        if is_orthogonal:
            adj += 0.9
        if last_useful_param and param == clean_text(last_useful_param):
            adj -= 0.95
        if candidate_t in {"controlled_exploration", "controlled_reopening"}:
            adj += 0.4
    elif mode == "safe_recovery_mode":
        if param in {"TOP_CANDIDATES_NEXT_WEEK", "TOP_SIMILAR_SPY_WEEKS"}:
            adj -= 1.2
        if candidate_t in {"quality_tightening", "weekly_gate_recalibration"}:
            adj += 0.65
        if candidate_t in {"controlled_exploration", "controlled_reopening", "gate_reactivation"}:
            adj -= 1.1
    return adj


def mode_hard_block_candidate(
    current_mode: str,
    candidate_type: str,
    parameter: str,
) -> bool:
    mode = normalize_research_mode(current_mode)
    candidate_t = clean_text(candidate_type)
    param = clean_text(parameter)
    if mode == "safe_recovery_mode":
        if param in {"TOP_CANDIDATES_NEXT_WEEK", "TOP_SIMILAR_SPY_WEEKS"} and candidate_t in {
            "controlled_exploration",
            "rank_adjustment",
            "controlled_reopening",
        }:
            return True
    return False


def infer_change_intent_from_mode(current_mode: str) -> str:
    mode = normalize_research_mode(current_mode)
    if mode == "refine_current_branch":
        return "refine"
    if mode == "extend_validation":
        return "validation"
    if mode in {"fix_process_before_more_research", "safe_recovery_mode"}:
        return "recovery"
    return "exploration"


def candidate_type_from_parameter(parameter: str) -> str:
    p = clean_text(parameter)
    if p == "MAX_CLOSE_VS_SMA50_PCT":
        return "quality_tightening"
    if p in {"MIN_SPY_CHANNEL_R2", "MAX_AVG_PROFILE_DISTANCE"}:
        return "weekly_gate_recalibration"
    if p == "TOP_CANDIDATES_NEXT_WEEK":
        return "rank_adjustment"
    if p in {"ENABLE_CLOSE_VS_SMA50_FILTER", "ENABLE_AVG_PROFILE_DISTANCE_GATE"}:
        return "gate_reactivation"
    return "controlled_exploration"


def candidate_family_from_parameter(parameter: str) -> str:
    p = clean_text(parameter)
    if p in {"ENABLE_CLOSE_VS_SMA50_FILTER", "MAX_CLOSE_VS_SMA50_PCT"}:
        return "asset_extension_filter"
    if p in {"MIN_SPY_CHANNEL_R2", "ENABLE_SPY_CHANNEL_R2_GATE"}:
        return "spy_regime_filter"
    if p in {"MAX_AVG_PROFILE_DISTANCE", "ENABLE_AVG_PROFILE_DISTANCE_GATE"}:
        return "profile_distance"
    if p == "TOP_CANDIDATES_NEXT_WEEK":
        return "rank_basket_selection"
    if p == "TOP_SIMILAR_SPY_WEEKS":
        return "similar_spy_window"
    return "controlled_exploration"


def build_exploratory_candidate_specs(parent_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []

    top_sim = to_float(parent_cfg.get("TOP_SIMILAR_SPY_WEEKS"))
    if top_sim is not None:
        for v in [
            round(min(52.0, max(8.0, top_sim + 4.0)), 3),
            round(min(52.0, max(8.0, top_sim + 8.0)), 3),
        ]:
            specs.append(
                {
                    "parameter": "TOP_SIMILAR_SPY_WEEKS",
                    "to_value": v,
                    "candidate_type": "weekly_gate_recalibration",
                    "candidate_family": "similar_spy_window",
                    "hypothesis": "Explorar una ventana mas amplia de semanas similares sin repetir el subespacio agotado.",
                    "meaning": "Ajuste exploratorio de TOP_SIMILAR_SPY_WEEKS.",
                    "purpose": "Buscar ortogonalidad de matching temporal.",
                    "why_improve": "Puede abrir una familia no agotada de similaridad SPY.",
                    "expected_effect": "Cambio exploratorio en la base de semanas comparables.",
                }
            )

    dist_thr = to_float(parent_cfg.get("MAX_AVG_PROFILE_DISTANCE"))
    if dist_thr is not None:
        for v in [
            round(max(0.08, dist_thr + 0.04), 3),
            round(max(0.08, dist_thr - 0.01), 3),
        ]:
            specs.append(
                {
                    "parameter": "MAX_AVG_PROFILE_DISTANCE",
                    "to_value": v,
                    "candidate_type": "weekly_gate_recalibration",
                    "candidate_family": "profile_distance",
                    "hypothesis": "Explorar una distancia de perfil fuera del vecindario ya agotado.",
                    "meaning": "Ajuste exploratorio de MAX_AVG_PROFILE_DISTANCE.",
                    "purpose": "Abrir una rama ortogonal en matching de perfil.",
                    "why_improve": "Puede recuperar señal sin reusar transiciones exhaustas.",
                    "expected_effect": "Filtrado distinto de semanas por distancia de perfil.",
                }
            )

    r2_thr = to_float(parent_cfg.get("MIN_SPY_CHANNEL_R2"))
    if r2_thr is not None:
        for v in [
            round(max(0.30, r2_thr - 0.01), 3),
            round(max(0.30, r2_thr - 0.02), 3),
        ]:
            specs.append(
                {
                    "parameter": "MIN_SPY_CHANNEL_R2",
                    "to_value": v,
                    "candidate_type": "weekly_gate_recalibration",
                    "candidate_family": "spy_regime_filter",
                    "hypothesis": "Explorar un umbral SPY un poco mas laxo sin volver al vecindario agotado.",
                    "meaning": "Ajuste exploratorio de MIN_SPY_CHANNEL_R2.",
                    "purpose": "Buscar otra zona operativa de gating SPY.",
                    "why_improve": "Puede recuperar frecuencia sin caer en no-op.",
                    "expected_effect": "Cambio exploratorio en semanas habilitadas por el gate SPY.",
                }
            )

    top_curr = int(round(to_float(parent_cfg.get("TOP_CANDIDATES_NEXT_WEEK")) or 5))
    if top_curr > 1:
        for v in [max(1, top_curr - 1), min(8, top_curr + 1)]:
            if v == top_curr:
                continue
            specs.append(
                {
                    "parameter": "TOP_CANDIDATES_NEXT_WEEK",
                    "to_value": v,
                    "candidate_type": "rank_adjustment",
                    "candidate_family": "rank_basket_selection",
                    "hypothesis": "Explorar una capacidad semanal distinta fuera de los valores ya quemados.",
                    "meaning": "Ajuste exploratorio de TOP_CANDIDATES_NEXT_WEEK.",
                    "purpose": "Mover la frontera calidad/frecuencia desde una rama nueva.",
                    "why_improve": "Puede abrir una rama ortogonal de basket selection.",
                    "expected_effect": "Cambio exploratorio en el numero de candidatos semanales.",
                }
            )

    return specs


def build_candidate_generation_diagnostic_output(
    parent_run_id: str,
    proposal_status: str,
    fallback_candidate_pool_considered: List[Dict[str, Any]],
    fallback_diagnosis: Optional[Dict[str, Any]] = None,
    selected_proposal: Optional[Dict[str, Any]] = None,
    force_axis_reset: bool = False,
    force_new_candidate_family: bool = False,
    consecutive_no_material_candidate: int = 0,
) -> Dict[str, Any]:
    fallback_diagnosis = fallback_diagnosis or {}
    pool = list(fallback_candidate_pool_considered or [])
    rejection_counts = Counter(clean_text(x.get("reason", "")) for x in pool if clean_text(x.get("state", "")) == "discarded")
    selected_candidate = None
    if isinstance(selected_proposal, dict):
        main = selected_proposal.get("main_change") or {}
        dep = selected_proposal.get("dependent_change") or {}
        selected_candidate = {
            "candidate_axis": clean_text(main.get("parameter", "")),
            "proposed_change": f"{normalize_scalar(main.get('from_value'))}->{normalize_scalar(main.get('to_value'))}",
            "candidate_family": candidate_family_from_parameter(main.get("parameter", "")),
            "proposal_source": clean_text(selected_proposal.get("proposal_source", selected_proposal.get("source", proposal_status))),
            "proposal_status": clean_text(selected_proposal.get("status", proposal_status)),
            "candidate_is_exploratory": bool(selected_proposal.get("candidate_is_exploratory", False)),
            "exploratory_reason": clean_text(selected_proposal.get("exploratory_reason", "")),
            "bypassed_soft_cooldown": bool(selected_proposal.get("bypassed_soft_cooldown", False)),
            "hard_block_bypassed": bool(selected_proposal.get("hard_block_bypassed", False)),
            "next_change_consumed": bool(selected_proposal.get("next_change_consumed", False)),
            "next_change_rejected": bool(selected_proposal.get("next_change_rejected", False)),
            "next_change_rejected_reason": clean_text(selected_proposal.get("next_change_rejected_reason", "")),
            "next_change_zigzag_override": bool(selected_proposal.get("next_change_zigzag_override", False)),
            "next_change_zigzag_override_reason": clean_text(selected_proposal.get("next_change_zigzag_override_reason", "")),
            "original_rejection_reason": clean_text(selected_proposal.get("original_rejection_reason", "")),
            "next_change_parameter": clean_text(selected_proposal.get("next_change_parameter", "")),
            "next_change_from": selected_proposal.get("next_change_from"),
            "next_change_to": selected_proposal.get("next_change_to"),
            "main_change": {
                "parameter": clean_text(main.get("parameter", "")),
                "from_value": main.get("from_value"),
                "to_value": main.get("to_value"),
            },
            "dependent_change": {
                "parameter": clean_text(dep.get("parameter", "")),
                "from_value": dep.get("from_value"),
                "to_value": dep.get("to_value"),
            }
            if clean_text(dep.get("parameter", ""))
            else None,
        }

    normalized_candidates: List[Dict[str, Any]] = []
    for item in pool:
        param = clean_text(item.get("parameter", ""))
        reason = clean_text(item.get("reason", ""))
        state = clean_text(item.get("state", ""))
        exhausted_stats = item.get("exhausted_stats", {}) if isinstance(item.get("exhausted_stats", {}), dict) else {}
        normalized_candidates.append(
            {
                "candidate_axis": param,
                "proposed_change": f"{normalize_scalar(item.get('from_value'))}->{normalize_scalar(item.get('to_value'))}",
                "candidate_family": candidate_family_from_parameter(param),
                "rejected_by": reason if state == "discarded" else "",
                "rejection_reason": reason if state == "discarded" else "",
                "was_duplicate": reason in {"duplicate_recent_proposal", "config_hash_already_tested_executed_run"},
                "was_no_op": reason == "no_op_equivalence",
                "was_in_cooldown": reason == "cooldown_active",
                "was_hard_blocked": reason in {
                    "hard_blocked_exhausted_or_memory_subspace",
                    "blocked_by_current_mode",
                    "branch_anchor_locked",
                },
                "was_metric_no_effect_axis": reason == "metric_no_effect" or clean_text(exhausted_stats.get("current_effect_class", "")) == "exhausted_no_effect",
                "was_orthogonal_candidate_available": bool(item.get("is_orthogonal", False)),
                "state": state,
                "layer": clean_text(item.get("layer", "")),
                "candidate_type": clean_text(item.get("candidate_type", "")),
                "bypassed_soft_cooldown": bool(item.get("bypassed_soft_cooldown", False)),
            }
        )

    valid_count = sum(1 for item in pool if clean_text(item.get("state", "")) == "valid")
    rejected_count = sum(1 for item in pool if clean_text(item.get("state", "")) == "discarded")
    return {
        "parent_run_id": clean_text(parent_run_id),
        "candidate_pool_size": int(len(pool)),
        "valid_candidate_count": int(valid_count),
        "rejected_candidate_count": int(rejected_count),
        "rejection_counts_by_reason": dict(sorted(rejection_counts.items())),
        "candidates": normalized_candidates,
        "selected_candidate": selected_candidate,
        "proposal_status": clean_text(proposal_status),
        "proposal_source": clean_text((selected_proposal or {}).get("proposal_source", "")) if isinstance(selected_proposal, dict) else "",
        "force_axis_reset": bool(force_axis_reset),
        "force_new_candidate_family": bool(force_new_candidate_family),
        "bypassed_soft_cooldown": bool(selected_proposal.get("bypassed_soft_cooldown", False)) if isinstance(selected_proposal, dict) else False,
        "hard_block_bypassed": bool(selected_proposal.get("hard_block_bypassed", False)) if isinstance(selected_proposal, dict) else False,
        "candidate_is_exploratory": bool(selected_proposal.get("candidate_is_exploratory", False)) if isinstance(selected_proposal, dict) else False,
        "exploratory_reason": clean_text(selected_proposal.get("exploratory_reason", "")) if isinstance(selected_proposal, dict) else "",
        "next_change_consumed": bool(selected_proposal.get("next_change_consumed", False)) if isinstance(selected_proposal, dict) else False,
        "next_change_rejected": bool(selected_proposal.get("next_change_rejected", False)) if isinstance(selected_proposal, dict) else False,
        "next_change_rejected_reason": clean_text(selected_proposal.get("next_change_rejected_reason", "")) if isinstance(selected_proposal, dict) else "",
        "next_change_zigzag_override": bool(selected_proposal.get("next_change_zigzag_override", False)) if isinstance(selected_proposal, dict) else False,
        "next_change_zigzag_override_reason": clean_text(selected_proposal.get("next_change_zigzag_override_reason", "")) if isinstance(selected_proposal, dict) else "",
        "original_rejection_reason": clean_text(selected_proposal.get("original_rejection_reason", "")) if isinstance(selected_proposal, dict) else "",
        "next_change_parameter": clean_text(selected_proposal.get("next_change_parameter", "")) if isinstance(selected_proposal, dict) else "",
        "next_change_from": selected_proposal.get("next_change_from") if isinstance(selected_proposal, dict) else None,
        "next_change_to": selected_proposal.get("next_change_to") if isinstance(selected_proposal, dict) else None,
        "consecutive_no_material_candidate": int(consecutive_no_material_candidate),
        "fallback_diagnosis": fallback_diagnosis,
    }


def count_recent_transition_attempts(
    rows: List[Dict[str, str]],
    parameter: str,
    from_value: Any,
    to_value: Any,
    lookback: int = 50,
    current_parent_run_id: str = "",
) -> int:
    """
    Count transition attempts globally in the recent window.

    current_parent_run_id is kept for API compatibility, but deliberately not
    used as a filter because tracker parent ids and loop_trace parent_used can
    diverge. Cooldown / duplicate blocking must protect against repeating bad
    transitions regardless of parent bookkeeping noise.
    """
    key = transition_key(parameter, from_value, to_value)
    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = sorted_rows[-max(1, int(lookback)) :] if sorted_rows else []
    cnt = 0
    for r in recent:
        if clean_text(r.get("status", "")) not in {"run_ok", "run_partial_valid"}:
            continue
        p = clean_text(r.get("main_parameter", ""))
        f = normalize_scalar(r.get("main_from"))
        t = normalize_scalar(r.get("main_to"))
        if (p, f, t) == key:
            cnt += 1
    return cnt


def recommended_direction_priority_adjustment(
    candidate_type: str,
    parameter: str,
    from_value: Any,
    to_value: Any,
    recommended_dirs: Optional[List[str]] = None,
) -> float:
    dirs = {clean_text(x) for x in (recommended_dirs or []) if clean_text(x)}
    ctype = clean_text(candidate_type)
    param = clean_text(parameter)
    adj = 0.0

    if "tighten_individual_candidate_filters" in dirs:
        if ctype == "quality_tightening":
            adj += 1.35
        if param == "MAX_CLOSE_VS_SMA50_PCT":
            fv = to_float(from_value)
            tv = to_float(to_value)
            if fv is not None and tv is not None and tv < fv:
                adj += 0.65
    if "reactivate_disabled_gate" in dirs and ctype == "gate_reactivation":
        adj += 1.5
    if "recalibrate_weekly_gate" in dirs:
        if ctype == "weekly_gate_recalibration":
            adj += 1.25
        if param in {"TOP_SIMILAR_SPY_WEEKS", "MIN_SPY_CHANNEL_R2", "MAX_AVG_PROFILE_DISTANCE"}:
            adj += 0.45
    return adj


def stage4_candidate_adjustment(
    parameter: str,
    from_value: Any,
    to_value: Any,
    candidate_type: str,
    current_mode: str,
    branch_health: str,
    main_friction: str,
    recommended_dirs: Optional[List[str]],
    parameter_recent_attempts: int,
    transition_recent_attempts: int,
    recent_param_counts: Optional[Dict[str, int]],
    parameter_effect_entry: Optional[Dict[str, Any]],
    orthogonal_force_active: bool,
) -> Tuple[float, List[str]]:
    param = clean_text(parameter)
    ctype = clean_text(candidate_type)
    bh = clean_text(branch_health)
    friction = clean_text(main_friction)
    recent_param_counts = recent_param_counts or {}
    effect_entry = parameter_effect_entry or {}
    is_orthogonal = int(recent_param_counts.get(param, 0)) == 0
    adj = 0.0
    reasons: List[str] = []

    rec_adj = recommended_direction_priority_adjustment(
        candidate_type=ctype,
        parameter=param,
        from_value=from_value,
        to_value=to_value,
        recommended_dirs=recommended_dirs,
    )
    if rec_adj != 0.0:
        adj += rec_adj
        reasons.append(f"recommended_change_directions:{rec_adj:+.2f}")

    if orthogonal_force_active:
        if is_orthogonal:
            adj += 1.25
            reasons.append("orthogonal_force_bonus:+1.25")
        else:
            adj -= 1.9
            reasons.append("orthogonal_force_penalty:-1.90")
    else:
        if is_orthogonal:
            adj += 0.35
            reasons.append("orthogonal_bonus:+0.35")
        elif int(parameter_recent_attempts) >= 3:
            adj -= 0.45
            reasons.append("repetitive_parameter_penalty:-0.45")

    if int(parameter_recent_attempts) >= 6:
        adj -= 0.9
        reasons.append("overtried_parameter_penalty:-0.90")
    if int(transition_recent_attempts) >= 3:
        adj -= 0.75
        reasons.append("repeated_transition_penalty:-0.75")

    fv = to_float(from_value)
    tv = to_float(to_value)
    if (
        param == "TOP_SIMILAR_SPY_WEEKS"
        and bh == "stagnating"
        and int(transition_recent_attempts) >= 2
    ):
        adj -= 2.3
        reasons.append("stagnating_repeated_top_similar_weeks_penalty:-2.30")
    if (
        param == "TOP_CANDIDATES_NEXT_WEEK"
        and fv is not None
        and tv is not None
        and int(round(fv)) == 2
        and int(round(tv)) in {4, 5}
        and int(transition_recent_attempts) >= 1
    ):
        adj -= 3.0
        reasons.append("repeat_known_bad_top_candidates_2_to_4_or_5_penalty:-3.00")

    d_spy = to_float(effect_entry.get("avg_delta_w52_spy_compare"))
    d_trades = to_float(effect_entry.get("avg_delta_w52_trades"))
    d_avg = to_float(effect_entry.get("avg_delta_w52_avg_net_return_pct"))
    if (
        d_trades is not None
        and d_trades > 0
        and (
            (d_spy is not None and d_spy <= -0.12)
            or (d_avg is not None and d_avg <= -0.06)
        )
    ):
        adj -= 2.15
        reasons.append("frequency_up_quality_down_penalty:-2.15")

    if friction in {"coordinator", "state_handling", "duplicate_throttling"} and ctype in {
        "controlled_exploration",
        "controlled_reopening",
        "rank_adjustment",
    }:
        adj -= 1.0
        reasons.append("process_friction_exploration_penalty:-1.00")
    if friction in {"candidate_generation", "branch_stagnation"} and ctype in {
        "quality_tightening",
        "gate_reactivation",
        "weekly_gate_recalibration",
    }:
        adj += 0.35
        reasons.append("friction_alignment_bonus:+0.35")

    mode = normalize_research_mode(current_mode)
    if mode == "controlled_exploration" and is_orthogonal:
        adj += 0.4
        reasons.append("mode_controlled_exploration_orthogonal_bonus:+0.40")
    return adj, reasons


def select_analyst_proposal(
    queue: List[Dict[str, Any]],
    parent_cfg: Dict[str, Any],
    last_valid_ctx: Optional[Dict[str, Any]],
    windows: List[int],
    rows: Optional[List[Dict[str, str]]] = None,
    branch_anchor: Optional[Dict[str, Any]] = None,
    branch_state: Optional[Dict[str, Any]] = None,
    existing_config_hashes: Optional[Dict[str, str]] = None,
    tracked_keys: Optional[List[str]] = None,
    parameter_effect_memory: Optional[Dict[str, Any]] = None,
    subspace_cooldowns: Optional[Dict[str, Any]] = None,
    current_iteration: int = 0,
) -> Dict[str, Any]:
    if rows is None:
        rows = []
    anchor_state = dict(branch_anchor or {})
    branch_state = dict(branch_state or {})
    branch_health = clean_text(branch_state.get("branch_health", ""))
    main_friction = clean_text(branch_state.get("main_friction", ""))
    recommended_change_directions = sanitize_text_list(
        branch_state.get("recommended_change_directions", []) or []
    )
    existing_config_hashes = existing_config_hashes or {}
    tracked_keys = tracked_keys or []
    parameter_effect_memory = parameter_effect_memory or {}
    subspace_cooldowns = subspace_cooldowns or {}
    parameter_effect_summary = build_parameter_effect_summary(parameter_effect_memory)
    active_cooldown_keys = get_active_cooldown_keys(subspace_cooldowns, int(current_iteration))
    memory_hard_blocked_transitions = build_memory_hard_blocked_transition_keys(parameter_effect_memory)
    current_mode = normalize_research_mode(
        branch_state.get("current_mode", ""),
        fallback=map_recommended_action_to_mode(branch_state.get("recommended_next_action", "")),
    )
    recent_params = get_recent_changed_parameters(rows, lookback=8)
    recent_param_counts: Dict[str, int] = {}
    for p in recent_params:
        recent_param_counts[p] = int(recent_param_counts.get(p, 0)) + 1
    recent_unique_params = sorted({clean_text(p) for p in recent_params if clean_text(p)})
    branch_force_orthogonal = bool(
        branch_state.get("force_new_candidate_family", False)
        or branch_state.get("force_axis_reset", False)
        or branch_state.get("avoid_last_candidate_family", "")
    )
    orthogonal_force_active = bool(branch_force_orthogonal or (len(recent_params) >= 6 and len(recent_unique_params) <= 2))
    no_material_recent_streak = count_consecutive_status_from_end(
        rows,
        {"blocked_no_material_candidate", "no_material_candidate_found"},
    )
    last_useful_param = get_recent_useful_main_parameter(rows, lookback=12)

    def _already_tested(cfg: Dict[str, Any]) -> bool:
        if not tracked_keys:
            return False
        h = config_hash(cfg, tracked_keys)
        return h in existing_config_hashes
    pending = [q for q in queue if q.get("status") == "pending"]
    if pending:
        for item in pending:
            main = dict(item.get("main_change", {}))
            dep = dict(item.get("dependent_change", {}))
            proposal_cfg = dict(parent_cfg)

            main_param = str(main.get("parameter", ""))
            if not main_param:
                continue
            proposal_cfg[main_param] = main.get("to_value")
            main_key = transition_key(main_param, parent_cfg.get(main_param), main.get("to_value"))
            if main_key in active_cooldown_keys:
                continue
            if main_key in memory_hard_blocked_transitions:
                continue

            dependent_obj = None
            dep_param = str(dep.get("parameter", ""))
            if dep_param:
                proposal_cfg[dep_param] = dep.get("to_value")
                dependent_obj = {
                    "parameter": dep_param,
                    "from_value": parent_cfg.get(dep_param),
                    "to_value": dep.get("to_value"),
                    "dependency_reason": dep.get("dependency_reason", ""),
                    "meaning": dep.get("meaning", ""),
                }

            last_run_id = ""
            if last_valid_ctx:
                last_run_id = str(last_valid_ctx.get("run_id", ""))
            diagnosis = "No hay corrida valida previa; se ejecuta plan inicial de reinicio."
            if last_run_id:
                diagnosis = f"Se analiza la ultima corrida valida ({last_run_id}) y se prioriza test causal limpio."

            proposal = {
                "role": "analyst",
                "mode": mode_to_analyst_style(current_mode),
                "research_mode_context": current_mode,
                "change_intent": infer_change_intent_from_mode(current_mode),
                "source": "initial_test_queue",
                "queue_test_id": item.get("id", ""),
                "parent_run_id": last_run_id,
                "analysis_reference_run_id": last_run_id,
                "diagnosis": diagnosis,
                "hypothesis": item.get("objective", ""),
                "main_change": {
                    "parameter": main_param,
                    "from_value": parent_cfg.get(main_param),
                    "to_value": main.get("to_value"),
                    "meaning": main.get("meaning", ""),
                    "purpose": main.get("purpose", ""),
                    "why_improve": main.get("why_improve", ""),
                },
                "dependent_change": dependent_obj,
                "expected_effect": item.get("expected_effect", ""),
                "compare_windows": windows,
                "compare_vs_spy": True,
                "prioritize_robustness_over_short_term": True,
                "revert_explicit": False,
                "revert_justification": "",
                "proposal_config": proposal_cfg,
                "fallback_diagnosis": {
                    "implementation_check": "",
                    "good_vs_bad_weeks": "",
                    "winners_vs_losers": "",
                    "rank_degradation": "",
                    "parent_vs_baseline": "",
                },
                "fallback_candidate_pool_considered": [],
                "fallback_selected_reason": "initial_test_queue_priority",
                "selection_trace": {
                    "current_mode": current_mode,
                    "change_intent": infer_change_intent_from_mode(current_mode),
                    "selection_reason": "initial_test_queue_priority",
                    "recommended_change_directions": recommended_change_directions[:3],
                    "historical_memory_used": {
                        "parameter_effect_memory": "summary_only",
                        "subspace_cooldowns_active": len(active_cooldown_keys),
                    },
                    "alternatives_discarded": [],
                },
            }
            if _already_tested(proposal_cfg):
                continue
            if validate_main_change_materiality(proposal).get("material_change_detected", False):
                anchor_eval = evaluate_branch_anchor_conflict(proposal, anchor_state)
                if bool(anchor_eval.get("blocked", False)):
                    continue
                return proposal

    last_run_id = ""
    if last_valid_ctx:
        last_run_id = str(last_valid_ctx.get("run_id", ""))

    parent_w52 = get_window_metrics_from_ctx(last_valid_ctx, 52)
    parent_w24 = get_window_metrics_from_ctx(last_valid_ctx, 24)
    compare_vs_parent = {
        "avg_net_return_pct": {"delta": None},
        "spy_compare": {"delta": None},
        "parent_recently_rejected": False,
    }
    # Usa evidencia reciente desde el mismo parent para evitar loops improductivos.
    if last_run_id:
        executed_rows = [
            r
            for r in sorted(rows, key=lambda x: parse_run_id(x.get("run_id", "")))
            if clean_text(r.get("parent_run_id", "")) == last_run_id
            and clean_text(r.get("status", "")) in {"run_ok", "run_partial_valid"}
            and clean_text(r.get("accepted_or_rejected", "")).lower() in {"accepted", "rejected"}
        ]
        if executed_rows:
            last_from_parent = executed_rows[-1]
            parent_spy = to_float(parent_w52.get("spy_compare"))
            last_spy = to_float(last_from_parent.get("w52_spy_compare"))
            if parent_spy is not None and last_spy is not None:
                compare_vs_parent["spy_compare"]["delta"] = round(last_spy - parent_spy, 6)
            if clean_text(last_from_parent.get("accepted_or_rejected", "")).lower() == "rejected":
                compare_vs_parent["parent_recently_rejected"] = True
    fallback_diagnosis = diagnose_parent_outcome_for_fallback(
        parent_metrics=parent_w52,
        compare_vs_parent=compare_vs_parent,
        compare_vs_spy=to_float(parent_w52.get("spy_compare")),
    )
    diagnosis_category = str(fallback_diagnosis.get("category", "no_clear_signal"))
    recent_feedback = collect_recent_coordinator_feedback(rows, lookback=30)
    behavior_diag = load_parent_behavior_diagnostics(last_valid_ctx, tie_low=0.0, tie_high=1.0)
    fallback_diagnosis["second_layer_required"] = True
    fallback_diagnosis["second_layer_executed"] = False
    fallback_diagnosis["behavioral_diagnostics"] = behavior_diag
    fallback_diagnosis = compose_fallback_diagnosis_contract(
        parent_cfg=parent_cfg,
        fallback_diagnosis=fallback_diagnosis,
        behavior_diag=behavior_diag,
        analysis_reference_run_id=last_run_id,
        parent_w24=parent_w24,
        parent_w52=parent_w52,
    )

    exhausted_subspaces = detect_recent_exhausted_subspaces(
        rows=rows,
        parent_run_id=last_run_id,
        lookback=50,
        min_repeats=3,
        min_reject_ratio=0.75,
    )
    memory_exhausted_subspaces = memory_hard_blocked_transitions
    for mem_key, mem_info in memory_exhausted_subspaces.items():
        exhausted_subspaces.setdefault(
            mem_key,
            {
                "count": int(mem_info.get("total_attempts", 0)),
                "rejected": int(mem_info.get("rejected_count", 0)),
                "accepted": int(mem_info.get("accepted_count", 0)),
                "reject_ratio": 1.0 if int(mem_info.get("total_attempts", 0)) > 0 else 0.0,
                "run_ids": list(mem_info.get("last_run_ids", [])),
                "latest_status": "memory_hard_block",
                "memory_reason": clean_text(mem_info.get("reason", "")),
                "current_effect_class": clean_text(mem_info.get("current_effect_class", "")),
            },
        )
    exhausted_keys = set(exhausted_subspaces.keys())
    exhausted_keys.update(active_cooldown_keys)
    exhausted_keys.update(memory_exhausted_subspaces.keys())
    # Guardrail específico para estancamiento reciente reportado en auditoría.
    if branch_health in {"stagnating", "blocked_by_process"}:
        exhausted_keys.add(("TOP_SIMILAR_SPY_WEEKS", normalize_scalar(24.0), normalize_scalar(16)))
        exhausted_keys.add(("MAX_AVG_PROFILE_DISTANCE", normalize_scalar(0.26), normalize_scalar(0.17)))
    fallback_diagnosis["branch_health"] = branch_health
    fallback_diagnosis["main_friction"] = main_friction
    fallback_diagnosis["current_mode"] = current_mode
    fallback_diagnosis["mode_reason_hint"] = clean_text(branch_state.get("mode_reason", ""))
    fallback_diagnosis["recommended_change_directions"] = recommended_change_directions[:3]
    fallback_diagnosis["orthogonal_force_active"] = bool(orthogonal_force_active)
    fallback_diagnosis["orthogonal_force_basis"] = {
        "recent_params_lookback": 8,
        "recent_params_count": len(recent_params),
        "recent_unique_params_count": len(recent_unique_params),
        "recent_unique_params": recent_unique_params[:6],
    }
    fallback_diagnosis["recent_exhausted_subspaces"] = [
        {
            "parameter": k[0],
            "normalized_from": k[1],
            "normalized_to": k[2],
            "count": (exhausted_subspaces.get(k, {}) or {}).get("count"),
            "reject_ratio": (exhausted_subspaces.get(k, {}) or {}).get("reject_ratio"),
            "run_ids": (exhausted_subspaces.get(k, {}) or {}).get("run_ids", [])[-5:],
            "cooldown_active": bool(
                (
                    get_subspace_cooldown_entry(subspace_cooldowns, k[0], k[1], k[2], create_if_missing=False)
                    or {}
                ).get("cooldown_active", False)
            ),
            "cooldown_until_iteration": int(
                to_float(
                    (
                        get_subspace_cooldown_entry(subspace_cooldowns, k[0], k[1], k[2], create_if_missing=False)
                        or {}
                    ).get("cooldown_until_iteration")
                )
                or 0
            ),
        }
        for k in sorted(list(exhausted_keys))
    ]
    fallback_diagnosis["active_cooldown_subspaces"] = [
        {"parameter": k[0], "normalized_from": k[1], "normalized_to": k[2]}
        for k in sorted(list(active_cooldown_keys))
    ][:8]
    fallback_diagnosis["memory_hard_blocked_subspaces"] = [
        {
            "parameter": k[0],
            "normalized_from": k[1],
            "normalized_to": k[2],
            "reason": clean_text(v.get("reason", "")),
            "attempts": int(v.get("total_attempts", 0)),
            "accepted": int(v.get("accepted_count", 0)),
            "rejected": int(v.get("rejected_count", 0)),
        }
        for k, v in sorted(memory_exhausted_subspaces.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2]))
    ][:12]
    fallback_diagnosis["parameter_effect_memory_used"] = [
        {
            "parameter": p,
            "attempts": int(v.get("attempts", 0)),
            "accept_ratio": to_float(v.get("accept_ratio")),
            "avg_delta_w52_spy_compare": to_float(v.get("avg_delta_w52_spy_compare")),
            "harmful_like": int(v.get("harmful_like", 0)),
            "strong_positive_like": int(v.get("strong_positive_like", 0)),
        }
        for p, v in sorted(
            (parameter_effect_summary or {}).items(),
            key=lambda kv: (-int(to_float((kv[1] or {}).get("attempts")) or 0), kv[0]),
        )[:8]
    ]

    next_change_audit: Dict[str, Any] = {
        "next_change_present": False,
        "proposal_source": "adaptive_fallback",
        "next_change_consumed": False,
        "next_change_rejected": False,
        "next_change_rejected_reason": "",
        "next_change_zigzag_override": False,
        "next_change_zigzag_override_reason": "",
        "next_change_recent_feedback_override": False,
        "recent_feedback_ignored_reason": "",
        "original_recent_feedback_reason": "",
        "original_rejection_reason": "",
        "next_change_parameter": "",
        "next_change_from": None,
        "next_change_to": None,
    }

    def _try_prepared_next_change() -> Optional[Dict[str, Any]]:
        nonlocal next_change_audit
        next_change_path = Path("state") / "next_change.json"
        next_change_raw = load_json(next_change_path, {})
        if not isinstance(next_change_raw, dict) or clean_text(next_change_raw.get("status", "")) != "prepared":
            return None
        next_change_audit["next_change_present"] = True

        next_change = next_change_raw.get("recommended_next_change", {})
        if not isinstance(next_change, dict):
            next_change_audit.update(
                {
                    "next_change_rejected": True,
                    "next_change_rejected_reason": "next_change_missing_recommended_next_change",
                }
            )
            return None

        spec_parent = clean_text(next_change_raw.get("parent_run_id", ""))
        if spec_parent and spec_parent != clean_text(last_run_id):
            next_change_audit.update(
                {
                    "next_change_rejected": True,
                    "next_change_rejected_reason": "next_change_parent_mismatch",
                    "next_change_parameter": clean_text(next_change.get("parameter", "")),
                    "next_change_from": next_change.get("from_value"),
                    "next_change_to": next_change.get("to_value"),
                }
            )
            return None

        param = clean_text(next_change.get("parameter", ""))
        from_value = next_change.get("from_value")
        to_value = next_change.get("to_value")
        if not param:
            next_change_audit.update(
                {
                    "next_change_rejected": True,
                    "next_change_rejected_reason": "next_change_missing_parameter",
                }
            )
            return None

        next_change_audit.update(
            {
                "next_change_parameter": param,
                "next_change_from": from_value,
                "next_change_to": to_value,
            }
        )

        if normalize_scalar(from_value) == normalize_scalar(to_value):
            next_change_audit.update(
                {
                    "next_change_rejected": True,
                    "next_change_rejected_reason": f"next_change_no_op:{param}:{normalize_scalar(from_value)}->{normalize_scalar(to_value)}",
                }
            )
            return None

        dep_param, dep_value, dep_reason = _next_change_dependency_requirement(param)
        if dep_param and normalize_scalar(parent_cfg.get(dep_param)) != normalize_scalar(dep_value):
            next_change_audit.update(
                {
                    "next_change_rejected": True,
                    "next_change_rejected_reason": f"dependency_gate_disabled:{dep_param}={normalize_scalar(dep_value)}",
                }
            )
            return None

        proposal_cfg = dict(parent_cfg)
        proposal_cfg[param] = to_value
        if _already_tested(proposal_cfg):
            next_change_audit.update(
                {
                    "next_change_rejected": True,
                    "next_change_rejected_reason": "config_hash_already_tested_executed_run",
                }
            )
            return None

        ex_key = (param, normalize_scalar(from_value), normalize_scalar(to_value))
        if ex_key in active_cooldown_keys:
            cd_entry = get_subspace_cooldown_entry(subspace_cooldowns, param, from_value, to_value, create_if_missing=False) or {}
            next_change_audit.update(
                {
                    "next_change_rejected": True,
                    "next_change_rejected_reason": "cooldown_active",
                    "cooldown_until_iteration": int(to_float(cd_entry.get("cooldown_until_iteration")) or 0),
                    "cooldown_reason": clean_text(cd_entry.get("reason", "")),
                }
            )
            return None
        if ex_key in exhausted_keys:
            next_change_audit.update(
                {
                    "next_change_rejected": True,
                    "next_change_rejected_reason": "hard_blocked_exhausted_or_memory_subspace",
                }
            )
            return None

        blocked_match = [
            x for x in recent_feedback.get("recent_blocked_transitions", set())
            if x[0] == param and x[1] == normalize_scalar(to_value)
        ]
        if blocked_match:
            recent_feedback_override = is_recent_feedback_only_zigzag_for_same_next_change(
                recent_feedback=recent_feedback,
                parameter=param,
                from_value=from_value,
                to_value=to_value,
                next_change=next_change,
            )
            if bool(recent_feedback_override.get("allowed", False)):
                next_change_audit.update(
                    {
                        "next_change_recent_feedback_override": True,
                        "recent_feedback_ignored_reason": clean_text(recent_feedback_override.get("reason", "")),
                        "original_recent_feedback_reason": clean_text(recent_feedback_override.get("original_reason", "")),
                    }
                )
            else:
                next_change_audit.update(
                    {
                        "next_change_rejected": True,
                        "next_change_rejected_reason": "recent_coordinator_block_feedback",
                        "original_recent_feedback_reason": clean_text(recent_feedback_override.get("original_reason", "")),
                    }
                )
                return None

        proposal = {
            "role": "analyst",
            "status": "proposal_ready",
            "proposal_status": "proposal_ready",
            "proposal_source": "next_change",
            "mode": mode_to_analyst_style(current_mode),
            "research_mode_context": current_mode,
            "change_intent": infer_change_intent_from_mode(current_mode),
            "source": "next_change",
            "queue_test_id": "",
            "parent_run_id": last_run_id,
            "analysis_reference_run_id": last_run_id,
            "diagnosis": (
                "next_change preparado consumido antes de adaptive_fallback; se prioriza cambio controlado validado."
            ),
            "hypothesis": clean_text(next_change.get("why", "")) or clean_text(next_change.get("why_improve", "")) or "next_change",
            "main_change": {
                "parameter": param,
                "from_value": from_value,
                "to_value": to_value,
                "meaning": clean_text(next_change.get("family", "")) or clean_text(next_change.get("meaning", "")),
                "purpose": clean_text(next_change.get("why", "")) or clean_text(next_change.get("purpose", "")),
                "why_improve": clean_text(next_change.get("why", "")) or clean_text(next_change.get("why_improve", "")),
            },
            "dependent_change": None,
            "expected_effect": clean_text(next_change.get("expected_effect", "")) or "next_change_consumed",
            "compare_windows": windows,
            "compare_vs_spy": True,
            "prioritize_robustness_over_short_term": True,
            "revert_explicit": False,
            "revert_justification": "",
            "proposal_config": proposal_cfg,
            "fallback_diagnosis": fallback_diagnosis,
            "fallback_candidate_pool_considered": [],
            "fallback_selected_reason": "next_change_consumed",
            "candidate_is_exploratory": False,
            "exploratory_reason": "",
            "bypassed_soft_cooldown": False,
            "hard_block_bypassed": False,
            "next_change_consumed": True,
            "next_change_rejected": False,
            "next_change_rejected_reason": "",
            "next_change_parameter": param,
            "next_change_from": from_value,
            "next_change_to": to_value,
        }
        anchor_eval = evaluate_branch_anchor_conflict(proposal, anchor_state)
        if bool(anchor_eval.get("blocked", False)):
            next_change_audit.update(
                {
                    "next_change_rejected": True,
                    "next_change_rejected_reason": "branch_anchor_locked",
                }
            )
            return None

        materiality_check = validate_main_change_materiality(proposal)
        if not bool(materiality_check.get("material_change_detected", False)):
            next_change_audit.update(
                {
                    "next_change_rejected": True,
                    "next_change_rejected_reason": "non_material_candidate",
                }
            )
            return None

        transition_eval = classify_param_transition(rows, proposal, parent_cfg)
        transition_details = transition_eval.get("details", [])
        transition_class = ""
        if transition_details:
            transition_class = clean_text(transition_details[0].get("classification", ""))
        if transition_class in {"no_op_equivalence", "duplicate_recent_proposal"}:
            next_change_audit.update(
                {
                    "next_change_rejected": True,
                    "next_change_rejected_reason": f"transition_{transition_class}",
                }
            )
            return None
        if transition_class == "true_zigzag_reversal":
            allow_zigzag_countermove = bool(next_change.get("allow_zigzag_countermove", False))
            override_reason = clean_text(next_change.get("override_reason", "")) or clean_text(
                next_change.get("evidence_reason", "")
            )
            evidence_items = next_change.get("evidence", [])
            if not allow_zigzag_countermove or not override_reason or not isinstance(evidence_items, list) or not evidence_items:
                next_change_audit.update(
                    {
                        "next_change_rejected": True,
                        "next_change_rejected_reason": "transition_true_zigzag_reversal",
                    }
                )
                return None
            next_change_audit.update(
                {
                    "next_change_zigzag_override": True,
                    "next_change_zigzag_override_reason": override_reason,
                    "original_rejection_reason": "transition_true_zigzag_reversal",
                }
            )

        candidate_type = candidate_type_from_parameter(param)
        if mode_hard_block_candidate(
            current_mode=current_mode,
            candidate_type=candidate_type,
            parameter=param,
        ):
            next_change_audit.update(
                {
                    "next_change_rejected": True,
                    "next_change_rejected_reason": "blocked_by_current_mode",
                }
            )
            return None

        parameter_recent_attempts = count_recent_parameter_attempts(
            rows=rows,
            parameter=param,
            lookback=50,
            current_parent_run_id="",
        )
        transition_recent_attempts = count_recent_transition_attempts(
            rows=rows,
            parameter=param,
            from_value=from_value,
            to_value=to_value,
            lookback=50,
            current_parent_run_id="",
        )
        effect_entry = (
            get_parameter_effect_entry(
                parameter_effect_memory,
                param,
                from_value,
                to_value,
                create_if_missing=False,
            )
            or {}
        )
        proposal["selection_trace"] = {
            "current_mode": current_mode,
            "change_intent": proposal.get("change_intent"),
            "selection_reason": "next_change_consumed",
            "orthogonal_force_active": False,
            "selected_is_orthogonal": False,
            "recommended_change_directions": recommended_change_directions[:3],
            "historical_memory_used": {
                "parameter_effect_summary_top": fallback_diagnosis.get("parameter_effect_memory_used", [])[:5],
                "chosen_transition_effect_memory": {
                    "parameter": param,
                    "from_value": normalize_scalar(from_value),
                    "to_value": normalize_scalar(to_value),
                    "current_effect_class": clean_text(effect_entry.get("current_effect_class", "")),
                    "total_attempts": int(to_float(effect_entry.get("total_attempts")) or 0),
                    "accepted_count": int(to_float(effect_entry.get("accepted_count")) or 0),
                    "rejected_count": int(to_float(effect_entry.get("rejected_count")) or 0),
                    "avg_delta_w52_spy_compare": to_float(effect_entry.get("avg_delta_w52_spy_compare")),
                    "avg_delta_w52_trades": to_float(effect_entry.get("avg_delta_w52_trades")),
                    "avg_delta_w52_avg_net_return_pct": to_float(effect_entry.get("avg_delta_w52_avg_net_return_pct")),
                },
                "active_cooldown_subspaces": fallback_diagnosis.get("active_cooldown_subspaces", [])[:8],
            },
            "alternatives_discarded": [],
        }
        proposal["candidate_generation_diagnostic_output"] = build_candidate_generation_diagnostic_output(
            parent_run_id=last_run_id,
            proposal_status=proposal["proposal_status"],
            fallback_candidate_pool_considered=[],
            fallback_diagnosis=fallback_diagnosis,
            selected_proposal=proposal,
            force_axis_reset=bool(branch_state.get("force_axis_reset", False)),
            force_new_candidate_family=bool(branch_state.get("force_new_candidate_family", False)),
            consecutive_no_material_candidate=int(no_material_recent_streak),
        )
        next_change_audit.update(
            {
                "proposal_source": "next_change",
                "next_change_consumed": True,
                "next_change_rejected": False,
                "next_change_rejected_reason": "",
            }
        )
        return proposal

    next_change_proposal = _try_prepared_next_change()
    if isinstance(next_change_proposal, dict):
        next_change_proposal = apply_next_change_trace(next_change_proposal, next_change_audit)
        next_change_proposal.pop("_selection_meta", None)
        return next_change_proposal

    fallback_candidates = [
        {
            "parameter": "MAX_CLOSE_VS_SMA50_PCT",
            "candidate_values": [0.35, 0.45, 0.65, 0.75],
            "requires_parameter": "ENABLE_CLOSE_VS_SMA50_FILTER",
            "requires_value": True,
            "hypothesis": "Ajustar extension maxima del basket para mejorar calidad/frecuencia.",
            "meaning": "Ajustar umbral maximo de close_vs_sma50.",
            "purpose": "Controlar extension de entradas.",
            "why_improve": "Puede mejorar la relacion calidad/frecuencia con cambio acotado.",
            "expected_effect": "Menor ruido de basket con impacto moderado en frecuencia.",
        },
        {
            "parameter": "MIN_SPY_CHANNEL_R2",
            "candidate_values": [0.6, 0.5],
            "requires_parameter": "ENABLE_SPY_CHANNEL_R2_GATE",
            "requires_value": True,
            "hypothesis": "Ajuste fino del gate de contexto SPY para robustez de semanas operadas.",
            "meaning": "Subir o bajar levemente el minimo de R2 del canal SPY.",
            "purpose": "Equilibrar filtro de contexto y frecuencia operativa.",
            "why_improve": "Puede destrabar o endurecer semanas sin cambiar familia estrategica.",
            "expected_effect": "Cambio incremental en semanas operadas con impacto controlado en calidad.",
        },
        {
            "parameter": "MAX_AVG_PROFILE_DISTANCE",
            "candidate_values": [0.17, 0.22],
            "requires_parameter": "ENABLE_AVG_PROFILE_DISTANCE_GATE",
            "requires_value": True,
            "hypothesis": "Refinar gate de distancia de perfil para ajustar selectividad.",
            "meaning": "Ajustar umbral maximo de avg_profile_distance.",
            "purpose": "Balancear calidad del matching y frecuencia.",
            "why_improve": "Puede mover el cuello de botella principal de frecuencia.",
            "expected_effect": "Cambio directo en semanas filtradas por similitud.",
        },
        {
            "parameter": "TOP_SIMILAR_SPY_WEEKS",
            "candidate_values": [20, 28, 16],
            "requires_parameter": "",
            "requires_value": None,
            "hypothesis": "Ajustar cantidad de semanas similares para refinar estabilidad del perfil.",
            "meaning": "Cambiar el universo de semanas historicas usadas para el perfil.",
            "purpose": "Mejorar robustez del matching sin redisenar estrategia.",
            "why_improve": "Puede mejorar consistencia temporal del perfil global.",
            "expected_effect": "Ajuste de estabilidad del matching con impacto gradual.",
        },
        {
            "parameter": "TOP_CANDIDATES_NEXT_WEEK",
            "candidate_values": [2, 4, 5, 3],
            "requires_parameter": "",
            "requires_value": None,
            "hypothesis": "Ajustar capacidad semanal para balancear calidad y frecuencia de basket.",
            "meaning": "Cambiar cantidad de candidatos por semana.",
            "purpose": "Reducir ruido marginal o recuperar frecuencia.",
            "why_improve": "Puede mover la frontera frecuencia/calidad sin tocar salida.",
            "expected_effect": "Cambio directo en cantidad de trades semanales.",
        },
    ]

    fallback_candidate_pool_considered: List[Dict[str, Any]] = []
    candidate_evaluations: List[Dict[str, Any]] = []
    selected: Optional[Dict[str, Any]] = None
    selected_score = float("-inf")
    selected_reason = ""
    selected_is_orthogonal = False

    for candidate in fallback_candidates:
        param = str(candidate.get("parameter", ""))
        if not param:
            continue

        requires_param = str(candidate.get("requires_parameter", "") or "")
        if requires_param:
            requires_value = candidate.get("requires_value")
            if normalize_scalar(parent_cfg.get(requires_param)) != normalize_scalar(requires_value):
                fallback_candidate_pool_considered.append(
                    {
                        "parameter": param,
                        "to_value": "",
                        "state": "discarded",
                        "reason": f"requires_{requires_param}={normalize_scalar(requires_value)}",
                    }
                )
                continue

        from_value = parent_cfg.get(param)
        for to_value in list(candidate.get("candidate_values", [])):
            if normalize_scalar(from_value) == normalize_scalar(to_value):
                fallback_candidate_pool_considered.append(
                    {
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "no_op_equivalence",
                    }
                )
                continue

            ex_key = (param, normalize_scalar(from_value), normalize_scalar(to_value))
            if ex_key in active_cooldown_keys:
                cd_entry = get_subspace_cooldown_entry(subspace_cooldowns, param, from_value, to_value, create_if_missing=False) or {}
                fallback_candidate_pool_considered.append(
                    {
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "cooldown_active",
                        "cooldown_until_iteration": int(to_float(cd_entry.get("cooldown_until_iteration")) or 0),
                        "cooldown_reason": clean_text(cd_entry.get("reason", "")),
                    }
                )
                continue
            if ex_key in exhausted_keys:
                fallback_candidate_pool_considered.append(
                    {
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "hard_blocked_exhausted_or_memory_subspace",
                        "exhausted_stats": exhausted_subspaces.get(ex_key, {}),
                    }
                )
                continue

            proposal_cfg = dict(parent_cfg)
            proposal_cfg[param] = to_value
            if _already_tested(proposal_cfg):
                fallback_candidate_pool_considered.append(
                    {
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "config_hash_already_tested_executed_run",
                    }
                )
                continue
            blocked_key = (param, normalize_scalar(to_value))
            blocked_match = [
                x for x in recent_feedback.get("recent_blocked_transitions", set())
                if x[0] == blocked_key[0] and x[1] == blocked_key[1]
            ]
            if blocked_match:
                fallback_candidate_pool_considered.append(
                    {
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "recent_coordinator_block_feedback",
                        "blocked_feedback": [f"{b[0]}:{b[1]}:{b[2]}" for b in blocked_match],
                    }
                )
                continue

            proposal = {
                "role": "analyst",
                "mode": mode_to_analyst_style(current_mode),
                "research_mode_context": current_mode,
                "source": "adaptive_fallback",
                "queue_test_id": "",
                "parent_run_id": last_run_id,
                "analysis_reference_run_id": last_run_id,
                "diagnosis": (
                    "No hay tests iniciales pendientes; fallback adaptativo en base al parent y feedback reciente. "
                    f"diagnosis={diagnosis_category}"
                ),
                "hypothesis": clean_text(candidate.get("hypothesis", "")),
                "main_change": {
                    "parameter": param,
                    "from_value": from_value,
                    "to_value": to_value,
                    "meaning": clean_text(candidate.get("meaning", "")),
                    "purpose": clean_text(candidate.get("purpose", "")),
                    "why_improve": clean_text(candidate.get("why_improve", "")),
                },
                "dependent_change": None,
                "expected_effect": clean_text(candidate.get("expected_effect", "")),
                "compare_windows": windows,
                "compare_vs_spy": True,
                "prioritize_robustness_over_short_term": True,
                "revert_explicit": False,
                "revert_justification": "",
                "proposal_config": proposal_cfg,
                "fallback_diagnosis": fallback_diagnosis,
                "fallback_candidate_pool_considered": [],
                "fallback_selected_reason": "",
            }
            anchor_eval = evaluate_branch_anchor_conflict(proposal, anchor_state)
            if bool(anchor_eval.get("blocked", False)):
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_1",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "branch_anchor_locked",
                        "anchor_reasons": anchor_eval.get("reasons", []),
                    }
                )
                continue

            materiality_check = validate_main_change_materiality(proposal)
            if not bool(materiality_check.get("material_change_detected", False)):
                fallback_candidate_pool_considered.append(
                    {
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "non_material_candidate",
                    }
                )
                continue

            transition_eval = classify_param_transition(rows, proposal, parent_cfg)
            transition_details = transition_eval.get("details", [])
            transition_class = ""
            if transition_details:
                transition_class = clean_text(transition_details[0].get("classification", ""))
            if transition_class in {"no_op_equivalence", "duplicate_recent_proposal", "true_zigzag_reversal"}:
                fallback_candidate_pool_considered.append(
                    {
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": f"transition_{transition_class}",
                    }
                )
                continue

            candidate_type = candidate_type_from_parameter(param)
            parameter_recent_attempts = count_recent_parameter_attempts(
                rows=rows,
                parameter=param,
                lookback=50,
                current_parent_run_id="",
            )
            transition_recent_attempts = count_recent_transition_attempts(
                rows=rows,
                parameter=param,
                from_value=from_value,
                to_value=to_value,
                lookback=50,
                current_parent_run_id="",
            )
            is_orthogonal = int(recent_param_counts.get(param, 0)) == 0
            if mode_hard_block_candidate(
                current_mode=current_mode,
                candidate_type=candidate_type,
                parameter=param,
            ):
                fallback_candidate_pool_considered.append(
                    {
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "blocked_by_current_mode",
                        "current_mode": current_mode,
                        "candidate_type": candidate_type,
                    }
                )
                continue

            effect_entry = (
                get_parameter_effect_entry(
                    parameter_effect_memory,
                    param,
                    from_value,
                    to_value,
                    create_if_missing=False,
                )
                or {}
            )
            base_score = score_fallback_candidate(
                diagnosis_category=diagnosis_category,
                candidate_type=candidate_type,
                parameter=param,
                from_value=from_value,
                to_value=to_value,
                transition_classification=(transition_class or "fresh_change"),
                layer="layer_1",
                behavior_diag=behavior_diag,
                branch_health=branch_health,
                exhausted_subspaces=exhausted_subspaces,
                parameter_effect_entry=effect_entry,
                parameter_effect_summary=parameter_effect_summary,
                parameter_recent_attempts=parameter_recent_attempts,
                cooldown_active=bool(ex_key in active_cooldown_keys),
            )
            mode_adj = mode_score_adjustment(
                current_mode=current_mode,
                candidate_type=candidate_type,
                parameter=param,
                transition_classification=(transition_class or "fresh_change"),
                parameter_recent_attempts=parameter_recent_attempts,
                recent_param_counts=recent_param_counts,
                last_useful_param=last_useful_param,
            )
            stage4_adj, stage4_reasons = stage4_candidate_adjustment(
                parameter=param,
                from_value=from_value,
                to_value=to_value,
                candidate_type=candidate_type,
                current_mode=current_mode,
                branch_health=branch_health,
                main_friction=main_friction,
                recommended_dirs=recommended_change_directions,
                parameter_recent_attempts=parameter_recent_attempts,
                transition_recent_attempts=transition_recent_attempts,
                recent_param_counts=recent_param_counts,
                parameter_effect_entry=effect_entry,
                orthogonal_force_active=orthogonal_force_active,
            )
            score = base_score + mode_adj + stage4_adj
            proposal["_selection_meta"] = {
                "layer": "layer_1",
                "candidate_type": candidate_type,
                "is_orthogonal": bool(is_orthogonal),
                "parameter_recent_attempts": int(parameter_recent_attempts),
                "transition_recent_attempts": int(transition_recent_attempts),
                "base_score": round(base_score, 6),
                "mode_score_adjustment": round(mode_adj, 6),
                "stage4_score_adjustment": round(stage4_adj, 6),
                "stage4_reasons": list(stage4_reasons),
            }
            candidate_entry = {
                "parameter": param,
                "from_value": from_value,
                "to_value": to_value,
                "state": "valid",
                "reason": "material_candidate",
                "candidate_type": candidate_type,
                "current_mode": current_mode,
                "is_orthogonal": bool(is_orthogonal),
                "parameter_recent_attempts": int(parameter_recent_attempts),
                "transition_recent_attempts": int(transition_recent_attempts),
                "base_score": round(base_score, 6),
                "mode_score_adjustment": round(mode_adj, 6),
                "stage4_score_adjustment": round(stage4_adj, 6),
                "stage4_reasons": stage4_reasons,
                "transition_classification": transition_class or "fresh_change",
                "score": round(score, 6),
            }
            fallback_candidate_pool_considered.append(candidate_entry)
            candidate_evaluations.append(
                {
                    "proposal": proposal,
                    "score": float(score),
                    "layer": "layer_1",
                    "parameter": param,
                    "from_value": from_value,
                    "to_value": to_value,
                    "candidate_type": candidate_type,
                    "is_orthogonal": bool(is_orthogonal),
                }
            )
            if score > selected_score:
                selected = proposal
                selected_score = score
                selected_is_orthogonal = bool(is_orthogonal)
                selected_reason = (
                    f"selected_by_score={score:.4f} diagnosis={diagnosis_category} "
                    f"mode={current_mode} transition={candidate_entry['transition_classification']}"
                )

    # Capa 2 obligatoria: solo si la capa 1 no encontró candidato material.
    if selected is None:
        fallback_diagnosis["second_layer_executed"] = True
        second_layer_candidates: List[Dict[str, Any]] = []
        close_filter_enabled = normalize_scalar(parent_cfg.get("ENABLE_CLOSE_VS_SMA50_FILTER")) == "true"
        dist_gate_enabled = normalize_scalar(parent_cfg.get("ENABLE_AVG_PROFILE_DISTANCE_GATE")) == "true"
        r2_gate_enabled = normalize_scalar(parent_cfg.get("ENABLE_SPY_CHANNEL_R2_GATE")) == "true"
        rank_diag = (behavior_diag.get("rank_degradation") or {}) if isinstance(behavior_diag, dict) else {}
        rank_rapid = bool(rank_diag.get("rapid_degradation", False))

        # Monotonic refinements adicionales
        close_thr = to_float(parent_cfg.get("MAX_CLOSE_VS_SMA50_PCT"))
        if close_filter_enabled and close_thr is not None:
            for v in [round(max(0.1, close_thr - 0.15), 3), round(max(0.1, close_thr - 0.30), 3), round(min(2.5, close_thr + 0.15), 3)]:
                second_layer_candidates.append(
                    {
                        "parameter": "MAX_CLOSE_VS_SMA50_PCT",
                        "to_value": v,
                        "requires_parameter": "ENABLE_CLOSE_VS_SMA50_FILTER",
                        "requires_value": True,
                        "candidate_type": "quality_tightening" if v < close_thr else "controlled_reopening",
                        "hypothesis": "Refinamiento monotónico adicional en extensión del basket.",
                        "meaning": "Ajuste incremental de MAX_CLOSE_VS_SMA50_PCT.",
                        "purpose": "Profundizar señal sin zig-zag.",
                        "why_improve": "Permite explorar continuidad económica tras agotamiento del pool corto.",
                        "expected_effect": "Cambio incremental en calidad/frecuencia.",
                    }
                )

        dist_thr = to_float(parent_cfg.get("MAX_AVG_PROFILE_DISTANCE"))
        if dist_gate_enabled and dist_thr is not None:
            for v in [round(max(0.08, dist_thr - 0.02), 3), round(min(0.35, dist_thr + 0.02), 3)]:
                second_layer_candidates.append(
                    {
                        "parameter": "MAX_AVG_PROFILE_DISTANCE",
                        "to_value": v,
                        "requires_parameter": "ENABLE_AVG_PROFILE_DISTANCE_GATE",
                        "requires_value": True,
                        "candidate_type": "quality_tightening" if v < dist_thr else "controlled_reopening",
                        "hypothesis": "Refinar gate de distancia según semanas buenas vs malas.",
                        "meaning": "Ajuste incremental de MAX_AVG_PROFILE_DISTANCE.",
                        "purpose": "Corregir selectividad excesiva o insuficiente.",
                        "why_improve": "El diagnóstico sugiere recalibración del gate.",
                        "expected_effect": "Variación causal de semanas filtradas.",
                    }
                )

        r2_thr = to_float(parent_cfg.get("MIN_SPY_CHANNEL_R2"))
        if r2_gate_enabled and r2_thr is not None:
            for v in [round(max(0.30, r2_thr - 0.03), 3), round(min(0.90, r2_thr + 0.03), 3)]:
                second_layer_candidates.append(
                    {
                        "parameter": "MIN_SPY_CHANNEL_R2",
                        "to_value": v,
                        "requires_parameter": "ENABLE_SPY_CHANNEL_R2_GATE",
                        "requires_value": True,
                        "candidate_type": "quality_tightening" if v > r2_thr else "controlled_reopening",
                        "hypothesis": "Refinar gate de contexto SPY en segunda capa.",
                        "meaning": "Micro-ajuste de MIN_SPY_CHANNEL_R2.",
                        "purpose": "Balancear calidad de contexto y frecuencia.",
                        "why_improve": "Ajuste causal sin rediseño de estrategia.",
                        "expected_effect": "Impacto incremental en semanas habilitadas.",
                    }
                )

        # Diagnóstico por degradación de rank
        top_curr = int(round(to_float(parent_cfg.get("TOP_CANDIDATES_NEXT_WEEK")) or 5))
        if rank_rapid and top_curr > 2:
            second_layer_candidates.append(
                {
                    "parameter": "TOP_CANDIDATES_NEXT_WEEK",
                    "to_value": max(2, top_curr - 1),
                    "candidate_type": "rank_adjustment",
                    "hypothesis": "La degradación por rank sugiere recortar candidatos bajos.",
                    "meaning": "Reducir TOP_CANDIDATES_NEXT_WEEK.",
                    "purpose": "Mejorar calidad media del basket.",
                    "why_improve": "Los ranks bajos muestran deterioro relativo en el parent.",
                    "expected_effect": "Menos ruido por cola de ranking.",
                }
            )

        # Reactivación causal de gates apagados
        if not close_filter_enabled:
            second_layer_candidates.append(
                {
                    "parameter": "ENABLE_CLOSE_VS_SMA50_FILTER",
                    "to_value": True,
                    "candidate_type": "gate_reactivation",
                    "hypothesis": "Reactivar filtro de extensión para volver operativo MAX_CLOSE_VS_SMA50_PCT.",
                    "meaning": "Encender gate de extensión.",
                    "purpose": "Habilitar control causal de activos extendidos.",
                    "why_improve": "Sin gate activo, el umbral de extensión no tiene efecto real.",
                    "expected_effect": "Mayor control de calidad del basket.",
                    "dependent_change": {
                        "parameter": "MAX_CLOSE_VS_SMA50_PCT",
                        "to_value": 0.5,
                        "dependency_reason": "gate_activation_required",
                        "meaning": "Umbral inicial al activar filtro de extensión.",
                    },
                }
            )
        if not dist_gate_enabled:
            second_layer_candidates.append(
                {
                    "parameter": "ENABLE_AVG_PROFILE_DISTANCE_GATE",
                    "to_value": True,
                    "candidate_type": "gate_reactivation",
                    "hypothesis": "Reactivar gate de distancia para recuperar disciplina de matching.",
                    "meaning": "Encender gate de avg_profile_distance.",
                    "purpose": "Evitar semanas de perfil forzado.",
                    "why_improve": "El parámetro de distancia vuelve a ser operativo.",
                    "expected_effect": "Filtrado adicional de semanas ruidosas.",
                    "dependent_change": {
                        "parameter": "MAX_AVG_PROFILE_DISTANCE",
                        "to_value": 0.22,
                        "dependency_reason": "gate_activation_required",
                        "meaning": "Umbral inicial al reactivar gate de distancia.",
                    },
                }
            )

        for candidate in second_layer_candidates:
            param = str(candidate.get("parameter", ""))
            if not param:
                continue
            requires_param = str(candidate.get("requires_parameter", "") or "")
            if requires_param:
                requires_value = candidate.get("requires_value")
                if normalize_scalar(parent_cfg.get(requires_param)) != normalize_scalar(requires_value):
                    fallback_candidate_pool_considered.append(
                        {
                            "layer": "layer_2",
                            "parameter": param,
                            "to_value": "",
                            "state": "discarded",
                            "reason": f"requires_{requires_param}={normalize_scalar(requires_value)}",
                        }
                    )
                    continue

            from_value = parent_cfg.get(param)
            to_value = candidate.get("to_value")
            if normalize_scalar(from_value) == normalize_scalar(to_value):
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_2",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "no_op_equivalence",
                    }
                )
                continue

            ex_key = (param, normalize_scalar(from_value), normalize_scalar(to_value))
            if ex_key in active_cooldown_keys:
                cd_entry = get_subspace_cooldown_entry(subspace_cooldowns, param, from_value, to_value, create_if_missing=False) or {}
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_2",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "cooldown_active",
                        "cooldown_until_iteration": int(to_float(cd_entry.get("cooldown_until_iteration")) or 0),
                        "cooldown_reason": clean_text(cd_entry.get("reason", "")),
                    }
                )
                continue
            if ex_key in exhausted_keys:
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_2",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "hard_blocked_exhausted_or_memory_subspace",
                        "exhausted_stats": exhausted_subspaces.get(ex_key, {}),
                    }
                )
                continue

            blocked_key = (param, normalize_scalar(to_value))
            blocked_match = [
                x for x in recent_feedback.get("recent_blocked_transitions", set())
                if x[0] == blocked_key[0] and x[1] == blocked_key[1]
            ]
            if blocked_match:
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_2",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "recent_coordinator_block_feedback",
                        "blocked_feedback": [f"{b[0]}:{b[1]}:{b[2]}" for b in blocked_match],
                    }
                )
                continue

            proposal_cfg = dict(parent_cfg)
            proposal_cfg[param] = to_value
            dep_obj = None
            dep_cfg = candidate.get("dependent_change") or {}
            dep_param = clean_text(dep_cfg.get("parameter", ""))
            if dep_param:
                proposal_cfg[dep_param] = dep_cfg.get("to_value")
                dep_obj = {
                    "parameter": dep_param,
                    "from_value": parent_cfg.get(dep_param),
                    "to_value": dep_cfg.get("to_value"),
                    "dependency_reason": clean_text(dep_cfg.get("dependency_reason", "")),
                    "meaning": clean_text(dep_cfg.get("meaning", "")),
                }
            if _already_tested(proposal_cfg):
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_2",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "config_hash_already_tested_executed_run",
                    }
                )
                continue

            proposal = {
                "role": "analyst",
                "mode": mode_to_analyst_style(current_mode),
                "research_mode_context": current_mode,
                "source": "adaptive_fallback",
                "fallback_layer_used": "layer_2",
                "queue_test_id": "",
                "analysis_reference_run_id": last_run_id,
                "diagnosis": (
                    "Fallback capa 2 activo: diagnóstico por semanas/trades/rank/gates. "
                    f"diagnosis={diagnosis_category}"
                ),
                "hypothesis": clean_text(candidate.get("hypothesis", "")),
                "main_change": {
                    "parameter": param,
                    "from_value": from_value,
                    "to_value": to_value,
                    "meaning": clean_text(candidate.get("meaning", "")),
                    "purpose": clean_text(candidate.get("purpose", "")),
                    "why_improve": clean_text(candidate.get("why_improve", "")),
                },
                "dependent_change": dep_obj,
                "expected_effect": clean_text(candidate.get("expected_effect", "")),
                "compare_windows": windows,
                "compare_vs_spy": True,
                "prioritize_robustness_over_short_term": True,
                "revert_explicit": bool(candidate.get("revert_explicit", False)),
                "revert_justification": clean_text(candidate.get("revert_justification", "")),
                "proposal_config": proposal_cfg,
                "fallback_diagnosis": fallback_diagnosis,
                "fallback_candidate_pool_considered": [],
                "fallback_selected_reason": "",
            }
            anchor_eval = evaluate_branch_anchor_conflict(proposal, anchor_state)
            if bool(anchor_eval.get("blocked", False)):
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_2",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "branch_anchor_locked",
                        "anchor_reasons": anchor_eval.get("reasons", []),
                    }
                )
                continue

            materiality_check = validate_main_change_materiality(proposal)
            if not bool(materiality_check.get("material_change_detected", False)):
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_2",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "non_material_candidate",
                    }
                )
                continue

            transition_eval = classify_param_transition(rows, proposal, parent_cfg)
            transition_details = transition_eval.get("details", [])
            transition_class = ""
            if transition_details:
                transition_class = clean_text(transition_details[0].get("classification", ""))
            if transition_class in {"no_op_equivalence", "duplicate_recent_proposal", "true_zigzag_reversal"}:
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_2",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": f"transition_{transition_class}",
                    }
                )
                continue

            candidate_type = clean_text(candidate.get("candidate_type", "")) or "controlled_exploration"
            parameter_recent_attempts = count_recent_parameter_attempts(
                rows=rows,
                parameter=param,
                lookback=50,
                current_parent_run_id="",
            )
            transition_recent_attempts = count_recent_transition_attempts(
                rows=rows,
                parameter=param,
                from_value=from_value,
                to_value=to_value,
                lookback=50,
                current_parent_run_id="",
            )
            is_orthogonal = int(recent_param_counts.get(param, 0)) == 0
            if mode_hard_block_candidate(
                current_mode=current_mode,
                candidate_type=candidate_type,
                parameter=param,
            ):
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_2",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "blocked_by_current_mode",
                        "current_mode": current_mode,
                        "candidate_type": candidate_type,
                    }
                )
                continue

            effect_entry = (
                get_parameter_effect_entry(
                    parameter_effect_memory,
                    param,
                    from_value,
                    to_value,
                    create_if_missing=False,
                )
                or {}
            )
            base_score = score_fallback_candidate(
                diagnosis_category=diagnosis_category,
                candidate_type=candidate_type,
                parameter=param,
                from_value=from_value,
                to_value=to_value,
                transition_classification=(transition_class or "fresh_change"),
                layer="layer_2",
                behavior_diag=behavior_diag,
                branch_health=branch_health,
                exhausted_subspaces=exhausted_subspaces,
                parameter_effect_entry=effect_entry,
                parameter_effect_summary=parameter_effect_summary,
                parameter_recent_attempts=parameter_recent_attempts,
                cooldown_active=bool(ex_key in active_cooldown_keys),
            )
            mode_adj = mode_score_adjustment(
                current_mode=current_mode,
                candidate_type=candidate_type,
                parameter=param,
                transition_classification=(transition_class or "fresh_change"),
                parameter_recent_attempts=parameter_recent_attempts,
                recent_param_counts=recent_param_counts,
                last_useful_param=last_useful_param,
            )
            stage4_adj, stage4_reasons = stage4_candidate_adjustment(
                parameter=param,
                from_value=from_value,
                to_value=to_value,
                candidate_type=candidate_type,
                current_mode=current_mode,
                branch_health=branch_health,
                main_friction=main_friction,
                recommended_dirs=recommended_change_directions,
                parameter_recent_attempts=parameter_recent_attempts,
                transition_recent_attempts=transition_recent_attempts,
                recent_param_counts=recent_param_counts,
                parameter_effect_entry=effect_entry,
                orthogonal_force_active=orthogonal_force_active,
            )
            score = base_score + mode_adj + stage4_adj
            proposal["_selection_meta"] = {
                "layer": "layer_2",
                "candidate_type": candidate_type,
                "is_orthogonal": bool(is_orthogonal),
                "parameter_recent_attempts": int(parameter_recent_attempts),
                "transition_recent_attempts": int(transition_recent_attempts),
                "base_score": round(base_score, 6),
                "mode_score_adjustment": round(mode_adj, 6),
                "stage4_score_adjustment": round(stage4_adj, 6),
                "stage4_reasons": list(stage4_reasons),
            }
            candidate_entry = {
                "layer": "layer_2",
                "parameter": param,
                "from_value": from_value,
                "to_value": to_value,
                "state": "valid",
                "reason": "material_candidate",
                "candidate_type": candidate_type,
                "current_mode": current_mode,
                "is_orthogonal": bool(is_orthogonal),
                "parameter_recent_attempts": int(parameter_recent_attempts),
                "transition_recent_attempts": int(transition_recent_attempts),
                "base_score": round(base_score, 6),
                "mode_score_adjustment": round(mode_adj, 6),
                "stage4_score_adjustment": round(stage4_adj, 6),
                "stage4_reasons": stage4_reasons,
                "transition_classification": transition_class or "fresh_change",
                "score": round(score, 6),
            }
            fallback_candidate_pool_considered.append(candidate_entry)
            candidate_evaluations.append(
                {
                    "proposal": proposal,
                    "score": float(score),
                    "layer": "layer_2",
                    "parameter": param,
                    "from_value": from_value,
                    "to_value": to_value,
                    "candidate_type": candidate_type,
                    "is_orthogonal": bool(is_orthogonal),
                }
            )
            if score > selected_score:
                selected = proposal
                selected_score = score
                selected_is_orthogonal = bool(is_orthogonal)
                selected_reason = (
                    f"selected_by_score={score:.4f} diagnosis={diagnosis_category} "
                    f"mode={current_mode} layer=layer_2 transition={candidate_entry['transition_classification']}"
                )

    if selected and orthogonal_force_active and not selected_is_orthogonal:
        orthogonal_records = [r for r in candidate_evaluations if bool(r.get("is_orthogonal", False))]
        if orthogonal_records:
            best_orthogonal = max(orthogonal_records, key=lambda x: float(x.get("score", float("-inf"))))
            selected = best_orthogonal.get("proposal")
            selected_score = float(best_orthogonal.get("score", float("-inf")))
            selected_is_orthogonal = True
            selected_reason = (
                f"forced_orthogonal_axis score={selected_score:.4f} mode={current_mode} "
                "porque últimos cambios tocaron pocos parámetros"
            )

    if selected:
        main_sel = (selected.get("main_change") or {}) if isinstance(selected.get("main_change"), dict) else {}
        sel_param = clean_text(main_sel.get("parameter", ""))
        sel_from = main_sel.get("from_value")
        sel_to = main_sel.get("to_value")
        chosen_effect_entry = (
            get_parameter_effect_entry(
                parameter_effect_memory,
                sel_param,
                sel_from,
                sel_to,
                create_if_missing=False,
            )
            or {}
        )
        sorted_alternatives = sorted(
            [x for x in fallback_candidate_pool_considered if clean_text(x.get("state", "")) == "valid"],
            key=lambda x: to_float(x.get("score")) or float("-inf"),
            reverse=True,
        )
        top_alternatives: List[Dict[str, Any]] = []
        for x in sorted_alternatives:
            xp = clean_text(x.get("parameter", ""))
            xf = x.get("from_value")
            xt = x.get("to_value")
            if xp == sel_param and normalize_scalar(xf) == normalize_scalar(sel_from) and normalize_scalar(xt) == normalize_scalar(sel_to):
                continue
            top_alternatives.append(
                {
                    "parameter": xp,
                    "from_value": xf,
                    "to_value": xt,
                    "candidate_type": clean_text(x.get("candidate_type", "")),
                    "score": to_float(x.get("score")),
                    "reason": clean_text(x.get("reason", "")),
                    "discard_or_lower_priority_reason": "lower_score_or_forced_orthogonal_selection",
                }
            )
            if len(top_alternatives) >= 5:
                break

        selected["fallback_diagnosis"] = fallback_diagnosis
        selected["fallback_candidate_pool_considered"] = fallback_candidate_pool_considered
        selected["fallback_selected_reason"] = selected_reason
        selected["change_intent"] = infer_change_intent_from_mode(current_mode)
        selected["selection_trace"] = {
            "current_mode": current_mode,
            "change_intent": selected.get("change_intent"),
            "selection_reason": selected_reason,
            "orthogonal_force_active": bool(orthogonal_force_active),
            "selected_is_orthogonal": bool(selected_is_orthogonal),
            "recommended_change_directions": recommended_change_directions[:3],
            "historical_memory_used": {
                "parameter_effect_summary_top": fallback_diagnosis.get("parameter_effect_memory_used", [])[:5],
                "chosen_transition_effect_memory": {
                    "parameter": sel_param,
                    "from_value": normalize_scalar(sel_from),
                    "to_value": normalize_scalar(sel_to),
                    "current_effect_class": clean_text(chosen_effect_entry.get("current_effect_class", "")),
                    "total_attempts": int(to_float(chosen_effect_entry.get("total_attempts")) or 0),
                    "accepted_count": int(to_float(chosen_effect_entry.get("accepted_count")) or 0),
                    "rejected_count": int(to_float(chosen_effect_entry.get("rejected_count")) or 0),
                    "avg_delta_w52_spy_compare": to_float(chosen_effect_entry.get("avg_delta_w52_spy_compare")),
                    "avg_delta_w52_trades": to_float(chosen_effect_entry.get("avg_delta_w52_trades")),
                    "avg_delta_w52_avg_net_return_pct": to_float(chosen_effect_entry.get("avg_delta_w52_avg_net_return_pct")),
                },
                "active_cooldown_subspaces": fallback_diagnosis.get("active_cooldown_subspaces", [])[:8],
            },
            "alternatives_discarded": top_alternatives,
        }
        selected["proposal_status"] = clean_text(selected.get("status", "proposal_ready")) or "proposal_ready"
        selected["candidate_generation_diagnostic_output"] = build_candidate_generation_diagnostic_output(
            parent_run_id=last_run_id,
            proposal_status=selected["proposal_status"],
            fallback_candidate_pool_considered=fallback_candidate_pool_considered,
            fallback_diagnosis=fallback_diagnosis,
            selected_proposal=selected,
            force_axis_reset=bool(branch_state.get("force_axis_reset", False)),
            force_new_candidate_family=bool(branch_state.get("force_new_candidate_family", False)),
            consecutive_no_material_candidate=int(no_material_recent_streak),
        )
        selected = apply_next_change_trace(selected, next_change_audit)
        selected.pop("_selection_meta", None)
        return selected

    exploratory_trigger = bool(
        branch_force_orthogonal
        or no_material_recent_streak >= 5
        or len([x for x in fallback_candidate_pool_considered if clean_text(x.get("state", "")) == "valid"]) == 0
    )
    if exploratory_trigger:
        exploratory_candidates = build_exploratory_candidate_specs(parent_cfg)
        exploratory_selected: Optional[Dict[str, Any]] = None
        exploratory_reason = "candidate_pool_exhausted_need_orthogonal_axis"
        for candidate in exploratory_candidates:
            param = str(candidate.get("parameter", ""))
            if not param:
                continue
            from_value = parent_cfg.get(param)
            to_value = candidate.get("to_value")
            candidate_family = clean_text(candidate.get("candidate_family", "")) or candidate_family_from_parameter(param)
            if normalize_scalar(from_value) == normalize_scalar(to_value):
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_3",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "no_op_equivalence",
                        "candidate_family": candidate_family,
                    }
                )
                continue

            ex_key = (param, normalize_scalar(from_value), normalize_scalar(to_value))
            if ex_key in exhausted_keys:
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_3",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "hard_blocked_exhausted_or_memory_subspace",
                        "candidate_family": candidate_family,
                        "exhausted_stats": exhausted_subspaces.get(ex_key, {}),
                    }
                )
                continue

            proposal_cfg = dict(parent_cfg)
            proposal_cfg[param] = to_value
            if _already_tested(proposal_cfg):
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_3",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "config_hash_already_tested_executed_run",
                        "candidate_family": candidate_family,
                    }
                )
                continue

            blocked_key = (param, normalize_scalar(to_value))
            blocked_match = [
                x for x in recent_feedback.get("recent_blocked_transitions", set())
                if x[0] == blocked_key[0] and x[1] == blocked_key[1]
            ]
            if blocked_match:
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_3",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "recent_coordinator_block_feedback",
                        "candidate_family": candidate_family,
                        "blocked_feedback": [f"{b[0]}:{b[1]}:{b[2]}" for b in blocked_match],
                    }
                )
                continue

            proposal = {
                "role": "analyst",
                "status": "controlled_exploration_exploratory_candidate",
                "proposal_status": "controlled_exploration_exploratory_candidate",
                "mode": mode_to_analyst_style(current_mode),
                "research_mode_context": current_mode,
                "change_intent": infer_change_intent_from_mode(current_mode),
                "source": "adaptive_fallback",
                "fallback_layer_used": "layer_3",
                "queue_test_id": "",
                "parent_run_id": last_run_id,
                "analysis_reference_run_id": last_run_id,
                "diagnosis": (
                    "Exploratory fallback activo: la capa 1 y 2 quedaron saturadas; "
                    "se intenta una rama ortogonal segura."
                ),
                "hypothesis": "candidate_pool_exhausted_need_orthogonal_axis",
                "main_change": {
                    "parameter": param,
                    "from_value": from_value,
                    "to_value": to_value,
                    "meaning": clean_text(candidate.get("meaning", "")),
                    "purpose": clean_text(candidate.get("purpose", "")),
                    "why_improve": clean_text(candidate.get("why_improve", "")),
                },
                "dependent_change": None,
                "expected_effect": clean_text(candidate.get("expected_effect", "")),
                "compare_windows": windows,
                "compare_vs_spy": True,
                "prioritize_robustness_over_short_term": True,
                "revert_explicit": False,
                "revert_justification": "",
                "proposal_config": proposal_cfg,
                "fallback_diagnosis": fallback_diagnosis,
                "fallback_candidate_pool_considered": [],
                "fallback_selected_reason": exploratory_reason,
                "candidate_is_exploratory": True,
                "exploratory_reason": exploratory_reason,
                "bypassed_soft_cooldown": bool(ex_key in active_cooldown_keys),
                "hard_block_bypassed": False,
            }
            anchor_eval = evaluate_branch_anchor_conflict(proposal, anchor_state)
            if bool(anchor_eval.get("blocked", False)):
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_3",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "branch_anchor_locked",
                        "candidate_family": candidate_family,
                        "anchor_reasons": anchor_eval.get("reasons", []),
                    }
                )
                continue

            materiality_check = validate_main_change_materiality(proposal)
            if not bool(materiality_check.get("material_change_detected", False)):
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_3",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "non_material_candidate",
                        "candidate_family": candidate_family,
                    }
                )
                continue

            transition_eval = classify_param_transition(rows, proposal, parent_cfg)
            transition_details = transition_eval.get("details", [])
            transition_class = ""
            if transition_details:
                transition_class = clean_text(transition_details[0].get("classification", ""))
            if transition_class in {"no_op_equivalence", "duplicate_recent_proposal", "true_zigzag_reversal"}:
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_3",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": f"transition_{transition_class}",
                        "candidate_family": candidate_family,
                    }
                )
                continue

            candidate_type = clean_text(candidate.get("candidate_type", "")) or "controlled_exploration"
            if mode_hard_block_candidate(
                current_mode=current_mode,
                candidate_type=candidate_type,
                parameter=param,
            ):
                fallback_candidate_pool_considered.append(
                    {
                        "layer": "layer_3",
                        "parameter": param,
                        "from_value": from_value,
                        "to_value": to_value,
                        "state": "discarded",
                        "reason": "blocked_by_current_mode",
                        "candidate_family": candidate_family,
                        "current_mode": current_mode,
                        "candidate_type": candidate_type,
                    }
                )
                continue

            parameter_recent_attempts = count_recent_parameter_attempts(
                rows=rows,
                parameter=param,
                lookback=50,
                current_parent_run_id="",
            )
            transition_recent_attempts = count_recent_transition_attempts(
                rows=rows,
                parameter=param,
                from_value=from_value,
                to_value=to_value,
                lookback=50,
                current_parent_run_id="",
            )
            is_orthogonal = int(recent_param_counts.get(param, 0)) == 0
            effect_entry = (
                get_parameter_effect_entry(
                    parameter_effect_memory,
                    param,
                    from_value,
                    to_value,
                    create_if_missing=False,
                )
                or {}
            )
            bypassed_soft_cooldown = bool(ex_key in active_cooldown_keys)
            score = score_fallback_candidate(
                diagnosis_category=diagnosis_category,
                candidate_type=candidate_type,
                parameter=param,
                from_value=from_value,
                to_value=to_value,
                transition_classification=(transition_class or "fresh_change"),
                layer="layer_3",
                behavior_diag=behavior_diag,
                branch_health=branch_health,
                exhausted_subspaces=exhausted_subspaces,
                parameter_effect_entry=effect_entry,
                parameter_effect_summary=parameter_effect_summary,
                parameter_recent_attempts=parameter_recent_attempts,
                cooldown_active=False if bypassed_soft_cooldown else bool(ex_key in active_cooldown_keys),
            )
            mode_adj = mode_score_adjustment(
                current_mode=current_mode,
                candidate_type=candidate_type,
                parameter=param,
                transition_classification=(transition_class or "fresh_change"),
                parameter_recent_attempts=parameter_recent_attempts,
                recent_param_counts=recent_param_counts,
                last_useful_param=last_useful_param,
            )
            stage4_adj, stage4_reasons = stage4_candidate_adjustment(
                parameter=param,
                from_value=from_value,
                to_value=to_value,
                candidate_type=candidate_type,
                current_mode=current_mode,
                branch_health=branch_health,
                main_friction=main_friction,
                recommended_dirs=recommended_change_directions,
                parameter_recent_attempts=parameter_recent_attempts,
                transition_recent_attempts=transition_recent_attempts,
                recent_param_counts=recent_param_counts,
                parameter_effect_entry=effect_entry,
                orthogonal_force_active=orthogonal_force_active,
            )
            score = score + mode_adj + stage4_adj
            proposal["_selection_meta"] = {
                "layer": "layer_3",
                "candidate_type": candidate_type,
                "is_orthogonal": bool(is_orthogonal),
                "parameter_recent_attempts": int(parameter_recent_attempts),
                "transition_recent_attempts": int(transition_recent_attempts),
                "base_score": round(score - mode_adj - stage4_adj, 6),
                "mode_score_adjustment": round(mode_adj, 6),
                "stage4_score_adjustment": round(stage4_adj, 6),
                "stage4_reasons": list(stage4_reasons),
            }
            proposal["bypassed_soft_cooldown"] = bypassed_soft_cooldown
            proposal["hard_block_bypassed"] = False
            candidate_entry = {
                "layer": "layer_3",
                "parameter": param,
                "from_value": from_value,
                "to_value": to_value,
                "state": "valid",
                "reason": "controlled_exploration_exploratory_candidate",
                "candidate_type": candidate_type,
                "candidate_family": candidate_family,
                "current_mode": current_mode,
                "is_orthogonal": bool(is_orthogonal),
                "parameter_recent_attempts": int(parameter_recent_attempts),
                "transition_recent_attempts": int(transition_recent_attempts),
                "base_score": round(score - mode_adj - stage4_adj, 6),
                "mode_score_adjustment": round(mode_adj, 6),
                "stage4_score_adjustment": round(stage4_adj, 6),
                "stage4_reasons": stage4_reasons,
                "transition_classification": transition_class or "fresh_change",
                "score": round(score, 6),
                "bypassed_soft_cooldown": bypassed_soft_cooldown,
            }
            fallback_candidate_pool_considered.append(candidate_entry)
            candidate_evaluations.append(
                {
                    "proposal": proposal,
                    "score": float(score),
                    "layer": "layer_3",
                    "parameter": param,
                    "from_value": from_value,
                    "to_value": to_value,
                    "candidate_type": candidate_type,
                    "is_orthogonal": bool(is_orthogonal),
                }
            )
            if score > selected_score:
                exploratory_selected = proposal
                selected = proposal
                selected_score = score
                selected_is_orthogonal = bool(is_orthogonal)
                selected_reason = (
                    f"controlled_exploration_exploratory_candidate score={score:.4f} diagnosis={diagnosis_category} "
                    f"mode={current_mode} transition={candidate_entry['transition_classification']}"
                )

        if exploratory_selected is not None:
            selected = exploratory_selected
            selected["fallback_diagnosis"] = fallback_diagnosis
            selected["fallback_candidate_pool_considered"] = fallback_candidate_pool_considered
            selected["fallback_selected_reason"] = selected_reason
            selected["change_intent"] = infer_change_intent_from_mode(current_mode)
            selected["selection_trace"] = {
                "current_mode": current_mode,
                "change_intent": selected.get("change_intent"),
                "selection_reason": selected_reason,
                "orthogonal_force_active": bool(orthogonal_force_active),
                "selected_is_orthogonal": bool(selected_is_orthogonal),
                "recommended_change_directions": recommended_change_directions[:3],
                "historical_memory_used": {
                    "parameter_effect_summary_top": fallback_diagnosis.get("parameter_effect_memory_used", [])[:5],
                    "chosen_transition_effect_memory": {
                        "parameter": clean_text((selected.get("main_change") or {}).get("parameter", "")),
                        "from_value": normalize_scalar((selected.get("main_change") or {}).get("from_value")),
                        "to_value": normalize_scalar((selected.get("main_change") or {}).get("to_value")),
                    },
                    "active_cooldown_subspaces": fallback_diagnosis.get("active_cooldown_subspaces", [])[:8],
                },
                "alternatives_discarded": [],
            }
            selected["candidate_generation_diagnostic_output"] = build_candidate_generation_diagnostic_output(
                parent_run_id=last_run_id,
                proposal_status=selected["status"],
                fallback_candidate_pool_considered=fallback_candidate_pool_considered,
                fallback_diagnosis=fallback_diagnosis,
                selected_proposal=selected,
                force_axis_reset=bool(branch_state.get("force_axis_reset", False)),
                force_new_candidate_family=bool(branch_state.get("force_new_candidate_family", False)),
                consecutive_no_material_candidate=int(no_material_recent_streak),
            )
            selected = apply_next_change_trace(selected, next_change_audit)
            selected.pop("_selection_meta", None)
            return selected

    fallback_diagnosis["second_layer_executed"] = True
    no_material_proposal = build_no_material_candidate_proposal(
        parent_cfg=parent_cfg,
        last_valid_ctx=last_valid_ctx,
        windows=windows,
        source="adaptive_fallback",
        diagnosis=(
            "No hay tests iniciales pendientes y no se encontro cambio material tras fallback de dos capas "
            "(pool corto + diagnostico semanas/trades/rank/gates)."
        ),
        reason=(
            "No existen candidatos materiales validos luego de agotar capa 1 y capa 2. "
            "Ver fallback_candidate_pool_considered para trazabilidad."
        ),
        fallback_diagnosis=fallback_diagnosis,
        fallback_candidate_pool_considered=fallback_candidate_pool_considered,
        current_mode=current_mode,
        candidate_generation_diagnostic_output=build_candidate_generation_diagnostic_output(
            parent_run_id=last_run_id,
            proposal_status="no_material_candidate_found",
            fallback_candidate_pool_considered=fallback_candidate_pool_considered,
            fallback_diagnosis=fallback_diagnosis,
            selected_proposal=None,
            force_axis_reset=bool(branch_state.get("force_axis_reset", False)),
            force_new_candidate_family=bool(branch_state.get("force_new_candidate_family", False)),
            consecutive_no_material_candidate=int(no_material_recent_streak),
        ),
    )
    no_material_proposal["proposal_status"] = "no_material_candidate_found"
    no_material_proposal = apply_next_change_trace(no_material_proposal, next_change_audit)
    return no_material_proposal

def changed_params_from_proposal(proposal: Dict[str, Any]) -> List[str]:
    out = []
    main = proposal.get("main_change") or {}
    dep = proposal.get("dependent_change") or {}
    if main.get("parameter"):
        out.append(str(main.get("parameter")))
    if dep.get("parameter"):
        out.append(str(dep.get("parameter")))
    return list(dict.fromkeys(out))


def normalize_for_compare(value: Any) -> str:
    return normalize_scalar(value)


def analyze_proposal_materiality(proposal: Dict[str, Any], parent_cfg: Dict[str, Any]) -> Dict[str, Any]:
    details: List[Dict[str, Any]] = []
    for role in ["main_change", "dependent_change"]:
        ch = proposal.get(role) or {}
        param = clean_text(ch.get("parameter", ""))
        if not param:
            continue
        from_value = ch.get("from_value")
        if from_value is None and param in parent_cfg:
            from_value = parent_cfg.get(param)
        to_value = ch.get("to_value")
        normalized_from = normalize_for_compare(from_value)
        normalized_to = normalize_for_compare(to_value)
        material = normalized_from != normalized_to
        details.append(
            {
                "role": role,
                "parameter": param,
                "from_value": from_value,
                "to_value": to_value,
                "normalized_from_value": normalized_from,
                "normalized_to_value": normalized_to,
                "material_change_detected": material,
            }
        )
    material_parameters = [d["parameter"] for d in details if bool(d.get("material_change_detected", False))]
    return {
        "material_change_detected": len(material_parameters) > 0,
        "no_op_detected": len(material_parameters) == 0,
        "material_parameters": material_parameters,
        "details": details,
    }


def _extract_param_history(
    rows: List[Dict[str, str]],
    parameter: str,
    lookback: int = 30,
    current_parent_run_id: str = "",
) -> List[Dict[str, Any]]:
    sorted_rows = sorted(rows, key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = sorted_rows[-lookback:] if lookback > 0 else sorted_rows
    out: List[Dict[str, Any]] = []
    eligible_statuses = {"run_ok", "run_partial_valid"}
    for r in recent:
        status = clean_text(r.get("status", ""))
        accepted_flag = clean_text(r.get("accepted_or_rejected", "")).lower()
        # Duplicate / zig-zag history must include rejected executed runs too.
        # Otherwise the analyst can repeat a rejected axis forever because it
        # never becomes a useful parent. Parent filtering is intentionally not
        # applied here: trackers and loop_trace may disagree on parent ids, and
        # repeated bad transitions should be blocked globally in the recent window.
        if status not in eligible_statuses or accepted_flag not in {"accepted", "rejected"}:
            continue
        run_id = clean_text(r.get("run_id", ""))
        for pf, ff, tf in [
            ("main_parameter", "main_from", "main_to"),
            ("dependent_parameter", "dependent_from", "dependent_to"),
        ]:
            p = clean_text(r.get(pf, ""))
            if p != parameter:
                continue
            f_raw = r.get(ff)
            t_raw = r.get(tf)
            f_norm = normalize_scalar(f_raw)
            t_norm = normalize_scalar(t_raw)
            if not f_norm and not t_norm:
                continue
            out.append(
                {
                    "run_id": run_id,
                    "status": status,
                    "from_value": f_raw,
                    "to_value": t_raw,
                    "normalized_from": f_norm,
                    "normalized_to": t_norm,
                }
            )
    return out


def count_recent_parameter_attempts(
    rows: List[Dict[str, str]],
    parameter: str,
    lookback: int = 25,
    current_parent_run_id: str = "",
) -> int:
    target = clean_text(parameter)
    if not target:
        return 0
    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = sorted_rows[-max(1, int(lookback)) :] if sorted_rows else []
    cnt = 0
    for r in recent:
        if clean_text(r.get("status", "")) not in {"run_ok", "run_partial_valid"}:
            continue
        if current_parent_run_id:
            row_parent = clean_text(r.get("parent_run_id", ""))
            if row_parent and row_parent != clean_text(current_parent_run_id):
                continue
        p = clean_text(r.get("main_parameter", ""))
        if p == target:
            cnt += 1
    return cnt


def _proposal_has_evidence_context(proposal: Dict[str, Any]) -> bool:
    if bool(proposal.get("revert_explicit", False)):
        return True
    text = " ".join(
        [
            clean_text(proposal.get("diagnosis", "")),
            clean_text(proposal.get("hypothesis", "")),
            clean_text(proposal.get("revert_justification", "")),
            clean_text(proposal.get("fallback_selected_reason", "")),
        ]
    ).lower()
    negative_patterns = ["sin evidencia", "no evidencia", "sin justific", "no justific"]
    if any(p in text for p in negative_patterns):
        # Solo se considera evidencia si además aparecen señales fuertes explícitas.
        strong_tokens = ["deterior", "degrad", "rollback", "revert_explicit", "justificado por", "basado en"]
        return any(tok in text for tok in strong_tokens)
    evidence_tokens = [
        "deterior",
        "degrad",
        "rollback",
        "revert",
        "justificado por",
        "basado en",
        "evidence_based",
        "por evidencia",
    ]
    return any(tok in text for tok in evidence_tokens)


def _classify_single_transition(
    history: List[Dict[str, Any]],
    normalized_from: str,
    normalized_to: str,
    proposal: Dict[str, Any],
) -> Tuple[str, str]:
    if normalized_from == normalized_to:
        return "no_op_equivalence", "normalize(from)==normalize(to)"

    has_evidence = _proposal_has_evidence_context(proposal)
    if not history:
        return "fresh_change", "sin historial previo para este parametro"

    prev = history[-1]
    prev_from = str(prev.get("normalized_from", ""))
    prev_to = str(prev.get("normalized_to", ""))

    # Repeticion exacta del ultimo cambio: duplicado reciente (no zig-zag).
    if prev_from == normalized_from and prev_to == normalized_to:
        return "duplicate_recent_proposal", "repite exactamente el ultimo cambio reciente"

    # Reversion directa A->B seguida de B->A.
    if prev_from == normalized_to and prev_to == normalized_from:
        if has_evidence:
            return "evidence_based_rollback", f"rollback justificado sobre {prev_from}->{prev_to}"
        return "true_zigzag_reversal", f"reversion exacta de {prev_from}->{prev_to} sin evidencia nueva"

    seen_to_values = {str(h.get("normalized_to", "")) for h in history}
    pf = to_float(prev_from)
    pt = to_float(prev_to)
    cf = to_float(normalized_from)
    ct = to_float(normalized_to)
    if None not in (pf, pt, cf, ct):
        prev_delta = float(pt) - float(pf)
        curr_delta = float(ct) - float(cf)
        if prev_delta * curr_delta > 0:
            return "monotonic_refinement", "continuidad monotona respecto al ultimo cambio"
        if prev_delta * curr_delta < 0:
            if has_evidence:
                return "evidence_based_rollback", "cambio de direccion justificado por evidencia"
            return "true_zigzag_reversal", "cambio de direccion sin evidencia de rollback"
    if normalized_to not in seen_to_values:
        return "controlled_exploration", "rama nueva razonable con valor no probado en historial reciente"

    if has_evidence:
        return "evidence_based_rollback", "retoma valor previo con justificativo de evidencia"
    return "controlled_exploration", "ajuste no monotono sin patron de reversion directa"


def classify_param_transition(
    rows: List[Dict[str, str]],
    proposal: Dict[str, Any],
    parent_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    details: List[Dict[str, Any]] = []
    blocked_classes = {"true_zigzag_reversal"}

    current_parent_run_id = clean_text(proposal.get("parent_run_id", ""))
    for role in ["main_change", "dependent_change"]:
        ch = proposal.get(role) or {}
        param = clean_text(ch.get("parameter", ""))
        if not param:
            continue
        from_value = ch.get("from_value")
        if from_value is None and param in parent_cfg:
            from_value = parent_cfg.get(param)
        to_value = ch.get("to_value")
        normalized_from = normalize_scalar(from_value)
        normalized_to = normalize_scalar(to_value)
        history = _extract_param_history(
            rows,
            param,
            lookback=40,
            current_parent_run_id=current_parent_run_id,
        )
        classification, reason = _classify_single_transition(history, normalized_from, normalized_to, proposal)
        details.append(
            {
                "role": role,
                "parameter": param,
                "from_value": from_value,
                "to_value": to_value,
                "normalized_from_value": normalized_from,
                "normalized_to_value": normalized_to,
                "classification": classification,
                "reason": reason,
                "history_depth": len(history),
                "last_history_run_id": (history[-1].get("run_id", "") if history else ""),
            }
        )

    blocked = [d for d in details if d.get("classification") in blocked_classes]
    return {
        "blocked": len(blocked) > 0,
        "block_reasons": [f"{d.get('parameter')}:{d.get('classification')}" for d in blocked],
        "details": details,
    }


def is_explicit_revert_allowed(proposal: Dict[str, Any], rows: List[Dict[str, str]]) -> bool:
    if not bool(proposal.get("revert_explicit", False)):
        return False
    justification = clean_text(proposal.get("revert_justification", ""))
    if not justification:
        return False
    if not rows:
        return False
    sorted_rows = sorted(rows, key=lambda r: parse_run_id(r.get("run_id", "")))
    last = sorted_rows[-1]
    main = proposal.get("main_change") or {}
    param = str(main.get("parameter", ""))
    if not param:
        return False
    return param == str(last.get("main_parameter", "")) or param == str(last.get("dependent_parameter", ""))


def is_next_change_zigzag_override_allowed(proposal: Dict[str, Any]) -> bool:
    proposal_source = clean_text(proposal.get("proposal_source", "")) or clean_text(proposal.get("source", ""))
    if proposal_source != "next_change":
        return False
    if not bool(proposal.get("next_change_consumed", False)) and not bool(proposal.get("next_change_zigzag_override", False)):
        return False
    override_reason = clean_text(proposal.get("next_change_zigzag_override_reason", "")) or clean_text(
        proposal.get("override_reason", "")
    ) or clean_text(proposal.get("evidence_reason", ""))
    if not override_reason:
        return False
    original_rejection_reason = clean_text(proposal.get("original_rejection_reason", "")) or clean_text(
        proposal.get("next_change_rejected_reason", "")
    )
    if original_rejection_reason != "transition_true_zigzag_reversal":
        return False
    next_change_path = Path("state") / "next_change.json"
    next_change_raw = load_json(next_change_path, {})
    if not isinstance(next_change_raw, dict) or clean_text(next_change_raw.get("status", "")) != "prepared":
        return False
    next_change = next_change_raw.get("recommended_next_change", {})
    if not isinstance(next_change, dict):
        return False
    if clean_text(next_change_raw.get("parent_run_id", "")) != clean_text(proposal.get("parent_run_id", "")):
        return False
    if clean_text(next_change.get("parameter", "")) != clean_text((proposal.get("main_change") or {}).get("parameter", "")):
        return False
    if normalize_scalar(next_change.get("from_value")) != normalize_scalar((proposal.get("main_change") or {}).get("from_value")):
        return False
    if normalize_scalar(next_change.get("to_value")) != normalize_scalar((proposal.get("main_change") or {}).get("to_value")):
        return False
    if not bool(next_change.get("allow_zigzag_countermove", False)):
        return False
    override_reason = clean_text(next_change.get("override_reason", "")) or clean_text(next_change.get("evidence_reason", ""))
    if not override_reason:
        return False
    evidence_items = next_change.get("evidence", [])
    if not isinstance(evidence_items, list) or not evidence_items:
        return False
    return True


def run_preflight(
    repo: Path,
    dependencies_path: Path,
    candidate_cfg_path: Path,
    parent_cfg_path: Path,
    change_set_path: Path,
    output_path: Path,
) -> Dict[str, Any]:
    preflight_script = repo / "preflight_validator.ps1"
    if not preflight_script.exists():
        return {"pass": False, "blocked": [f"Falta {preflight_script.name}"], "effective_change_check": {}}
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(preflight_script),
        "-DependenciesPath", str(dependencies_path),
        "-CandidateConfigPath", str(candidate_cfg_path),
        "-ParentConfigPath", str(parent_cfg_path),
        "-ChangeSetPath", str(change_set_path),
        "-OutputPath", str(output_path),
    ]
    try:
        cp = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, timeout=120)
    except Exception as e:
        return {"pass": False, "blocked": [f"preflight_exception: {e}"], "effective_change_check": {}}
    obj = load_json(output_path, None)
    if isinstance(obj, dict):
        return obj
    text = (cp.stdout or "").strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except Exception:
            pass
    return {"pass": False, "blocked": [f"Preflight invalido rc={cp.returncode}"], "effective_change_check": {}}


def apply_config_to_script_text(script_text: str, cfg: Dict[str, Any], keys: List[str]) -> str:
    out = script_text
    for k in keys:
        if k not in cfg:
            continue
        try:
            out = set_py_const(out, k, to_py_literal(cfg[k]))
        except Exception:
            continue
    return out


def find_latest_file(root: Path, pattern: str) -> Optional[Path]:
    if not root.exists():
        return None
    files = sorted(root.rglob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def find_latest_csv_for_stem(root: Path, stem: str) -> Optional[Path]:
    pattern = f"*_{stem}_*.csv"
    return find_latest_file(root, pattern)


def collect_window_csv_artifacts(window_dir: Path) -> Dict[str, str]:
    stems = [
        "07_next_week_real_trades",
        "08_summary_by_regime_week",
        "09_summary_total",
        "06_next_week_candidates",
    ]
    out: Dict[str, str] = {}
    for stem in stems:
        p = find_latest_csv_for_stem(window_dir, stem)
        out[stem] = str(p) if p else ""
    return out


def extract_metrics_from_artifacts(
    repo: Path,
    python_exe: str,
    xlsx_path: Optional[Path],
    artifacts_dir: Optional[Path],
    weekly_csv: Optional[Path],
    tie_low: float,
    tie_high: float,
    max_regime_weeks: int = 0,
) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    has_weekly = bool(weekly_csv and weekly_csv.exists())
    has_xlsx = bool(xlsx_path and xlsx_path.exists())
    has_artifacts_dir = bool(artifacts_dir and artifacts_dir.exists())
    if (not has_weekly) or ((not has_xlsx) and (not has_artifacts_dir)):
        return metrics
    cfg = load_paths_config(repo)
    extract_rel = cfg_get_str(
        cfg, ["scripts", "extract_backtest_metrics"], "scripts/metrics/extract_backtest_metrics.py"
    )
    extract_script = (repo / extract_rel).resolve()
    e_cmd = [
        python_exe,
        str(extract_script),
        "--weekly-csv",
        str(weekly_csv),
        "--tie-low",
        str(tie_low),
        "--tie-high",
        str(tie_high),
    ]
    if has_xlsx and xlsx_path:
        e_cmd += ["--xlsx", str(xlsx_path)]
    if has_artifacts_dir and artifacts_dir:
        e_cmd += ["--base-dir", str(artifacts_dir)]
    if int(max_regime_weeks) > 0:
        e_cmd += ["--max-regime-weeks", str(int(max_regime_weeks))]
    try:
        ep = subprocess.run(e_cmd, cwd=str(repo), capture_output=True, text=True, timeout=180)
        if ep.returncode == 0:
            metrics = json.loads((ep.stdout or "{}").strip() or "{}")
        else:
            metrics = {"extract_error": (ep.stderr or "").strip()}
    except Exception as e:
        metrics = {"extract_error": str(e)}
    return metrics


def run_window_backtest(
    repo: Path,
    python_exe: str,
    candidate_script: Path,
    run_dir: Path,
    window_weeks: int,
    tie_low: float,
    tie_high: float,
    weekly_csv: Optional[Path],
    timeout_sec: int,
    lightweight_mode: bool = False,
    fast_artifacts_mode: bool = False,
    export_xlsx: bool = True,
    adaptive_workers_mode: bool = True,
    profile_enabled: bool = False,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    window_dir = run_dir / f"window_{window_weeks:02d}"
    window_dir.mkdir(parents=True, exist_ok=True)
    window_script = generated_script_path(window_dir, candidate_script.stem, f"w{window_weeks}")

    src_text = candidate_script.read_text(encoding="utf-8", errors="ignore")
    patched = src_text
    test_end_raw = parse_py_literal_basic(get_py_const_literal(src_text, "TEST_END"))
    require_next_raw = parse_py_literal_basic(get_py_const_literal(src_text, "REQUIRE_NEXT_WEEK_WITHIN_TEST_RANGE"))
    require_next = True if require_next_raw is None else bool(require_next_raw)
    dynamic_start = compute_last_n_weeks_start_date(
        weekly_csv=weekly_csv,
        test_end=test_end_raw,
        regime_weeks=int(window_weeks),
        require_next_within_test=require_next,
    )
    if dynamic_start:
        try:
            patched = set_py_const(patched, "TEST_START", to_py_literal(dynamic_start))
        except Exception:
            pass
    t_patch_1 = time.perf_counter()
    patched = set_py_const(patched, "REGIME_WEEKS_TO_RUN", to_py_literal(window_weeks))
    patched = set_py_const(patched, "OUTPUT_DIR", to_py_literal(str(window_dir)))
    patched = set_py_const(patched, "OUTPUT_IN_TIMESTAMP_SUBDIR", "True")
    if adaptive_workers_mode:
        cpu_cnt = os_cpu_count()
        cap = max(2, min(max(2, cpu_cnt - 1), 16))
        pre_workers = max(2, min(max(2, cpu_cnt // 2), 12))
        patched = set_py_const(patched, "PARALLEL_REGIME_WORKERS", "0")
        patched = set_py_const(patched, "AUTO_PARALLEL_WORKERS", "True")
        patched = set_py_const(patched, "MAX_PARALLEL_WORKERS_CAP", str(int(cap)))
        patched = set_py_const(patched, "PRECOMPUTE_WORKERS", str(int(pre_workers)))
    if fast_artifacts_mode:
        patched = set_py_const(patched, "EXPORT_SUMMARY_XLSX", "False")
        patched = set_py_const(patched, "EXPORT_CSVS_INCLUDED_IN_XLSX", "True")
        patched = set_py_const(patched, "EXPORT_SHEETS_INFO_TXT", "False")
    elif not export_xlsx:
        patched = set_py_const(patched, "EXPORT_SUMMARY_XLSX", "False")
        patched = set_py_const(patched, "EXPORT_CSVS_INCLUDED_IN_XLSX", "True")
        patched = set_py_const(patched, "EXPORT_SHEETS_INFO_TXT", "False")
    if lightweight_mode:
        patched = set_py_const(patched, "EXPORT_CSVS_INCLUDED_IN_XLSX", "True")
        patched = set_py_const(patched, "EXPORT_SHEETS_INFO_TXT", "False")

    # Optional persistent dataset cache. This prelude monkey-patches pandas.read_csv
    # inside the generated window script so repeated large CSV loads can be served
    # from Parquet across windows/iterations. It is intentionally best-effort:
    # any cache error falls back to the original CSV behavior.
    cache_prelude = (
        "# --- SPY DATASET CACHE PRELUDE (auto-injected by run_multi_agent_iteration.py) ---\n"
        "try:\n"
        "    import sys as _spy_sys\n"
        "    from pathlib import Path as _SpyPath\n"
        f"    _spy_repo = _SpyPath({to_py_literal(str(repo))})\n"
        "    if str(_spy_repo) not in _spy_sys.path:\n"
        "        _spy_sys.path.insert(0, str(_spy_repo))\n"
        "    from scripts.cache.dataset_cache import install_pandas_csv_cache as _spy_install_pandas_csv_cache\n"
        "    _spy_install_pandas_csv_cache(repo=_spy_repo)\n"
        "except Exception as _spy_cache_error:\n"
        "    try:\n"
        "        print(f'[dataset_cache] disabled: {_spy_cache_error}')\n"
        "    except Exception:\n"
        "        pass\n"
        "# --- END SPY DATASET CACHE PRELUDE ---\n"
    )
    if "SPY DATASET CACHE PRELUDE" not in patched:
        patched = insert_text_after_future_imports(patched, cache_prelude)

    window_script.write_text(patched, encoding="utf-8")
    t_patch_2 = time.perf_counter()

    out_log = window_dir / "stdout.log"
    err_log = window_dir / "stderr.log"
    # -u para logs en tiempo real aun con redireccion a archivo.
    cmd = [python_exe, "-u", str(window_script)]
    timed_out = False
    rc = -1
    stderr_text = ""
    proc: Optional[subprocess.Popen[str]] = None
    env = os.environ.copy()
    if profile_enabled:
        env["SPY_ENABLE_PROFILE"] = "1"
    t_exec_0 = time.perf_counter()
    try:
        with out_log.open("w", encoding="utf-8", buffering=1) as out_f, err_log.open("w", encoding="utf-8", buffering=1) as err_f:
            proc = subprocess.Popen(
                cmd,
                cwd=str(repo),
                stdout=out_f,
                stderr=err_f,
                text=True,
                env=env,
            )
            try:
                rc = proc.wait(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=10)
                except Exception:
                    pass
                rc = -1
        t_exec_1 = time.perf_counter()
    except Exception as e:
        stderr_text = f"executor_exception: {e}"
        err_log.write_text(stderr_text, encoding="utf-8")
        t_exec_1 = time.perf_counter()

    perf = {
        "patch_dynamic_start_sec": round(max(0.0, t_patch_1 - t0), 6),
        "patch_constants_sec": round(max(0.0, t_patch_2 - t_patch_1), 6),
        "subprocess_exec_sec": round(max(0.0, t_exec_1 - t_exec_0), 6),
    }

    if timed_out:
        return {
            "status": "run_error",
            "window": window_weeks,
            "requested_weeks": int(window_weeks),
            "actual_weeks_run": None,
            "depth_ok": False,
            "test_start_used": dynamic_start or "",
            "command": " ".join(cmd),
            "stdout_log": str(out_log),
            "stderr_log": str(err_log),
            "outputs": {"excel": "", "txt": "", "artifacts_dir": str(window_dir), "csv": {}},
            "metrics": {},
            "errors": [f"Timeout ejecutando ventana {window_weeks} semanas"],
            "perf": perf,
        }
    if rc != 0:
        return {
            "status": "run_error",
            "window": window_weeks,
            "requested_weeks": int(window_weeks),
            "actual_weeks_run": None,
            "depth_ok": False,
            "test_start_used": dynamic_start or "",
            "command": " ".join(cmd),
            "stdout_log": str(out_log),
            "stderr_log": str(err_log),
            "outputs": {"excel": "", "txt": "", "artifacts_dir": str(window_dir), "csv": {}},
            "metrics": {},
            "errors": [f"Exit code {rc} en ventana {window_weeks} semanas"],
            "perf": perf,
        }

    t_art_0 = time.perf_counter()
    xlsx = find_latest_file(window_dir, "spy_context_asset_profile_resumen_*.xlsx")
    info_txt = find_latest_file(window_dir, "spy_context_asset_profile_solapas_info_*.txt")
    csv_artifacts = collect_window_csv_artifacts(window_dir)
    has_csv_metrics = bool(csv_artifacts.get("08_summary_by_regime_week") and csv_artifacts.get("07_next_week_real_trades"))
    if (not xlsx) and (not has_csv_metrics):
        return {
            "status": "run_error",
            "window": window_weeks,
            "requested_weeks": int(window_weeks),
            "actual_weeks_run": None,
            "depth_ok": False,
            "test_start_used": dynamic_start or "",
            "command": " ".join(cmd),
            "stdout_log": str(out_log),
            "stderr_log": str(err_log),
            "outputs": {"excel": "", "txt": "", "artifacts_dir": str(window_dir), "csv": csv_artifacts},
            "metrics": {},
            "errors": [f"No se encontraron artefactos validos (xlsx/csv) para ventana {window_weeks}"],
            "perf": perf,
        }
    t_art_1 = time.perf_counter()

    t_ext_0 = time.perf_counter()
    metrics = extract_metrics_from_artifacts(
        repo=repo,
        python_exe=python_exe,
        xlsx_path=xlsx,
        artifacts_dir=window_dir,
        weekly_csv=weekly_csv,
        tie_low=tie_low,
        tie_high=tie_high,
        max_regime_weeks=0,
    )
    t_ext_1 = time.perf_counter()
    perf["artifact_discovery_sec"] = round(max(0.0, t_art_1 - t_art_0), 6)
    perf["extract_metrics_sec"] = round(max(0.0, t_ext_1 - t_ext_0), 6)
    perf["total_window_sec"] = round(max(0.0, t_ext_1 - t0), 6)

    actual_weeks_run = to_float((metrics or {}).get("weeks_run"))
    actual_weeks_int: Optional[int] = None
    if actual_weeks_run is not None:
        actual_weeks_int = int(round(actual_weeks_run))
    depth_ok = True
    depth_error = ""
    if actual_weeks_int is not None and actual_weeks_int < int(window_weeks):
        depth_ok = False
        depth_error = (
            f"insufficient_depth: requested={int(window_weeks)} actual_weeks_run={int(actual_weeks_int)}"
        )
    elif actual_weeks_int is None:
        depth_ok = False
        depth_error = f"missing_weeks_run_metric: requested={int(window_weeks)}"

    status = "run_ok" if depth_ok else "insufficient_depth"
    errors: List[str] = []
    if depth_error:
        errors.append(depth_error)

    return {
        "status": status,
        "window": window_weeks,
        "requested_weeks": int(window_weeks),
        "actual_weeks_run": actual_weeks_int,
        "depth_ok": depth_ok,
        "test_start_used": dynamic_start or "",
        "command": " ".join(cmd),
        "stdout_log": str(out_log),
        "stderr_log": str(err_log),
        "outputs": {
            "excel": str(xlsx) if xlsx else "",
            "txt": str(info_txt) if info_txt else "",
            "artifacts_dir": str(window_dir),
            "csv": csv_artifacts,
        },
        "metrics": metrics,
        "errors": errors,
        "perf": perf,
    }


def derive_window_result_from_existing_run(
    repo: Path,
    python_exe: str,
    base_result: Dict[str, Any],
    window_weeks: int,
    tie_low: float,
    tie_high: float,
    weekly_csv: Optional[Path],
) -> Dict[str, Any]:
    outputs = base_result.get("outputs", {}) if isinstance(base_result, dict) else {}
    xlsx_raw = clean_text(outputs.get("excel", ""))
    xlsx = Path(xlsx_raw) if xlsx_raw else None
    if xlsx and (not xlsx.exists()):
        xlsx = None
    artifacts_dir_raw = clean_text(outputs.get("artifacts_dir", ""))
    artifacts_dir = Path(artifacts_dir_raw) if artifacts_dir_raw else None
    if artifacts_dir and (not artifacts_dir.exists()):
        artifacts_dir = None
    if not xlsx and not artifacts_dir:
        return {
            "status": "run_error",
            "window": window_weeks,
            "command": str(base_result.get("command", "")),
            "stdout_log": str(base_result.get("stdout_log", "")),
            "stderr_log": str(base_result.get("stderr_log", "")),
            "errors": [f"No existen artefactos base (xlsx/csv) para derivar ventana {window_weeks}"],
        }
    metrics = extract_metrics_from_artifacts(
        repo=repo,
        python_exe=python_exe,
        xlsx_path=xlsx,
        artifacts_dir=artifacts_dir,
        weekly_csv=weekly_csv,
        tie_low=tie_low,
        tie_high=tie_high,
        max_regime_weeks=int(window_weeks),
    )
    actual_weeks_run = to_float((metrics or {}).get("weeks_run"))
    actual_weeks_int: Optional[int] = None
    if actual_weeks_run is not None:
        actual_weeks_int = int(round(actual_weeks_run))
    trades_val = to_float((metrics or {}).get("trades"))
    weeks_traded_val = to_float((metrics or {}).get("weeks_traded"))
    depth_ok = True
    errors: List[str] = []
    reason = ""
    short_no_trades = False
    if actual_weeks_int is None:
        depth_ok = False
        reason = "missing_weeks_run_metric"
        errors.append(f"{reason}: requested={int(window_weeks)}")
    elif actual_weeks_int < int(window_weeks):
        depth_ok = False
        reason = "insufficient_depth"
        errors.append(f"{reason}: requested={int(window_weeks)} actual_weeks_run={int(actual_weeks_int)}")
    if int(window_weeks) in {4, 8, 24} and trades_val is not None and float(trades_val) <= 0:
        depth_ok = False
        short_no_trades = True
        reason = "insufficient_short_window_activity"
        errors = []
    status = "run_ok" if depth_ok else ("short_window_no_trades" if short_no_trades else "insufficient_depth")
    return {
        "status": status,
        "window": window_weeks,
        "requested_weeks": int(window_weeks),
        "actual_weeks_run": actual_weeks_int,
        "depth_ok": depth_ok,
        "reason": reason,
        "trades": trades_val,
        "weeks_traded": weeks_traded_val,
        "test_start_used": clean_text(base_result.get("test_start_used", "")),
        "derived_from_window": base_result.get("window"),
        "command": str(base_result.get("command", "")),
        "stdout_log": str(base_result.get("stdout_log", "")),
        "stderr_log": str(base_result.get("stderr_log", "")),
        "outputs": outputs,
        "metrics": metrics,
        "errors": errors,
        "execution_mode": "derived_reuse",
    }


def should_early_prune_after_window(window_weeks: int, window_result: Dict[str, Any]) -> Tuple[bool, str]:
    if (window_result or {}).get("status") != "run_ok":
        return True, f"window_{int(window_weeks)} not run_ok"
    if not bool((window_result or {}).get("depth_ok", False)):
        return True, f"window_{int(window_weeks)} insufficient_depth"
    m = (window_result or {}).get("metrics", {}) or {}
    trades = to_float(m.get("trades"))
    weeks_traded = to_float(m.get("weeks_traded"))
    spy_cmp = to_float(m.get("spy_compare"))
    avg_ret = to_float(m.get("avg_net_return_pct"))
    total_pnl = to_float(m.get("total_net_pnl_dollars"))
    if trades is not None and trades <= 0:
        return True, f"window_{int(window_weeks)} trades=0"
    if weeks_traded is not None and weeks_traded <= 0:
        return True, f"window_{int(window_weeks)} weeks_traded=0"
    # Smoke/prueba inicial (4/8): poda agresiva.
    if int(window_weeks) <= 8:
        if (spy_cmp is not None and spy_cmp <= -0.60) and (
            ((avg_ret is not None and avg_ret <= 0) or (total_pnl is not None and total_pnl <= 0))
        ):
            return True, f"window_{int(window_weeks)} smoke_fail_vs_spy"
    # 24 semanas: primer filtro serio de continuidad.
    if int(window_weeks) == 24:
        if (spy_cmp is not None and spy_cmp <= -0.25) and (
            ((avg_ret is not None and avg_ret <= 0) or (total_pnl is not None and total_pnl <= 0))
        ):
            return True, "window_24 fuerte debilidad vs SPY"
    return False, ""


def should_early_prune_after_24w(window_result: Dict[str, Any]) -> Tuple[bool, str]:
    # Compatibilidad con llamadas existentes.
    return should_early_prune_after_window(24, window_result)


def classify_executor_run_status(windows_results: Dict[str, Any], exec_errors: List[str]) -> str:
    statuses = [clean_text((windows_results.get(k, {}) or {}).get("status", "")) for k in windows_results.keys()]
    fatal_statuses = {"run_error", "timeout"}
    nonfatal_statuses = {"insufficient_depth", "short_window_no_trades"}
    if any(s in fatal_statuses for s in statuses):
        return "run_error"
    if any(s in nonfatal_statuses for s in statuses):
        return "run_partial_valid"
    if exec_errors:
        # Si hay errores pero no hubo fatal explícito, tratar como parcial.
        return "run_partial_valid"
    return "run_ok"


def build_validation_depth_summary(
    windows_results: Dict[str, Any],
    requested_windows: List[int],
    progressive_windows: List[int],
) -> Dict[str, Any]:
    requested = [int(w) for w in requested_windows]
    progressive = [int(w) for w in progressive_windows]
    valid_windows: List[int] = []
    for w in progressive:
        payload = windows_results.get(str(w), {}) or {}
        status = clean_text(payload.get("status", ""))
        depth_ok = bool(payload.get("depth_ok", False))
        requested_w = int(to_float(payload.get("requested_weeks")) or w)
        actual_w = to_float(payload.get("actual_weeks_run"))
        if actual_w is not None and actual_w < requested_w:
            depth_ok = False
        if status == "run_ok" and depth_ok:
            valid_windows.append(int(w))

    best_valid_window = max(valid_windows) if valid_windows else None
    p156 = windows_results.get("156", {}) or {}
    s156 = clean_text(p156.get("status", ""))
    d156 = bool(p156.get("depth_ok", False))
    req156 = int(to_float(p156.get("requested_weeks")) or 156)
    act156 = to_float(p156.get("actual_weeks_run"))
    multi_year_real = False
    if p156:
        if s156 == "run_ok" and d156 and act156 is not None and int(round(act156)) >= req156 and req156 >= 156:
            multi_year_real = True

    notes: List[str] = []
    if 156 in requested and p156 and not multi_year_real:
        if s156 == "insufficient_depth":
            notes.append("window_156_insufficient_depth_non_fatal")
        elif s156 and s156 != "run_ok":
            notes.append(f"window_156_status={s156}")
        else:
            notes.append("window_156_not_real_depth")
    if best_valid_window == 52 and 156 in requested and not multi_year_real:
        notes.append("preserve_52w_evidence")

    return {
        "best_valid_window": best_valid_window,
        "requested_windows": requested,
        "progressive_plan": progressive,
        "multi_year_real": multi_year_real,
        "notes": "; ".join(notes),
    }


def get_metric_from_window(executor_output: Dict[str, Any], window: int, key: str) -> Any:
    w = executor_output.get("windows", {}).get(str(window), {})
    m = w.get("metrics", {})
    return m.get(key)


def compare_window_metrics(curr: Dict[str, Any], ref: Dict[str, Any]) -> Dict[str, Any]:
    keys = ["weeks_traded", "trades", "wins", "losses", "ties", "avg_net_return_pct", "total_net_pnl_dollars", "spy_compare"]
    out: Dict[str, Any] = {}
    for k in keys:
        cv = curr.get(k)
        rv = ref.get(k)
        out[k] = {"current": cv, "reference": rv}
        c = to_float(cv)
        r = to_float(rv)
        if c is not None and r is not None:
            out[k]["delta"] = round(c - r, 6)
    return out


def evaluate_metric_effect(curr: Dict[str, Any], ref: Dict[str, Any], tolerance: float = 1e-9) -> Dict[str, Any]:
    """
    Detecta corridas que cambiaron config/código pero no movieron resultados.

    Regla de gobierno:
    - metric_no_effect vs parent o vs current_baseline NO puede ser baseline.
    - metric_no_effect tampoco puede ser accepted_for_followup ni nuevo parent.
    """
    keys = [
        "weeks_traded",
        "trades",
        "wins",
        "losses",
        "ties",
        "avg_net_return_pct",
        "total_net_pnl_dollars",
        "spy_compare",
    ]
    deltas: Dict[str, Any] = {}
    comparable_keys: List[str] = []
    changed_keys: List[str] = []

    for key in keys:
        c = to_float(curr.get(key)) if isinstance(curr, dict) else None
        r = to_float(ref.get(key)) if isinstance(ref, dict) else None
        deltas[key] = {
            "current": (curr.get(key) if isinstance(curr, dict) else None),
            "reference": (ref.get(key) if isinstance(ref, dict) else None),
            "delta": None,
        }
        if c is None or r is None:
            continue
        comparable_keys.append(key)
        d = float(c) - float(r)
        deltas[key]["current"] = c
        deltas[key]["reference"] = r
        deltas[key]["delta"] = round(d, 10)
        if abs(d) > tolerance:
            changed_keys.append(key)

    metric_no_effect = bool(comparable_keys and not changed_keys)
    return {
        "metric_no_effect": metric_no_effect,
        "comparable_keys": comparable_keys,
        "changed_keys": changed_keys,
        "deltas": deltas,
    }


def material_improvement_signal(curr: Dict[str, Any], ref: Dict[str, Any]) -> Dict[str, Any]:
    """
    Señal simple para decidir si una corrida merece follow-up.
    Evita que una corrida sin mejora real avance como parent técnico.
    """
    cur_spy = to_float((curr or {}).get("spy_compare"))
    ref_spy = to_float((ref or {}).get("spy_compare"))
    cur_avg = to_float((curr or {}).get("avg_net_return_pct"))
    ref_avg = to_float((ref or {}).get("avg_net_return_pct"))
    cur_pnl = to_float((curr or {}).get("total_net_pnl_dollars"))
    ref_pnl = to_float((ref or {}).get("total_net_pnl_dollars"))
    cur_trades = to_float((curr or {}).get("trades"))
    ref_trades = to_float((ref or {}).get("trades"))

    delta_spy = (float(cur_spy) - float(ref_spy)) if cur_spy is not None and ref_spy is not None else None
    delta_avg = (float(cur_avg) - float(ref_avg)) if cur_avg is not None and ref_avg is not None else None
    delta_pnl = (float(cur_pnl) - float(ref_pnl)) if cur_pnl is not None and ref_pnl is not None else None
    delta_trades = (float(cur_trades) - float(ref_trades)) if cur_trades is not None and ref_trades is not None else None

    improves_spy = bool(delta_spy is not None and delta_spy > 0.05)
    improves_avg = bool(delta_avg is not None and delta_avg > 0.05)
    improves_pnl_without_edge_decay = bool(
        delta_pnl is not None
        and delta_pnl > 0.0
        and (delta_spy is None or delta_spy >= -0.05)
        and (delta_avg is None or delta_avg >= -0.05)
    )
    frequency_only = bool(
        delta_trades is not None
        and delta_trades > 0
        and delta_pnl is not None
        and delta_pnl >= 0
        and (delta_spy is not None and delta_spy <= 0)
        and (delta_avg is not None and delta_avg <= 0)
    )

    return {
        "delta_spy_compare": (round(delta_spy, 6) if delta_spy is not None else None),
        "delta_avg_net_return_pct": (round(delta_avg, 6) if delta_avg is not None else None),
        "delta_total_net_pnl_dollars": (round(delta_pnl, 6) if delta_pnl is not None else None),
        "delta_trades": (round(delta_trades, 6) if delta_trades is not None else None),
        "improves_spy": improves_spy,
        "improves_avg": improves_avg,
        "improves_pnl_without_edge_decay": improves_pnl_without_edge_decay,
        "frequency_only": frequency_only,
        "has_material_improvement": bool((improves_spy or improves_avg or improves_pnl_without_edge_decay) and not frequency_only),
    }


def evaluate_multi_year_vs_spy(
    window_metrics: Dict[str, Any],
    min_years_vs_spy: int,
    max_nonpositive_years_vs_spy: int,
) -> Dict[str, Any]:
    yearly_raw = window_metrics.get("spy_yearly_breakdown") or []
    parsed: List[Dict[str, Any]] = []
    for r in yearly_raw:
        if not isinstance(r, dict):
            continue
        y = r.get("year")
        d = to_float(r.get("diff_pct"))
        if d is None:
            continue
        try:
            yi = int(y)
        except Exception:
            continue
        parsed.append({"year": yi, "diff_pct": d})
    parsed = sorted(parsed, key=lambda x: x["year"])
    positives = [x for x in parsed if x["diff_pct"] > 0]
    nonpositive = [x for x in parsed if x["diff_pct"] <= 0]
    details = "; ".join([f"{x['year']}:{x['diff_pct']:.4f}" for x in parsed]) if parsed else ""

    if len(parsed) < min_years_vs_spy:
        return {
            "pass": False,
            "years_evaluated": len(parsed),
            "positive_years": len(positives),
            "nonpositive_years": len(nonpositive),
            "details": details,
            "reason": f"Evidencia multi-anio insuficiente: {len(parsed)} anios (minimo {min_years_vs_spy}).",
        }

    if len(nonpositive) > max_nonpositive_years_vs_spy:
        return {
            "pass": False,
            "years_evaluated": len(parsed),
            "positive_years": len(positives),
            "nonpositive_years": len(nonpositive),
            "details": details,
            "reason": (
                f"No supera SPY en anios suficientes: {len(nonpositive)} anios no positivos "
                f"(maximo permitido {max_nonpositive_years_vs_spy})."
            ),
        }

    return {
        "pass": True,
        "years_evaluated": len(parsed),
        "positive_years": len(positives),
        "nonpositive_years": len(nonpositive),
        "details": details,
        "reason": "Valida multi-anio vs SPY.",
    }


def _extract_yearly_diff_list(window_metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    yearly_raw = window_metrics.get("spy_yearly_breakdown") or []
    out: List[Dict[str, Any]] = []
    for r in yearly_raw:
        if not isinstance(r, dict):
            continue
        y = r.get("year")
        d = to_float(r.get("diff_pct"))
        if d is None:
            continue
        try:
            yi = int(y)
        except Exception:
            continue
        out.append({"year": yi, "diff_pct": d})
    return sorted(out, key=lambda x: x["year"])


def evaluate_promotion_vs_parent(
    parent_metrics: Dict[str, Any],
    current_metrics: Dict[str, Any],
    validation_phase: str,
) -> Dict[str, Any]:
    blockers: List[str] = []
    warnings: List[str] = []
    details: Dict[str, Any] = {}

    if not parent_metrics:
        blockers.append("No hay metricas del parent para validar promoción.")
        return {
            "promote": False,
            "promotion_reason": "Sin comparación contra parent no se promueve baseline.",
            "promotion_blockers": blockers,
            "promotion_warnings": warnings,
            "details": details,
        }

    cur_avg = to_float(current_metrics.get("avg_net_return_pct"))
    par_avg = to_float(parent_metrics.get("avg_net_return_pct"))
    cur_spy = to_float(current_metrics.get("spy_compare"))
    par_spy = to_float(parent_metrics.get("spy_compare"))
    cur_trades = to_float(current_metrics.get("trades"))
    par_trades = to_float(parent_metrics.get("trades"))
    cur_weeks = to_float(current_metrics.get("weeks_traded"))
    par_weeks = to_float(parent_metrics.get("weeks_traded"))

    details["avg_net_return_pct_52"] = {"current": cur_avg, "parent": par_avg}
    details["spy_compare_52"] = {"current": cur_spy, "parent": par_spy}
    details["trades_52"] = {"current": cur_trades, "parent": par_trades}
    details["weeks_traded_52"] = {"current": cur_weeks, "parent": par_weeks}

    if None not in (cur_avg, par_avg, cur_spy, par_spy):
        if float(cur_avg) < float(par_avg) and float(cur_spy) < float(par_spy):
            blockers.append("Empeora edge en 52w vs parent (avg_net_return_pct y spy_compare).")
        elif float(cur_avg) < float(par_avg):
            warnings.append("avg_net_return_pct_52 empeora vs parent.")
        elif float(cur_spy) < float(par_spy):
            warnings.append("spy_compare_52 empeora vs parent.")

    if None not in (cur_trades, par_trades, cur_avg, par_avg, cur_spy, par_spy):
        if float(cur_trades) > float(par_trades) and float(cur_avg) < float(par_avg) and float(cur_spy) < float(par_spy):
            blockers.append("Sube frecuencia/trades pero deteriora edge contra parent.")

    cur_yearly = _extract_yearly_diff_list(current_metrics)
    par_yearly = _extract_yearly_diff_list(parent_metrics)
    cur_nonpos = [x for x in cur_yearly if x["diff_pct"] <= 0]
    par_nonpos = [x for x in par_yearly if x["diff_pct"] <= 0]
    details["yearly_vs_spy_current"] = cur_yearly
    details["yearly_vs_spy_parent"] = par_yearly

    if cur_nonpos:
        warnings.append("Hay al menos un año no positivo vs SPY en el run actual.")
        blockers.append("No promueve baseline con años no positivos vs SPY en esta fase.")
    if len(cur_nonpos) > len(par_nonpos):
        blockers.append("Deteriora el breakdown anual vs SPY contra parent.")

    promote = len(blockers) == 0
    if promote:
        reason = "Mejora o mantiene edge vs parent sin deterioro material vs SPY."
    else:
        reason = "Aceptable para seguimiento, pero no robusto para promoción de baseline."

    return {
        "promote": promote,
        "promotion_reason": reason,
        "promotion_blockers": blockers,
        "promotion_warnings": warnings,
        "details": details,
        "validation_phase": validation_phase,
    }


def evaluate_parent_depth_guard_52w(current_metrics: Dict[str, Any]) -> Dict[str, Any]:
    w52_weeks_traded = to_float(current_metrics.get("weeks_traded"))
    w52_trades = to_float(current_metrics.get("trades"))
    excluded_ratio = None
    if w52_weeks_traded is not None and float(w52_weeks_traded) >= 0:
        excluded_ratio = max(0.0, 1.0 - (float(w52_weeks_traded) / 52.0))

    weeks_ok = w52_weeks_traded is not None and float(w52_weeks_traded) >= 20.0
    trades_ok = w52_trades is not None and float(w52_trades) >= 15.0
    excluded_ok = excluded_ratio is not None and float(excluded_ratio) <= 0.50
    passed = bool(weeks_ok and trades_ok and excluded_ok)

    blockers: List[str] = []
    if not weeks_ok:
        blockers.append("w52_weeks_traded_below_parent_minimum")
    if not trades_ok:
        blockers.append("w52_trades_below_parent_minimum")
    if not excluded_ok:
        blockers.append("w52_excluded_ratio_above_parent_maximum")

    return {
        "pass": passed,
        "reason": "" if passed else "low_depth_52w_not_allowed_as_parent",
        "weeks_traded": w52_weeks_traded,
        "trades": w52_trades,
        "excluded_ratio": (round(float(excluded_ratio), 6) if excluded_ratio is not None else None),
        "min_weeks_traded": 20.0,
        "min_trades": 15.0,
        "max_excluded_ratio": 0.50,
        "blockers": blockers,
    }


def decide_acceptance(
    executor_output: Dict[str, Any],
    last_valid_ctx: Optional[Dict[str, Any]],
    baseline_ref_metrics: Dict[str, Any],
    validation_phase: str,
    year_validation_window_weeks: int,
    min_years_vs_spy: int,
    max_nonpositive_years_vs_spy: int,
) -> Tuple[str, List[str], Dict[str, Any]]:
    executor_status = clean_text(executor_output.get("status", ""))
    if executor_status not in {"run_ok", "run_partial_valid"}:
        return "rejected", ["Executor no finalizo OK."], {}

    reasons: List[str] = []
    compare: Dict[str, Any] = {"executor_status": executor_status}
    compare["champion_for_followup"] = False
    if executor_status == "run_partial_valid":
        compare["partial_validation_note"] = "Corrida usable con validacion parcial."
    curr_w24, meta_w24 = get_window_metrics_if_valid_depth(executor_output, 24)
    curr_w52, meta_w52 = get_window_metrics_if_valid_depth(executor_output, 52)
    compare["window_depth_validation"] = {"24": meta_w24, "52": meta_w52}
    parent_depth_guard = evaluate_parent_depth_guard_52w(curr_w52 or {})
    compare["parent_depth_guard_52w"] = parent_depth_guard
    if not bool(parent_depth_guard.get("pass", False)):
        compare["do_not_use_as_parent"] = True
        compare["branch_anchor_allowed"] = False
        compare["parent_depth_guard_reason"] = clean_text(parent_depth_guard.get("reason", "low_depth_52w_not_allowed_as_parent"))
    depth_limited_rule = evaluate_depth_limited_followup_rule(
        executor_output=executor_output,
        year_validation_window_weeks=year_validation_window_weeks,
    )
    compare["global_state_rule"] = depth_limited_rule

    if not curr_w24 or not curr_w52:
        reasons.append("Faltan ventanas 24/52 validas y con profundidad real para validar robustez.")
        return "rejected", reasons, compare

    w52_traded = to_float(curr_w52.get("weeks_traded")) or 0.0
    w52_spy = to_float(curr_w52.get("spy_compare")) or -999.0
    w24_spy = to_float(curr_w24.get("spy_compare")) or -999.0

    phase = (validation_phase or "year1").strip().lower()
    if phase not in {"year1", "multi_year"}:
        phase = "year1"
    compare["validation_phase"] = phase

    if w52_traded < 20:
        reasons.append("Muy baja frecuencia en 52 semanas.")
    if w52_spy <= 0:
        reasons.append("No supera SPY en 52 semanas.")
    if phase == "multi_year" and w24_spy <= 0:
        reasons.append("No supera SPY en 24 semanas.")

    year_key = str(year_validation_window_weeks)
    year_metrics, meta_year = get_window_metrics_if_valid_depth(executor_output, year_validation_window_weeks)
    compare["window_depth_validation"][year_key] = meta_year
    promotion_only_blockers: List[str] = []
    if not year_metrics:
        compare["multi_year_validation"] = {
            "pass": False,
            "reason": "missing_or_insufficient_depth_window",
            "window_weeks": year_validation_window_weeks,
            "actual_weeks_run": meta_year.get("actual_weeks_run"),
        }
        if phase == "multi_year":
            promotion_only_blockers.append(
                f"Falta ventana valida multi-anio ({year_validation_window_weeks} semanas reales). "
                f"actual={meta_year.get('actual_weeks_run')}"
            )
    else:
        multi_year = evaluate_multi_year_vs_spy(
            window_metrics=year_metrics,
            min_years_vs_spy=min_years_vs_spy,
            max_nonpositive_years_vs_spy=max_nonpositive_years_vs_spy,
        )
        multi_year["window_weeks"] = year_validation_window_weeks
        compare["multi_year_validation"] = multi_year
        if phase == "multi_year" and not bool(multi_year.get("pass", False)):
            promotion_only_blockers.append(str(multi_year.get("reason", "No valida multi-anio vs SPY.")))
    if not bool(meta_year.get("depth_ok", False)):
        compare["year_window_depth_warning"] = (
            f"window={year_validation_window_weeks} depth insuficiente "
            f"(actual={meta_year.get('actual_weeks_run')})"
        )
    if phase == "year1" and w24_spy <= 0:
        compare["w24_spy_warning"] = "No supera SPY en 24 semanas (no bloquea fase year1)."

    long_window_required_for_promotion = int(year_validation_window_weeks) >= 156
    long_window_depth_ok = bool(meta_year.get("depth_ok", False)) and bool(year_metrics)
    compare["long_window_required_for_promotion"] = long_window_required_for_promotion
    compare["long_window_depth_ok"] = long_window_depth_ok
    if promotion_only_blockers:
        compare["promotion_only_blockers"] = promotion_only_blockers

    last_valid_metrics = {}
    parent_no_effect = False
    baseline_no_effect = False
    followup_quality_blocks: List[str] = []
    parent_material_signal: Dict[str, Any] = {}
    baseline_material_signal: Dict[str, Any] = {}

    if last_valid_ctx:
        last_valid_metrics = (last_valid_ctx.get("executor_output") or {}).get("windows", {})
    if last_valid_metrics:
        lw52 = (last_valid_metrics.get("52") or {}).get("metrics", {})
        compare["vs_last_valid_w52"] = compare_window_metrics(curr_w52, lw52)
        parent_effect = evaluate_metric_effect(curr_w52, lw52)
        parent_material_signal = material_improvement_signal(curr_w52, lw52)
        compare["effective_change_vs_parent_w52"] = parent_effect
        compare["material_improvement_vs_parent_w52"] = parent_material_signal
        parent_no_effect = bool(parent_effect.get("metric_no_effect", False))
        if parent_no_effect:
            followup_quality_blocks.append("metric_no_effect_vs_parent: no cambia métricas 52w vs parent; no aceptar follow-up ni usar como parent.")
        cur_pnl = to_float(curr_w52.get("total_net_pnl_dollars"))
        prev_pnl = to_float(lw52.get("total_net_pnl_dollars"))
        if cur_pnl is not None and prev_pnl is not None and cur_pnl < prev_pnl and w52_spy <= (to_float(lw52.get("spy_compare")) or -999):
            reasons.append("Empeora contra ultima corrida valida en PnL y spy_compare (52w).")

    if baseline_ref_metrics:
        bw52 = baseline_ref_metrics.get("52", {})
        compare["vs_baseline_w52"] = compare_window_metrics(curr_w52, bw52)
        baseline_effect = evaluate_metric_effect(curr_w52, bw52)
        baseline_material_signal = material_improvement_signal(curr_w52, bw52)
        compare["effective_change_vs_current_baseline_w52"] = baseline_effect
        compare["material_improvement_vs_current_baseline_w52"] = baseline_material_signal
        baseline_no_effect = bool(baseline_effect.get("metric_no_effect", False))
        if baseline_no_effect:
            followup_quality_blocks.append("metric_no_effect_vs_current_baseline: no cambia métricas 52w vs baseline activo; no aceptar follow-up ni parent.")
        base_spy = to_float(bw52.get("spy_compare"))
        base_avg = to_float(bw52.get("avg_net_return_pct"))
        if base_spy is not None and w52_spy <= float(base_spy):
            followup_quality_blocks.append("spy_compare_52 no mejora vs current_baseline real.")
        cur_avg_for_base = to_float(curr_w52.get("avg_net_return_pct"))
        if cur_avg_for_base is not None and base_avg is not None and cur_avg_for_base < float(base_avg):
            followup_quality_blocks.append("avg_net_return_pct_52 empeora vs current_baseline real.")
        if bool(baseline_material_signal.get("frequency_only", False)):
            followup_quality_blocks.append("frequency_only_vs_current_baseline: más actividad/PnL sin mejorar edge/SPY; no usar como parent.")
        byw = baseline_ref_metrics.get(year_key, {})
        if byw:
            compare[f"vs_baseline_w{year_validation_window_weeks}"] = compare_window_metrics(year_metrics, byw)

    if parent_no_effect or baseline_no_effect:
        compare["decision_type"] = "rejected"
        compare["promotion_reason"] = "metric_no_effect: corrida sin efecto material; no se acepta follow-up."
        compare["promotion_blockers"] = list(dict.fromkeys(followup_quality_blocks))
        compare["do_not_use_as_parent"] = True
        compare["branch_anchor_allowed"] = False
        return "rejected", list(dict.fromkeys(followup_quality_blocks)), compare

    last_valid_w52_spy = None
    if last_valid_metrics:
        lw52_local = (last_valid_metrics.get("52") or {}).get("metrics", {})
        last_valid_w52_spy = to_float(lw52_local.get("spy_compare"))
    delta_w52_vs_last = (
        (float(w52_spy) - float(last_valid_w52_spy))
        if (last_valid_w52_spy is not None and math.isfinite(float(last_valid_w52_spy)))
        else None
    )
    strong_w52_signal = bool(
        float(w52_spy) >= 2.0
        or (delta_w52_vs_last is not None and float(delta_w52_vs_last) >= 0.5)
    )
    compare["strong_w52_signal"] = strong_w52_signal
    compare["delta_w52_spy_vs_last_valid"] = (round(float(delta_w52_vs_last), 6) if delta_w52_vs_last is not None else None)
    long_depth_limited = bool(long_window_required_for_promotion and (not long_window_depth_ok))
    compare["long_depth_limited"] = long_depth_limited

    if reasons and long_depth_limited and strong_w52_signal:
        softened: List[str] = []
        hard: List[str] = []
        for r in reasons:
            rtxt = clean_text(r)
            low = rtxt.lower()
            if (
                "no supera spy en 24 semanas" in low
                or "empeora contra ultima corrida valida" in low
                or "muy baja frecuencia en 52 semanas" in low
            ):
                softened.append(rtxt)
            else:
                hard.append(rtxt)
        if softened and not hard:
            compare["strong_52_depth_limited_override"] = {
                "applied": True,
                "softened_reasons": softened,
            }
            promotion_only_blockers.extend(softened)
            reasons = []

    if reasons:
        compare["decision_type"] = "rejected"
        compare["promotion_reason"] = ""
        compare["promotion_blockers"] = reasons
        return "rejected", reasons, compare

    if promotion_only_blockers:
        compare["decision_type"] = "accepted_for_followup"
        compare["promotion_reason"] = "Corrida util para seguimiento; pendiente validacion larga robusta."
        compare["promotion_blockers"] = promotion_only_blockers
        if long_depth_limited and strong_w52_signal:
            compare["champion_for_followup"] = True
        if not bool(parent_depth_guard.get("pass", False)):
            compare["promotion_reason"] = "Corrida util para seguimiento, pero no elegible como parent fuerte por baja profundidad 52w."
            compare["promotion_blockers"] = list(
                dict.fromkeys(
                    (compare.get("promotion_blockers") or [])
                    + [clean_text(parent_depth_guard.get("reason", "low_depth_52w_not_allowed_as_parent"))]
                )
            )
        return "accepted_for_followup", ["Aceptado para seguimiento."] + promotion_only_blockers, compare

    parent_metrics = {}
    if last_valid_ctx:
        parent_metrics = ((last_valid_ctx.get("executor_output") or {}).get("windows", {}).get("52", {}) or {}).get("metrics", {}) or {}
    promotion_eval = evaluate_promotion_vs_parent(
        parent_metrics=parent_metrics,
        current_metrics=curr_w52,
        validation_phase=phase,
    )
    compare["promotion_evaluation"] = promotion_eval
    compare["promotion_reason"] = promotion_eval.get("promotion_reason", "")
    compare["promotion_blockers"] = promotion_eval.get("promotion_blockers", [])
    compare["promotion_warnings"] = promotion_eval.get("promotion_warnings", [])

    if long_window_required_for_promotion and not long_window_depth_ok:
        reason_long = (
            f"No se promueve baseline sin validar profundidad real de {year_validation_window_weeks} semanas "
            f"(actual={meta_year.get('actual_weeks_run')})."
        )
        followup_reasons = ["Aceptado para seguimiento, pendiente validación de ventana larga real.", reason_long]
        if bool(depth_limited_rule.get("applies", False)):
            followup_reasons.append(
                "Regla global aplicada: 4/8/24/52 validas + 156 insufficient_depth => parent util y sin reinicio de cola inicial."
            )
        compare["decision_type"] = "accepted_for_followup"
        compare["promotion_reason"] = (
            "Pendiente validación robusta en ventana larga real. "
            "No se reinicia initial_test_queue; corrida utilizable como parent."
        )
        compare["promotion_blockers"] = list(dict.fromkeys((compare.get("promotion_blockers") or []) + [reason_long]))
        if strong_w52_signal:
            compare["champion_for_followup"] = True
            followup_reasons.append("Marcada como champion_for_followup por señal fuerte en 52w con profundidad larga insuficiente.")
        if not bool(parent_depth_guard.get("pass", False)):
            compare["promotion_reason"] = "Pendiente validacion robusta en ventana larga real, pero no elegible como parent fuerte por baja profundidad 52w."
            compare["promotion_blockers"] = list(
                dict.fromkeys(
                    (compare.get("promotion_blockers") or [])
                    + [clean_text(parent_depth_guard.get("reason", "low_depth_52w_not_allowed_as_parent"))]
                )
            )
        return "accepted_for_followup", followup_reasons, compare

    if followup_quality_blocks:
        merged_promotion_blockers = list(dict.fromkeys((compare.get("promotion_blockers") or []) + followup_quality_blocks))
        compare["promotion_blockers"] = merged_promotion_blockers
        if isinstance(compare.get("promotion_evaluation"), dict):
            compare["promotion_evaluation"]["promote"] = False
            compare["promotion_evaluation"]["promotion_blockers"] = merged_promotion_blockers
            compare["promotion_evaluation"]["promotion_reason"] = "Bloqueada por comparación contra current_baseline/parent."

    if bool(promotion_eval.get("promote", False)) and not followup_quality_blocks:
        compare["decision_type"] = "promoted_to_baseline"
        if phase == "year1":
            return (
                "promoted_to_baseline",
                ["Cumple fase year1 y valida promoción vs parent."],
                compare,
            )
        return (
            "promoted_to_baseline",
            ["Cumple fase multi_year y valida promoción robusta vs parent."],
            compare,
        )

    # Si no promueve baseline, solo puede quedar como follow-up si trae mejora material real.
    # Esto evita que metric_no_effect o cambios de frecuencia sin edge avancen como parent.
    parent_followup_ok = bool(parent_material_signal.get("has_material_improvement", False)) if isinstance(parent_material_signal, dict) else False
    baseline_followup_ok = True
    if baseline_ref_metrics:
        baseline_followup_ok = bool(baseline_material_signal.get("has_material_improvement", False)) if isinstance(baseline_material_signal, dict) else False

    if followup_quality_blocks or not parent_followup_ok or not baseline_followup_ok:
        reject_reasons = [
            "No se acepta follow-up: la corrida no aporta mejora material suficiente para ser nuevo parent."
        ]
        reject_reasons.extend([clean_text(x) for x in followup_quality_blocks if clean_text(x)])
        reject_reasons.extend([clean_text(x) for x in (promotion_eval.get("promotion_blockers") or []) if clean_text(x)])
        if not parent_followup_ok:
            reject_reasons.append("Sin mejora material vs parent en 52w.")
        if baseline_ref_metrics and not baseline_followup_ok:
            reject_reasons.append("Sin mejora material vs current_baseline real en 52w.")
        reject_reasons = list(dict.fromkeys([x for x in reject_reasons if clean_text(x)]))
        compare["decision_type"] = "rejected"
        compare["promotion_reason"] = "Rechazada como follow-up por falta de mejora material."
        compare["promotion_blockers"] = reject_reasons
        compare["do_not_use_as_parent"] = True
        compare["branch_anchor_allowed"] = False
        return "rejected", reject_reasons, compare

    followup_reasons = ["Aceptado para seguimiento, pero sin promoción de baseline."]
    followup_reasons.extend([clean_text(x) for x in (promotion_eval.get("promotion_blockers") or []) if clean_text(x)])
    compare["decision_type"] = "accepted_for_followup"
    compare["branch_anchor_allowed"] = True
    return "accepted_for_followup", followup_reasons, compare


def build_learning_feedback(
    proposal: Dict[str, Any],
    decision_type: str,
    compare_obj: Dict[str, Any],
    executor_output: Dict[str, Any],
) -> Dict[str, Any]:
    hypothesis = clean_text(proposal.get("hypothesis", ""))
    discarded: List[str] = []
    worsened: List[str] = []
    next_change_types: List[str] = []
    notes: List[str] = []

    vs_last = compare_obj.get("vs_last_valid_w52", {}) or {}
    for metric_key, dim in [
        ("weeks_traded", "frequency"),
        ("avg_net_return_pct", "edge"),
        ("spy_compare", "relation_with_spy"),
        ("total_net_pnl_dollars", "total_pnl"),
    ]:
        delta = to_float(((vs_last.get(metric_key) or {}).get("delta")))
        if delta is not None and delta < 0:
            worsened.append(dim)

    multi_year = compare_obj.get("multi_year_validation", {}) or {}
    if multi_year and not bool(multi_year.get("pass", True)):
        worsened.append("year_breakdown")
        notes.append(clean_text(multi_year.get("reason", "")))

    if decision_type == "rejected" and hypothesis:
        discarded.append(hypothesis)
    elif decision_type == "accepted_for_followup" and hypothesis:
        notes.append("Hipótesis informativa, pero aún no robusta para baseline.")

    fallback_diag = proposal.get("fallback_diagnosis", {}) or {}
    behavior_diag = fallback_diag.get("behavioral_diagnostics", {}) if isinstance(fallback_diag, dict) else {}
    rank_rapid = bool(((behavior_diag.get("rank_degradation") or {}).get("rapid_degradation", False))) if isinstance(behavior_diag, dict) else False
    close_filter_enabled = normalize_scalar((proposal.get("proposal_config") or {}).get("ENABLE_CLOSE_VS_SMA50_FILTER")) == "true"

    if "edge" in worsened or "relation_with_spy" in worsened:
        next_change_types.append("tightening")
    if "frequency" in worsened:
        next_change_types.append("controlled_reopening")
    if rank_rapid:
        next_change_types.append("rank_adjustment")
    if not close_filter_enabled:
        next_change_types.append("gate_reactivation")
    if "year_breakdown" in worsened:
        next_change_types.append("adjust_similar_weeks_window")

    if not next_change_types:
        next_change_types = ["controlled_exploration"]

    meta_feedback_for_analyst: List[str] = []
    if "year_breakdown" in worsened:
        meta_feedback_for_analyst.append("Priorizar cambios que reduzcan años no positivos vs SPY en 156 semanas.")
    if "frequency" in worsened and "edge" not in worsened:
        meta_feedback_for_analyst.append("Evitar sobre-filtrado: recuperar frecuencia sin degradar compare vs SPY.")
    if "edge" in worsened or "relation_with_spy" in worsened:
        meta_feedback_for_analyst.append("Priorizar calidad del basket/candidato antes de ampliar frecuencia.")
    if decision_type == "rejected":
        meta_feedback_for_analyst.append("Evitar repetir el mismo cambio sin hipótesis causal adicional.")
    if decision_type == "accepted_for_followup":
        meta_feedback_for_analyst.append("Usar esta corrida como parent útil y escalar validación de forma monotónica.")

    return {
        "hypothesis_discarded": list(dict.fromkeys([x for x in discarded if x])),
        "worsened_dimensions": list(dict.fromkeys([x for x in worsened if x])),
        "next_change_type_recommendation": list(dict.fromkeys([x for x in next_change_types if x])),
        "notes": list(dict.fromkeys([x for x in notes if x])),
        "meta_feedback_for_analyst": list(dict.fromkeys([x for x in meta_feedback_for_analyst if x])),
    }


def _clamp_score(v: float) -> float:
    return max(0.0, min(100.0, float(v)))


def _map_change_dirs(next_change_types: List[str], compare_obj: Dict[str, Any], coordinator_status: str) -> List[str]:
    mapped: List[str] = []
    mapper = {
        "tightening": "tighten_individual_candidate_filters",
        "controlled_reopening": "recalibrate_weekly_gate",
        "rank_adjustment": "reduce_top_candidates",
        "gate_reactivation": "reactivate_disabled_gate",
        "adjust_similar_weeks_window": "recalibrate_weekly_gate",
        "controlled_exploration": "open_controlled_exploration_on_profile_mode",
    }
    for x in next_change_types or []:
        k = clean_text(x)
        if k in mapper:
            mapped.append(mapper[k])

    my = compare_obj.get("multi_year_validation", {}) if isinstance(compare_obj, dict) else {}
    if clean_text(str(my.get("reason", ""))).startswith("missing_or_insufficient_depth_window"):
        mapped.append("fix_long_window_handling")
    if coordinator_status in {"blocked_duplicate", "blocked_zigzag", "blocked_branch_anchor"}:
        mapped.append("improve_parent_state_persistence")
    if coordinator_status == "blocked_no_material_candidate":
        mapped.append("stop_branch_no_learning")
    out = list(dict.fromkeys([m for m in mapped if m]))
    return out[:3]


def _map_recommended_branch_mode(recommended_next_action: str) -> str:
    action = clean_text(recommended_next_action)
    if action == "fix_process_before_more_research":
        return "fix_process_before_more_research"
    if action == "extend_validation":
        return "extend_validation"
    if action in {"controlled_exploration", "stop_branch"}:
        return "controlled_exploration"
    return "refine_current_branch"


def evaluate_research_mode_transition(
    repo: Path,
    rows: List[Dict[str, str]],
    previous_branch_state: Dict[str, Any],
    decision_type: str,
    compare_obj: Dict[str, Any],
    auditor_eval: Dict[str, Any],
) -> Dict[str, Any]:
    prev_mode = normalize_research_mode(
        previous_branch_state.get("current_mode", ""),
        fallback=map_recommended_action_to_mode(previous_branch_state.get("recommended_next_action", "")),
    )
    branch_health = clean_text(auditor_eval.get("branch_health", previous_branch_state.get("branch_health", "")))
    main_friction = clean_text(auditor_eval.get("main_friction", previous_branch_state.get("main_friction", "")))
    recommended_next_action = clean_text(
        auditor_eval.get("recommended_next_action", previous_branch_state.get("recommended_next_action", ""))
    )

    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    last5 = sorted_rows[-5:] if sorted_rows else []
    accepted_recent = any(clean_text(r.get("accepted_or_rejected", "")).lower() == "accepted" for r in last5)
    acceptance_rate_15 = recent_acceptance_rate(sorted_rows, lookback=15)
    useful_recent_count = count_recent_useful_runs(sorted_rows, lookback=10)
    no_useful_recent_streak = bool(len(sorted_rows) >= 8 and useful_recent_count == 0)
    exhausted_recent_count = count_recent_exhausted_subspaces(sorted_rows, lookback=15)
    parent_obvious_exhaustion = estimate_parent_obvious_exhaustion(sorted_rows, lookback=12)
    admin_statuses = {
        "blocked_duplicate",
        "blocked_zigzag",
        "blocked_preflight",
        "blocked_branch_anchor",
        "blocked_no_material_candidate",
    }
    admin_error_recent = count_recent_status(
        sorted_rows,
        statuses=admin_statuses,
        lookback=10,
    )
    admin_error_repeated = count_recent_status(
        sorted_rows,
        statuses=admin_statuses,
        lookback=10,
    ) >= 3
    technical_error_repeated = count_recent_status(
        sorted_rows,
        statuses={"run_error"},
        lookback=10,
    ) >= 2

    watchdog_state = load_watchdog_health_state(repo)
    safe_recovery_trigger = bool(
        watchdog_indicates_safe_recovery(watchdog_state)
        or technical_error_repeated
    )

    friction_process_trigger = bool(
        main_friction in {"coordinator", "state_handling", "duplicate_throttling"}
        or admin_error_repeated
    )

    long_depth_block = bool(
        bool(compare_obj.get("champion_for_followup", False))
        or (
            clean_text(decision_type) == "accepted_for_followup"
            and bool(compare_obj.get("long_window_required_for_promotion", False))
            and (not bool(compare_obj.get("long_window_depth_ok", False)))
        )
    )
    d52 = to_float(
        ((compare_obj.get("vs_last_valid_w52", {}) or {}).get("spy_compare", {}) or {}).get("delta")
    )
    d24 = to_float(
        ((compare_obj.get("vs_last_valid_w24", {}) or {}).get("spy_compare", {}) or {}).get("delta")
    )
    useful_improvement_24_52 = bool(
        (d24 is not None and float(d24) > 0.05)
        or (d52 is not None and float(d52) > 0.10)
    )
    strong_recent_run = bool(d52 is not None and float(d52) >= 0.75)
    if (not strong_recent_run) and sorted_rows:
        for r in reversed(sorted_rows[-8:]):
            if clean_text(r.get("accepted_or_rejected", "")).lower() != "accepted":
                continue
            w52_spy = to_float(r.get("w52_spy_compare"))
            if w52_spy is not None and float(w52_spy) >= 3.0:
                strong_recent_run = True
                break

    mode = prev_mode
    reason = "mode_kept_previous"
    if safe_recovery_trigger:
        mode = "safe_recovery_mode"
        reason = "safe_recovery_trigger_watchdog_or_technical_errors"
    elif friction_process_trigger:
        mode = "fix_process_before_more_research"
        reason = "main_friction_process_or_admin_errors_repeated"
    elif no_useful_recent_streak:
        if admin_error_recent >= 3:
            mode = "fix_process_before_more_research"
            reason = "no_useful_delta_recent_with_admin_blockers"
        else:
            mode = "controlled_exploration"
            reason = "no_useful_delta_recent_switch_to_orthogonal_exploration"
    elif long_depth_block and bool(
        (d52 is None and clean_text(decision_type) == "accepted_for_followup")
        or (d52 is not None and float(d52) > 0.05)
    ):
        mode = "extend_validation"
        reason = "strong_52_signal_but_long_window_depth_not_real"
    elif strong_recent_run and clean_text(decision_type) in {"accepted_for_followup", "promoted_to_baseline"}:
        mode = "champion_hold"
        reason = "strong_recent_run_hold_branch_and_test_orthogonal_small_changes"
    elif (
        acceptance_rate_15 < 0.30
        or branch_health == "stagnating"
        or exhausted_recent_count >= 2
        or parent_obvious_exhaustion
    ):
        mode = "controlled_exploration"
        reason = "low_acceptance_or_stagnation_or_exhausted_subspaces_or_parent_exhausted"
    elif (
        accepted_recent
        and useful_improvement_24_52
        and exhausted_recent_count < 2
        and branch_health in {"alive_and_improving", "alive_but_noisy"}
    ):
        mode = "refine_current_branch"
        reason = "accepted_recent_plus_useful_improvement_and_branch_alive"
    else:
        mapped = map_recommended_action_to_mode(recommended_next_action)
        mode = normalize_research_mode(mapped, fallback=prev_mode)
        reason = f"fallback_to_recommended_next_action:{recommended_next_action or 'none'}"

    mode = normalize_research_mode(mode, fallback=prev_mode)
    return {
        "current_mode": mode,
        "mode_reason": reason,
        "diagnostics": {
            "acceptance_rate_last_15": round(float(acceptance_rate_15), 6),
            "useful_recent_count_last_10": int(useful_recent_count),
            "no_useful_recent_streak": bool(no_useful_recent_streak),
            "branch_health": branch_health,
            "main_friction": main_friction,
            "exhausted_subspaces_recent_count": int(exhausted_recent_count),
            "parent_obvious_exhaustion": bool(parent_obvious_exhaustion),
            "safe_recovery_trigger": bool(safe_recovery_trigger),
            "technical_error_repeated": bool(technical_error_repeated),
            "admin_error_repeated": bool(admin_error_repeated),
            "admin_error_recent_count_last_10": int(admin_error_recent),
            "long_depth_block": bool(long_depth_block),
            "strong_recent_run": bool(strong_recent_run),
            "useful_improvement_24_52": bool(useful_improvement_24_52),
            "d24_vs_last_valid": d24,
            "d52_vs_last_valid": d52,
            "recommended_next_action": recommended_next_action,
        },
    }


def apply_mode_transition_to_branch_state(
    branch_state: Dict[str, Any],
    mode_eval: Dict[str, Any],
    run_id: str,
    now_iso: str,
) -> Dict[str, Any]:
    bs = dict(branch_state or {})
    prev_mode = normalize_research_mode(
        bs.get("current_mode", ""),
        fallback=map_recommended_action_to_mode(bs.get("recommended_next_action", "")),
    )
    next_mode = normalize_research_mode(mode_eval.get("current_mode", prev_mode), fallback=prev_mode)
    reason = clean_text(mode_eval.get("mode_reason", "")) or "mode_evaluation_no_reason"
    stability = int(to_float(bs.get("mode_stability_counter")) or 0)

    if next_mode == prev_mode:
        stability = max(1, stability + 1)
        bs["mode_reason"] = reason
        if not clean_text(bs.get("last_mode_change_at", "")):
            bs["last_mode_change_at"] = now_iso
        if not clean_text(bs.get("last_mode_change_run_id", "")):
            bs["last_mode_change_run_id"] = clean_text(run_id)
    else:
        bs["previous_mode"] = prev_mode
        bs["current_mode"] = next_mode
        bs["mode_reason"] = reason
        bs["last_mode_change_at"] = now_iso
        bs["last_mode_change_run_id"] = clean_text(run_id)
        stability = 1

    bs["current_mode"] = next_mode
    bs["mode_stability_counter"] = max(1, int(stability))
    return bs


def build_branch_governance_block(
    coordinator_output: Dict[str, Any],
    proposal: Dict[str, Any],
    compare_obj: Dict[str, Any],
    auditor_eval: Dict[str, Any],
    current_mode: str = "",
) -> Dict[str, Any]:
    out = coordinator_output or {}
    cmp = compare_obj or {}
    aud = auditor_eval or {}

    anchor_src = out.get("branch_anchor")
    if not isinstance(anchor_src, dict):
        anchor_src = cmp.get("branch_anchor")
    if not isinstance(anchor_src, dict):
        anchor_src = proposal.get("branch_anchor_context")
    if not isinstance(anchor_src, dict):
        anchor_src = {}

    anchor_active = bool(anchor_src.get("active", False))
    anchor_parameter = clean_text(anchor_src.get("parameter", ""))
    anchor_value = anchor_src.get("value")
    anchor_reason = clean_text(anchor_src.get("reason", ""))
    if not anchor_reason and clean_text(out.get("status", "")) == "blocked_branch_anchor":
        anchor_reason = clean_text("; ".join(out.get("reasons", []) or []))
    anchor_hold_iterations = 0
    if anchor_active:
        anchor_hold_iterations = int(
            to_float(anchor_src.get("remaining_iterations"))
            or to_float(anchor_src.get("hold_iterations"))
            or 0
        )

    dup = cmp.get("duplicate_throttling", {}) if isinstance(cmp.get("duplicate_throttling"), dict) else {}
    duplicate_throttle_triggered = bool(dup.get("active", False))
    recent_duplicate_rate = to_float(dup.get("blocked_duplicate_ratio"))

    decision_type = clean_text(out.get("decision_type", ""))
    my = cmp.get("multi_year_validation", {}) if isinstance(cmp.get("multi_year_validation"), dict) else {}
    blockers = [clean_text(x) for x in (cmp.get("promotion_blockers") or []) if clean_text(x)]
    blocker_text = " | ".join(blockers).lower()
    yearly_gap_policy_triggered = bool(
        decision_type == "accepted_for_followup"
        and clean_text(aud.get("recommended_next_action", "")) == "extend_validation"
        and (
            ("año" in blocker_text)
            or ("anual" in blocker_text)
            or ("yearly" in blocker_text)
            or ("multi-anio" in blocker_text)
            or ("multi_year" in blocker_text)
            or clean_text(str(my.get("reason", ""))) == "missing_or_insufficient_depth_window"
        )
    )

    recommended_branch_mode = _map_recommended_branch_mode(clean_text(aud.get("recommended_next_action", "")))

    return {
        "branch_anchor_active": anchor_active,
        "anchor_parameter": anchor_parameter,
        "anchor_value": anchor_value,
        "anchor_reason": anchor_reason,
        "anchor_hold_iterations": anchor_hold_iterations,
        "yearly_gap_policy_triggered": yearly_gap_policy_triggered,
        "duplicate_throttle_triggered": duplicate_throttle_triggered,
        "recent_duplicate_rate": recent_duplicate_rate,
        "current_mode": normalize_research_mode(current_mode or "refine_current_branch"),
        "recommended_branch_mode": recommended_branch_mode,
    }


def build_auditor_v2_evaluation(
    decision_type: str,
    coordinator_status: str,
    proposal: Dict[str, Any],
    executor_output: Dict[str, Any],
    compare_obj: Dict[str, Any],
    learning_feedback: Dict[str, Any],
) -> Dict[str, Any]:
    executor_status = clean_text((executor_output or {}).get("status", ""))
    duplicate_throttling = (
        compare_obj.get("duplicate_throttling", {}) if isinstance(compare_obj, dict) else {}
    ) or {}
    duplicate_throttling_active = bool(duplicate_throttling.get("active", False))
    my = compare_obj.get("multi_year_validation", {}) if isinstance(compare_obj, dict) else {}
    depth_warning = bool(compare_obj.get("year_window_depth_warning")) or (
        isinstance(my, dict) and clean_text(my.get("reason", "")) == "missing_or_insufficient_depth_window"
    )

    process_score = 82.0
    if coordinator_status in {"blocked_preflight", "blocked_no_op", "blocked_duplicate", "blocked_zigzag", "blocked_branch_anchor"}:
        process_score -= 14.0
    if coordinator_status == "blocked_no_material_candidate":
        process_score -= 10.0
    if executor_status == "run_error":
        process_score -= 30.0
    elif executor_status == "run_partial_valid":
        process_score -= 4.0
    if depth_warning:
        process_score -= 3.0
    if duplicate_throttling_active:
        process_score -= 10.0
    if bool(((compare_obj.get("global_state_rule") or {}).get("applies", False))):
        process_score += 2.0
    process_score = _clamp_score(process_score)

    analyst_score = 76.0
    if clean_text(proposal.get("status", "")) == "no_material_candidate_found":
        analyst_score -= 12.0
    if bool((proposal.get("proposal_validation") or {}).get("invalid_no_op", False)):
        analyst_score -= 20.0
    if len(proposal.get("fallback_candidate_pool_considered", []) or []) > 0:
        analyst_score += 5.0
    fd = proposal.get("fallback_diagnosis", {}) or {}
    if isinstance(fd, dict) and bool(fd.get("second_layer_executed", False)):
        analyst_score += 3.0
    analyst_score = _clamp_score(analyst_score)

    coordinator_score = 78.0
    transition_details = compare_obj.get("transition_classification", []) if isinstance(compare_obj, dict) else []
    if not transition_details:
        coordinator_score -= 6.0
    if coordinator_status == "blocked_duplicate":
        coordinator_score += 3.0
    if coordinator_status == "blocked_zigzag":
        coordinator_score += 2.0
    if decision_type in {"accepted_for_followup", "promoted_to_baseline"}:
        coordinator_score += 4.0
    if depth_warning and decision_type == "accepted_for_followup":
        coordinator_score += 2.0
    coordinator_score = _clamp_score(coordinator_score)

    research_score = 70.0
    if decision_type == "promoted_to_baseline":
        research_score += 18.0
    elif decision_type == "accepted_for_followup":
        research_score += 8.0
    else:
        research_score -= 8.0
    vs_last = compare_obj.get("vs_last_valid_w52", {}) if isinstance(compare_obj, dict) else {}
    delta_edge = to_float(((vs_last.get("avg_net_return_pct") or {}).get("delta")))
    delta_spy = to_float(((vs_last.get("spy_compare") or {}).get("delta")))
    if delta_edge is not None:
        research_score += 5.0 if delta_edge > 0 else -4.0
    if delta_spy is not None:
        research_score += 7.0 if delta_spy > 0 else -6.0
    if len((learning_feedback or {}).get("hypothesis_discarded", []) or []) > 0:
        research_score += 2.0
    if coordinator_status == "blocked_no_material_candidate":
        research_score -= 15.0
    research_score = _clamp_score(research_score)

    overall = _clamp_score((process_score + analyst_score + coordinator_score + research_score) / 4.0)

    if research_score >= 80:
        research_value = "high"
        learning_signal = "strong"
    elif research_score >= 65:
        research_value = "medium"
        learning_signal = "medium"
    elif research_score >= 50:
        research_value = "low"
        learning_signal = "weak"
    else:
        research_value = "none"
        learning_signal = "absent"

    main_friction = "none"
    if coordinator_status in {"blocked_preflight", "blocked_no_op", "blocked_duplicate", "blocked_zigzag", "blocked_branch_anchor"}:
        main_friction = "coordinator"
    elif coordinator_status == "blocked_no_material_candidate":
        main_friction = "candidate_generation"
    elif depth_warning:
        main_friction = "long_window_depth"
    if duplicate_throttling_active:
        main_friction = "coordinator"

    if main_friction != "none" and process_score < 70:
        branch_health = "blocked_by_process"
    elif research_score >= 75 and decision_type in {"accepted_for_followup", "promoted_to_baseline"}:
        branch_health = "alive_and_improving"
    elif research_score >= 60:
        branch_health = "alive_but_noisy"
    elif coordinator_status == "blocked_no_material_candidate":
        branch_health = "stagnating"
    else:
        branch_health = "stagnating"

    if branch_health in {"blocked_by_process", "stagnating"} and research_score < 60:
        stagnation_risk = "high"
    elif research_score < 70:
        stagnation_risk = "medium"
    else:
        stagnation_risk = "low"

    promotion_blockers = [clean_text(x) for x in (compare_obj.get("promotion_blockers") or []) if clean_text(x)] if isinstance(compare_obj, dict) else []
    blocker_text = " | ".join(promotion_blockers).lower()
    yearly_or_multi_year_block = (
        ("año" in blocker_text)
        or ("anual" in blocker_text)
        or ("yearly" in blocker_text)
        or ("multi-anio" in blocker_text)
        or ("multi_year" in blocker_text)
        or clean_text(str(my.get("reason", ""))) == "missing_or_insufficient_depth_window"
    )
    vs_last = compare_obj.get("vs_last_valid_w52", {}) if isinstance(compare_obj, dict) else {}
    delta_spy = to_float(((vs_last.get("spy_compare") or {}).get("delta"))
                         )
    clear_w52_signal_vs_spy = bool(delta_spy is not None and delta_spy > 0.05)

    if duplicate_throttling_active:
        recommended_next_action = "fix_process_before_more_research"
        why_this_direction = (
            "Duplicate throttling activo: blocked_duplicate >=20% en últimas corridas, "
            "se prioriza corregir gobernanza del coordinator."
        )
    elif main_friction in {"coordinator", "long_window_depth", "state_handling"} and process_score < 70:
        recommended_next_action = "fix_process_before_more_research"
        why_this_direction = "El principal freno es de proceso y limita aprendizaje útil."
    elif decision_type == "promoted_to_baseline":
        recommended_next_action = "extend_validation"
        why_this_direction = "Hay señal robusta suficiente para extender validación."
    elif decision_type == "accepted_for_followup" and clear_w52_signal_vs_spy and yearly_or_multi_year_block:
        recommended_next_action = "extend_validation"
        why_this_direction = (
            "52w mejora vs SPY pero la promoción quedó bloqueada por yearly_vs_spy/"
            "profundidad multi-year; conviene extender validación sin resetear la rama."
        )
    elif decision_type == "accepted_for_followup":
        recommended_next_action = "refine_current_branch"
        why_this_direction = "La corrida es útil para seguimiento pero no aún baseline."
    elif coordinator_status == "blocked_no_material_candidate":
        recommended_next_action = "controlled_exploration"
        why_this_direction = "La rama actual está agotada y requiere explorar una dirección controlada."
    else:
        recommended_next_action = "controlled_exploration"
        why_this_direction = "No hay evidencia robusta suficiente; conviene exploración acotada."

    recommended_dirs = _map_change_dirs(
        next_change_types=(learning_feedback or {}).get("next_change_type_recommendation", []) or [],
        compare_obj=compare_obj,
        coordinator_status=coordinator_status,
    )
    if duplicate_throttling_active:
        recommended_dirs = list(dict.fromkeys((recommended_dirs or []) + [
            "improve_parent_state_persistence",
            "fix_long_window_handling",
        ]))
    if not recommended_dirs and recommended_next_action == "fix_process_before_more_research":
        recommended_dirs = ["improve_parent_state_persistence", "fix_long_window_handling"]

    return {
        "process_reliability_score": round(process_score, 2),
        "analyst_quality_score": round(analyst_score, 2),
        "coordinator_quality_score": round(coordinator_score, 2),
        "research_effectiveness_score": round(research_score, 2),
        "overall_agent_score": round(overall, 2),
        "research_value": research_value,
        "branch_health": branch_health,
        "learning_signal": learning_signal,
        "stagnation_risk": stagnation_risk,
        "main_friction": main_friction,
        "recommended_next_action": recommended_next_action,
        "recommended_change_directions": recommended_dirs[:3],
        "why_this_direction": why_this_direction,
    }


def finalize_coordinator_output(
    coordinator_output: Dict[str, Any],
    proposal: Optional[Dict[str, Any]] = None,
    executor_output: Optional[Dict[str, Any]] = None,
    compare_obj: Optional[Dict[str, Any]] = None,
    learning_feedback: Optional[Dict[str, Any]] = None,
    current_mode: str = "",
) -> Dict[str, Any]:
    out = dict(coordinator_output or {})
    decision_type = clean_text(out.get("decision_type", ""))
    if decision_type not in {"rejected", "accepted_for_followup", "promoted_to_baseline"}:
        decision_type = "rejected"
    out["decision_type"] = decision_type
    out["accepted_for_followup"] = decision_type == "accepted_for_followup"
    out["promoted_to_baseline"] = decision_type == "promoted_to_baseline"
    lf_default = {
        "hypothesis_discarded": [],
        "worsened_dimensions": [],
        "next_change_type_recommendation": [],
        "meta_feedback_for_analyst": [],
        "notes": [],
    }
    lf = out.get("learning_feedback", None)
    if not isinstance(lf, dict):
        lf = dict(learning_feedback or lf_default)
    for k, v in lf_default.items():
        if k not in lf:
            lf[k] = list(v) if isinstance(v, list) else v
    out["learning_feedback"] = lf
    cmp = compare_obj if isinstance(compare_obj, dict) else (out.get("compare", {}) if isinstance(out.get("compare"), dict) else {})
    cmp = dict(cmp or {})
    if "duplicate_throttling" not in cmp:
        cmp["duplicate_throttling"] = evaluate_duplicate_throttling(
            rows=_AUDIT_RECENT_ROWS,
            current_status=clean_text(out.get("status", "")),
            lookback=15,
        )
    out["compare"] = cmp
    if "auditor_v2_evaluation" not in out:
        out["auditor_v2_evaluation"] = build_auditor_v2_evaluation(
            decision_type=decision_type,
            coordinator_status=clean_text(out.get("status", "")),
            proposal=proposal or {},
            executor_output=executor_output or {},
            compare_obj=(out.get("compare", {}) or {}),
            learning_feedback=(out.get("learning_feedback", {}) or {}),
        )
    mode_src = current_mode or clean_text((proposal or {}).get("research_mode_context", ""))
    out["current_mode"] = normalize_research_mode(
        mode_src,
        fallback=map_recommended_action_to_mode((out.get("auditor_v2_evaluation", {}) or {}).get("recommended_next_action", "")),
    )
    out["branch_governance"] = build_branch_governance_block(
        coordinator_output=out,
        proposal=proposal or {},
        compare_obj=(out.get("compare", {}) or {}),
        auditor_eval=(out.get("auditor_v2_evaluation", {}) or {}),
        current_mode=out.get("current_mode", ""),
    )
    return out


def persist_governance_state(
    baseline_path: Path,
    baseline: Dict[str, Any],
    research_state_path: Path,
    research_state: Dict[str, Any],
    run_id: str,
    decision_type: str,
    coordinator_status: str,
    executor_output: Optional[Dict[str, Any]],
    coordinator_output: Dict[str, Any],
    queue_id: str = "",
    proposal: Optional[Dict[str, Any]] = None,
    recent_rows: Optional[List[Dict[str, str]]] = None,
) -> None:
    now_iso = datetime.now().isoformat(timespec="seconds")
    b_state = baseline.setdefault("state_tracking", {})
    r_state = research_state.setdefault("state_tracking", {})
    exec_status = clean_text((executor_output or {}).get("status", ""))
    p_state = research_state.setdefault("parent_state", {})
    if exec_status in {"run_ok", "run_partial_valid"}:
        b_state["last_successful_executor_run_id"] = run_id
        r_state["last_successful_executor_run_id"] = run_id
    compare_state = (coordinator_output.get("compare", {}) or {}) if isinstance(coordinator_output, dict) else {}
    do_not_use_as_parent = bool(compare_state.get("do_not_use_as_parent", False))
    branch_anchor_allowed = compare_state.get("branch_anchor_allowed")
    if branch_anchor_allowed is None:
        branch_anchor_allowed = not do_not_use_as_parent
    if decision_type in {"accepted_for_followup", "promoted_to_baseline"} and bool(branch_anchor_allowed):
        b_state["last_useful_run_id"] = run_id
        r_state["last_useful_run_id"] = run_id
        p_state["last_useful_run_id"] = run_id
        p_state["current_parent_run_id"] = run_id
        p_state["parent_source"] = "fresh_branch_run"
        p_state["use_baseline_as_parent"] = False
        if decision_type == "accepted_for_followup":
            b_state["last_followup_run_id"] = run_id
            r_state["last_followup_run_id"] = run_id
    elif decision_type in {"accepted_for_followup", "promoted_to_baseline"} and do_not_use_as_parent:
        parent_guard_reason = clean_text(compare_state.get("parent_depth_guard_reason", "")) or "low_depth_52w_not_allowed_as_parent"
        p_state["last_rejected_parent_candidate_run_id"] = run_id
        p_state["last_rejected_parent_candidate_reason"] = parent_guard_reason
        p_state["last_followup_evidence_run_id"] = run_id
        p_state["last_followup_evidence_reason"] = parent_guard_reason
        r_state["last_followup_evidence_run_id"] = run_id
        r_state["last_followup_evidence_reason"] = parent_guard_reason
    if decision_type == "promoted_to_baseline":
        b_state["last_promoted_baseline_run_id"] = run_id
        r_state["last_promoted_baseline_run_id"] = run_id
    if queue_id:
        b_state["last_completed_initial_test_id"] = queue_id
        r_state["last_completed_initial_test_id"] = queue_id
    # Compatibilidad con versiones previas.
    if decision_type == "promoted_to_baseline":
        baseline["last_accepted_run_id"] = run_id

    # Baseline immutability policy: do NOT write baseline during normal runs.
    # Baseline promotion (writing baseline) must be explicit and is handled elsewhere.

    auditor = coordinator_output.get("auditor_v2_evaluation", {}) if isinstance(coordinator_output, dict) else {}
    rs_branch = research_state.setdefault("branch_state", {})
    rs_branch["active_branch_id"] = rs_branch.get("active_branch_id", "main") or "main"
    rs_branch["branch_health"] = maybe_fix_mojibake(auditor.get("branch_health", rs_branch.get("branch_health", "alive_but_noisy")))
    rs_branch["learning_signal"] = maybe_fix_mojibake(auditor.get("learning_signal", rs_branch.get("learning_signal", "medium")))
    rs_branch["stagnation_risk"] = maybe_fix_mojibake(auditor.get("stagnation_risk", rs_branch.get("stagnation_risk", "medium")))
    rs_branch["main_friction"] = maybe_fix_mojibake(auditor.get("main_friction", rs_branch.get("main_friction", "none")))
    rs_branch["recommended_next_action"] = maybe_fix_mojibake(auditor.get("recommended_next_action", rs_branch.get("recommended_next_action", "refine_current_branch")))
    if "current_mode" not in rs_branch:
        rs_branch["current_mode"] = normalize_research_mode(
            rs_branch.get("recommended_next_action", "refine_current_branch")
        )
    if "mode_reason" not in rs_branch:
        rs_branch["mode_reason"] = "mode_not_initialized"
    if "last_mode_change_at" not in rs_branch:
        rs_branch["last_mode_change_at"] = ""
    if "last_mode_change_run_id" not in rs_branch:
        rs_branch["last_mode_change_run_id"] = ""
    if "previous_mode" not in rs_branch:
        rs_branch["previous_mode"] = ""
    if "mode_stability_counter" not in rs_branch:
        rs_branch["mode_stability_counter"] = 0

    mode_eval = evaluate_research_mode_transition(
        repo=research_state_path.parent,
        rows=(recent_rows or []),
        previous_branch_state=rs_branch,
        decision_type=decision_type,
        compare_obj=(coordinator_output.get("compare", {}) if isinstance(coordinator_output, dict) else {}),
        auditor_eval=auditor,
    )
    rs_branch = apply_mode_transition_to_branch_state(
        branch_state=rs_branch,
        mode_eval=mode_eval,
        run_id=run_id,
        now_iso=now_iso,
    )
    coordinator_output["current_mode"] = rs_branch.get("current_mode", "refine_current_branch")
    coordinator_output["mode_reason"] = rs_branch.get("mode_reason", "")
    coordinator_output["mode_diagnostics"] = mode_eval.get("diagnostics", {})
    bg = coordinator_output.get("branch_governance", {}) if isinstance(coordinator_output.get("branch_governance"), dict) else {}
    bg["current_mode"] = rs_branch.get("current_mode", "refine_current_branch")
    coordinator_output["branch_governance"] = bg

    research_state["latest_scores"] = {
        "process_reliability_score": auditor.get("process_reliability_score"),
        "analyst_quality_score": auditor.get("analyst_quality_score"),
        "coordinator_quality_score": auditor.get("coordinator_quality_score"),
        "research_effectiveness_score": auditor.get("research_effectiveness_score"),
        "overall_agent_score": auditor.get("overall_agent_score"),
    }

    lf = coordinator_output.get("learning_feedback", {}) if isinstance(coordinator_output, dict) else {}
    research_state["latest_learning_summary"] = {
        "research_value": maybe_fix_mojibake(auditor.get("research_value", "")),
        "what_was_learned": sanitize_text_list(lf.get("hypothesis_discarded", []) or []),
        "what_is_not_working": sanitize_text_list(lf.get("worsened_dimensions", []) or []),
        "process_warnings": sanitize_text_list(lf.get("notes", []) or []),
        "recommended_change_directions": sanitize_text_list(auditor.get("recommended_change_directions", []) or []),
    }

    memory = research_state.get("branch_memory", [])
    if not isinstance(memory, list):
        memory = []
    memory.append(
        {
            "run_id": run_id,
            "decision_type": decision_type or "rejected",
            "accepted_for_followup": bool(decision_type == "accepted_for_followup"),
            "promoted_to_baseline": bool(decision_type == "promoted_to_baseline"),
            "research_value": maybe_fix_mojibake(auditor.get("research_value", "")),
            "notes": maybe_fix_mojibake("; ".join((coordinator_output.get("reasons", []) or [])[:3])),
            "coordinator_status": coordinator_status,
        }
    )
    research_state["branch_memory"] = memory[-300:]

    # Branch anchor governance.
    anchor = get_branch_anchor_state(research_state)
    dup_info = evaluate_duplicate_throttling(
        rows=(recent_rows or []),
        current_status=clean_text(coordinator_status),
        lookback=15,
    )
    duplicate_throttling_active = bool(dup_info.get("active", False))
    if anchor.get("active", False):
        if clean_text(anchor.get("activated_run_id", "")) != clean_text(run_id):
            rem = int(to_float(anchor.get("remaining_iterations")) or 0)
            rem = max(0, rem - 1)
            anchor["remaining_iterations"] = rem
            if rem <= 0:
                anchor = default_branch_anchor_state()
            else:
                anchor["locked_by_duplicate_throttling"] = bool(duplicate_throttling_active)

    compare_obj = coordinator_output.get("compare", {}) if isinstance(coordinator_output, dict) else {}
    activation = should_activate_branch_anchor(
        decision_type=decision_type,
        compare_obj=(compare_obj if isinstance(compare_obj, dict) else {}),
        proposal=proposal,
        rows=(recent_rows or []),
    )
    if bool(activation.get("activate", False)):
        anchor = {
            "active": True,
            "parameter": clean_text(activation.get("parameter", "")),
            "value": activation.get("anchor_value"),
            "hold_iterations": int(to_float(activation.get("hold_iterations")) or 3),
            "remaining_iterations": int(to_float(activation.get("hold_iterations")) or 3),
            "activated_run_id": run_id,
            "activated_at": now_iso,
            "reason": clean_text(activation.get("reason", "")),
            "locked_by_duplicate_throttling": False,
        }

    if anchor.get("active", False):
        anchor["locked_by_duplicate_throttling"] = bool(duplicate_throttling_active)

    research_state["branch_anchor"] = anchor
    rs_branch["branch_anchor_active"] = bool(anchor.get("active", False))
    rs_branch["anchor_parameter"] = clean_text(anchor.get("parameter", ""))
    rs_branch["anchor_value"] = anchor.get("value")
    rs_branch["anchor_hold_iterations"] = int(
        to_float(anchor.get("remaining_iterations"))
        or (to_float(anchor.get("hold_iterations")) if bool(anchor.get("active", False)) else 0)
        or 0
    )

    research_state["updated_at"] = now_iso
    save_json(research_state_path, research_state)


def append_master_tracker(
    repo: Path,
    run_id: str,
    parent_run_id: str,
    status: str,
    accepted_or_rejected: str,
    proposal: Dict[str, Any],
    cfg: Dict[str, Any],
    executor_output: Dict[str, Any],
    run_dir: Path,
    xlsx_update_cadence: int = 5,
    refresh_xlsx: bool = False,
) -> None:
    cfg = load_paths_config(repo)
    csv_rel = cfg_get_str(cfg, ["trackers", "agent_live_runs_master_csv"], "agent_live_runs_master.csv")
    xlsx_rel = cfg_get_str(cfg, ["trackers", "agent_live_runs_master_xlsx"], "agent_live_runs_master.xlsx")
    csv_path = (repo / csv_rel).resolve()
    xlsx_path = (repo / xlsx_rel).resolve()
    header = [
        "run_id", "date", "parent_run_id", "status", "accepted_or_rejected",
        "main_parameter", "main_to", "dependent_parameter", "dependent_to",
        "strategy_family", "profile_mode", "min_spy_channel_r2", "max_avg_profile_distance",
        "enable_close_vs_sma50_filter", "max_close_vs_sma50_pct", "top_candidates_next_week",
        "w8_weeks_traded", "w24_weeks_traded", "w52_weeks_traded",
        "w8_trades", "w24_trades", "w52_trades",
        "w8_wins", "w24_wins", "w52_wins",
        "w8_losses", "w24_losses", "w52_losses",
        "w8_ties", "w24_ties", "w52_ties",
        "w8_avg_net_return_pct", "w24_avg_net_return_pct", "w52_avg_net_return_pct",
        "w8_total_net_pnl_dollars", "w24_total_net_pnl_dollars", "w52_total_net_pnl_dollars",
        "w8_spy_compare", "w24_spy_compare", "w52_spy_compare", "run_dir",
    ]
    if not csv_path.exists():
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(header)

    def m(window: int, key: str) -> str:
        val = get_metric_from_window(executor_output, window, key)
        n = to_float(val)
        if n is None:
            return clean_text(val)
        return csv_num(n)

    main = proposal.get("main_change") or {}
    dep = proposal.get("dependent_change") or {}
    row = {
        "run_id": run_id,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "parent_run_id": parent_run_id,
        "status": status,
        "accepted_or_rejected": accepted_or_rejected,
        "main_parameter": clean_text(main.get("parameter")),
        "main_to": clean_text(main.get("to_value")),
        "dependent_parameter": clean_text(dep.get("parameter")),
        "dependent_to": clean_text(dep.get("to_value")),
        "strategy_family": clean_text(cfg.get("STRATEGY_FAMILY")),
        "profile_mode": clean_text(cfg.get("PROFILE_MODE")),
        "min_spy_channel_r2": csv_num(cfg.get("MIN_SPY_CHANNEL_R2")),
        "max_avg_profile_distance": csv_num(cfg.get("MAX_AVG_PROFILE_DISTANCE")),
        "enable_close_vs_sma50_filter": clean_text(cfg.get("ENABLE_CLOSE_VS_SMA50_FILTER")),
        "max_close_vs_sma50_pct": csv_num(cfg.get("MAX_CLOSE_VS_SMA50_PCT")),
        "top_candidates_next_week": csv_num(cfg.get("TOP_CANDIDATES_NEXT_WEEK")),
        "w8_weeks_traded": m(8, "weeks_traded"),
        "w24_weeks_traded": m(24, "weeks_traded"),
        "w52_weeks_traded": m(52, "weeks_traded"),
        "w8_trades": m(8, "trades"),
        "w24_trades": m(24, "trades"),
        "w52_trades": m(52, "trades"),
        "w8_wins": m(8, "wins"),
        "w24_wins": m(24, "wins"),
        "w52_wins": m(52, "wins"),
        "w8_losses": m(8, "losses"),
        "w24_losses": m(24, "losses"),
        "w52_losses": m(52, "losses"),
        "w8_ties": m(8, "ties"),
        "w24_ties": m(24, "ties"),
        "w52_ties": m(52, "ties"),
        "w8_avg_net_return_pct": m(8, "avg_net_return_pct"),
        "w24_avg_net_return_pct": m(24, "avg_net_return_pct"),
        "w52_avg_net_return_pct": m(52, "avg_net_return_pct"),
        "w8_total_net_pnl_dollars": m(8, "total_net_pnl_dollars"),
        "w24_total_net_pnl_dollars": m(24, "total_net_pnl_dollars"),
        "w52_total_net_pnl_dollars": m(52, "total_net_pnl_dollars"),
        "w8_spy_compare": m(8, "spy_compare"),
        "w24_spy_compare": m(24, "spy_compare"),
        "w52_spy_compare": m(52, "spy_compare"),
        "run_dir": str(run_dir),
    }
    with csv_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([row.get(h, "") for h in header])

    # Performance: keep CSV append in the hot path, but do not regenerate the XLSX
    # tracker unless explicitly enabled. Rebuilding the XLSX reads the full CSV and
    # rewrites a workbook, which is expensive during autonomous loops.
    if not refresh_xlsx:
        return

    try:
        cadence = int(xlsx_update_cadence)
    except Exception:
        cadence = 0
    if cadence <= 0:
        return

    run_num = parse_run_id(run_id)
    should_refresh_xlsx = (run_num <= 0) or (cadence <= 1) or (run_num % cadence == 0)
    if should_refresh_xlsx:
        try:
            import pandas as pd

            df = pd.read_csv(csv_path, sep=";", dtype=str, encoding="utf-8")
            df.to_excel(xlsx_path, index=False)
        except Exception:
            pass


def parse_windows(raw: str) -> List[int]:
    parts = [p.strip() for p in str(raw).split(",")]
    out: List[int] = []
    for p in parts:
        if p and re.fullmatch(r"\d+", p):
            out.append(int(p))
    out = sorted(list(dict.fromkeys(out)))
    return out or [4, 8, 24, 52]


def build_progressive_window_plan(requested_windows: List[int], year_validation_window_weeks: int) -> List[int]:
    year_w = int(year_validation_window_weeks)
    if year_w < 52:
        year_w = 52
    base = [4, 8, 24, 52, year_w]
    extras = [int(w) for w in requested_windows if int(w) not in base and int(w) > 0]
    plan: List[int] = []
    for w in base + sorted(extras):
        if w not in plan:
            plan.append(w)
    return plan


def normalize_long156_policy(raw: Any) -> str:
    policy = clean_text(raw).lower()
    allowed = {"always", "threshold_or_cadence", "threshold_only", "cadence_only", "never"}
    return policy if policy in allowed else "threshold_or_cadence"


def was_window_executed(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    mode = clean_text(payload.get("execution_mode", "")).lower()
    if mode:
        return mode == "executed"
    errs = [clean_text(x).lower() for x in (payload.get("errors") or []) if clean_text(x)]
    if any(("skipped_by_policy" in e) or ("early_prune_not_executed" in e) for e in errs):
        return False
    if clean_text(payload.get("command", "")):
        return True
    if clean_text(payload.get("stdout_log", "")) or clean_text(payload.get("stderr_log", "")):
        return True
    return False


def run_dir_has_real_156_execution(run_dir_value: Any, repo: Path) -> bool:
    run_dir_s = clean_text(run_dir_value)
    if not run_dir_s:
        return False
    run_dir = Path(run_dir_s)
    if not run_dir.is_absolute():
        run_dir = (repo / run_dir).resolve()
    eo = load_json(run_dir / "executor_output.json", {})
    if not isinstance(eo, dict):
        return False
    p156 = (eo.get("windows", {}) or {}).get("156", {}) or {}
    return was_window_executed(p156)


def count_useful_runs_since_last_real_156(rows: List[Dict[str, str]], repo: Path, max_scan: int = 250) -> int:
    useful = 0
    scanned = 0
    for row in reversed(rows):
        scanned += 1
        if scanned > max_scan:
            break
        if run_dir_has_real_156_execution(row.get("run_dir", ""), repo):
            break
        status = clean_text(row.get("status", ""))
        accepted = clean_text(row.get("accepted_or_rejected", ""))
        if status in {"run_ok", "run_partial_valid"} and accepted == "accepted":
            useful += 1
    return useful


def evaluate_w52_threshold_for_156(
    windows_results: Dict[str, Any],
    min_spy_compare: float,
    min_weeks_traded: float,
    min_trades: float,
) -> Dict[str, Any]:
    p52 = (windows_results.get("52", {}) or {})
    status = clean_text(p52.get("status", ""))
    depth_ok = bool(p52.get("depth_ok", False))
    metrics = p52.get("metrics", {}) or {}
    w52_spy = to_float(metrics.get("spy_compare"))
    w52_weeks_traded = to_float(metrics.get("weeks_traded"))
    w52_trades = to_float(metrics.get("trades"))
    has_minimum_window = status == "run_ok" and depth_ok
    threshold_met = bool(
        has_minimum_window
        and (w52_spy is not None and float(w52_spy) >= float(min_spy_compare))
        and (w52_weeks_traded is not None and float(w52_weeks_traded) >= float(min_weeks_traded))
        and (w52_trades is not None and float(w52_trades) >= float(min_trades))
    )
    return {
        "threshold_met": threshold_met,
        "status_52": status,
        "depth_ok_52": depth_ok,
        "w52_spy_compare": w52_spy,
        "w52_weeks_traded": w52_weeks_traded,
        "w52_trades": w52_trades,
        "min_w52_spy_compare": float(min_spy_compare),
        "min_w52_weeks_traded": float(min_weeks_traded),
        "min_w52_trades": float(min_trades),
    }


def should_execute_156_window(
    policy: str,
    windows_results: Dict[str, Any],
    useful_runs_since_last_real_156: int,
    cadence_useful_runs: int,
    min_w52_spy_compare: float,
    min_w52_weeks_traded: float,
    min_w52_trades: float,
) -> Tuple[bool, Dict[str, Any]]:
    norm_policy = normalize_long156_policy(policy)
    threshold_eval = evaluate_w52_threshold_for_156(
        windows_results=windows_results,
        min_spy_compare=min_w52_spy_compare,
        min_weeks_traded=min_w52_weeks_traded,
        min_trades=min_w52_trades,
    )
    threshold_met = bool(threshold_eval.get("threshold_met", False))
    cadence_needed = max(1, int(cadence_useful_runs))
    cadence_met = int(useful_runs_since_last_real_156) >= cadence_needed

    run_156 = True
    trigger = "always"
    if norm_policy == "never":
        run_156 = False
        trigger = "none"
    elif norm_policy == "threshold_only":
        run_156 = threshold_met
        trigger = "threshold" if threshold_met else "none"
    elif norm_policy == "cadence_only":
        run_156 = cadence_met
        trigger = "cadence" if cadence_met else "none"
    elif norm_policy == "threshold_or_cadence":
        run_156 = threshold_met or cadence_met
        if threshold_met:
            trigger = "threshold"
        elif cadence_met:
            trigger = "cadence"
        else:
            trigger = "none"

    detail = {
        "policy": norm_policy,
        "run_156": bool(run_156),
        "trigger": trigger,
        "threshold_met": bool(threshold_met),
        "cadence_met": bool(cadence_met),
        "cadence_useful_runs_required": cadence_needed,
        "useful_runs_since_last_real_156": int(useful_runs_since_last_real_156),
        "threshold_eval": threshold_eval,
    }
    return bool(run_156), detail


def get_window_payload(executor_output: Dict[str, Any], window_weeks: int) -> Dict[str, Any]:
    return (executor_output.get("windows", {}).get(str(int(window_weeks)), {}) or {})


def get_window_metrics_if_valid_depth(executor_output: Dict[str, Any], window_weeks: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    payload = get_window_payload(executor_output, window_weeks)
    status = clean_text(payload.get("status", ""))
    requested = int(to_float(payload.get("requested_weeks")) or int(window_weeks))
    actual_raw = to_float(payload.get("actual_weeks_run"))
    depth_ok = bool(payload.get("depth_ok", False))
    if actual_raw is not None and actual_raw < requested:
        depth_ok = False
    meta = {
        "status": status,
        "requested_weeks": requested,
        "actual_weeks_run": (int(round(actual_raw)) if actual_raw is not None else None),
        "depth_ok": depth_ok,
    }
    if status != "run_ok" or (not depth_ok):
        return {}, meta
    return (payload.get("metrics", {}) or {}), meta


def evaluate_depth_limited_followup_rule(
    executor_output: Dict[str, Any],
    year_validation_window_weeks: int,
) -> Dict[str, Any]:
    short_windows = [4, 8, 24, 52]
    short_eval: Dict[str, Any] = {}
    short_all_valid = True
    for w in short_windows:
        metrics_w, meta_w = get_window_metrics_if_valid_depth(executor_output, w)
        valid = bool(metrics_w) and bool(meta_w.get("depth_ok", False)) and clean_text(meta_w.get("status", "")) == "run_ok"
        short_eval[str(w)] = {"valid": valid, "meta": meta_w}
        if not valid:
            short_all_valid = False

    year_payload = get_window_payload(executor_output, int(year_validation_window_weeks))
    year_status = clean_text(year_payload.get("status", ""))
    year_depth_ok = bool(year_payload.get("depth_ok", False))
    year_actual = to_float(year_payload.get("actual_weeks_run"))
    year_requested = int(to_float(year_payload.get("requested_weeks")) or int(year_validation_window_weeks))
    year_insufficient = year_status == "insufficient_depth" or (
        (not year_depth_ok)
        and year_status in {"run_ok", "insufficient_depth"}
        and year_requested >= 156
    )

    applies = bool(short_all_valid and year_requested >= 156 and year_insufficient)
    return {
        "applies": applies,
        "short_windows_required": short_windows,
        "short_windows_validation": short_eval,
        "year_window_requested": year_requested,
        "year_window_status": year_status,
        "year_window_depth_ok": year_depth_ok,
        "year_window_actual_weeks_run": (int(round(year_actual)) if year_actual is not None else None),
        "notes": (
            "4/8/24/52 validas y ventana larga insuficiente: sirve para follow-up y parent tecnico, "
            "sin promocion automatica a baseline."
            if applies
            else ""
        ),
    }


def config_hash(cfg: Dict[str, Any], keys: List[str]) -> str:
    payload = {k: normalize_scalar(cfg.get(k)) for k in keys}
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def load_existing_config_hashes(runs_root: Path, keys: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not runs_root.exists():
        return out
    for d in runs_root.iterdir():
        if not d.is_dir():
            continue
        cfg_path = d / "candidate_config.json"
        eo_path = d / "executor_output.json"
        if not cfg_path.exists() or not eo_path.exists():
            continue
        eo = load_json(eo_path, {})
        if clean_text(eo.get("status", "")) not in {"run_ok", "run_partial_valid"}:
            continue
        # For duplicate/cooldown blocking we intentionally include every executed
        # run with a valid executor output, including rejected runs. Parent
        # selection still uses only useful runs elsewhere; this function is only
        # about not spending compute on an already-tested config.
        cfg = load_json(cfg_path, {})
        if not isinstance(cfg, dict):
            continue
        out[config_hash(cfg, keys)] = d.name
    return out


def mark_queue_item(path: Path, queue_id: str, status: str, run_id: str) -> None:
    queue = load_json(path, [])
    if not isinstance(queue, list):
        return
    changed = False
    for item in queue:
        if str(item.get("id", "")) == queue_id:
            item["status"] = status
            item["updated_at"] = datetime.now().isoformat(timespec="seconds")
            item["run_id"] = run_id
            changed = True
            break
    if changed:
        save_json(path, queue)


def refresh_subspace_cooldowns_state(cooldowns_state: Dict[str, Any], current_iteration: int) -> bool:
    changed = False
    for row in _cooldown_entries(cooldowns_state):
        if not bool(row.get("cooldown_active", False)):
            continue
        until_it = int(to_float(row.get("cooldown_until_iteration")) or 0)
        if int(current_iteration) > until_it:
            row["cooldown_active"] = False
            changed = True
    return changed


def compute_current_vs_parent_deltas(
    last_valid_ctx: Optional[Dict[str, Any]],
    executor_output: Dict[str, Any],
) -> Dict[str, Optional[float]]:
    parent_w24 = get_window_metrics_from_ctx(last_valid_ctx, 24)
    parent_w52 = get_window_metrics_from_ctx(last_valid_ctx, 52)
    curr_w24 = ((executor_output.get("windows", {}) or {}).get("24", {}) or {}).get("metrics", {}) or {}
    curr_w52 = ((executor_output.get("windows", {}) or {}).get("52", {}) or {}).get("metrics", {}) or {}
    p24_spy = to_float(parent_w24.get("spy_compare"))
    c24_spy = to_float(curr_w24.get("spy_compare"))
    p52_spy = to_float(parent_w52.get("spy_compare"))
    c52_spy = to_float(curr_w52.get("spy_compare"))
    p52_pnl = to_float(parent_w52.get("total_net_pnl_dollars"))
    c52_pnl = to_float(curr_w52.get("total_net_pnl_dollars"))
    p52_trades = to_float(parent_w52.get("trades"))
    c52_trades = to_float(curr_w52.get("trades"))
    p52_avg = to_float(parent_w52.get("avg_net_return_pct"))
    c52_avg = to_float(curr_w52.get("avg_net_return_pct"))
    return {
        "delta_w24_spy_compare": (round(c24_spy - p24_spy, 6) if c24_spy is not None and p24_spy is not None else None),
        "delta_w52_spy_compare": (round(c52_spy - p52_spy, 6) if c52_spy is not None and p52_spy is not None else None),
        "delta_w52_pnl": (round(c52_pnl - p52_pnl, 6) if c52_pnl is not None and p52_pnl is not None else None),
        "delta_w52_trades": (round(c52_trades - p52_trades, 6) if c52_trades is not None and p52_trades is not None else None),
        "delta_w52_avg_net_return_pct": (round(c52_avg - p52_avg, 6) if c52_avg is not None and p52_avg is not None else None),
    }


def compute_recent_transition_stats(
    rows: List[Dict[str, str]],
    parameter: str,
    normalized_from: str,
    normalized_to: str,
    lookback: int = 25,
) -> Dict[str, Any]:
    sorted_rows = sorted(rows or [], key=lambda r: parse_run_id(r.get("run_id", "")))
    recent = sorted_rows[-max(1, int(lookback)) :] if sorted_rows else []
    run_spy_map: Dict[str, Optional[float]] = {}
    for r in sorted_rows:
        rid = clean_text(r.get("run_id", ""))
        if rid:
            run_spy_map[rid] = to_float(r.get("w52_spy_compare"))

    matched: List[Dict[str, Any]] = []
    for r in recent:
        if clean_text(r.get("status", "")) not in {"run_ok", "run_partial_valid"}:
            continue
        p = clean_text(r.get("main_parameter", ""))
        if p != clean_text(parameter):
            continue
        f_norm = normalize_scalar(r.get("main_from"))
        t_norm = normalize_scalar(r.get("main_to"))
        if f_norm != clean_text(normalized_from) or t_norm != clean_text(normalized_to):
            continue
        rid = clean_text(r.get("run_id", ""))
        decision = clean_text(r.get("accepted_or_rejected", "")).lower()
        row_spy = to_float(r.get("w52_spy_compare"))
        parent_spy = run_spy_map.get(clean_text(r.get("parent_run_id", "")))
        delta = None
        if row_spy is not None and parent_spy is not None:
            delta = row_spy - parent_spy
        matched.append(
            {
                "run_id": rid,
                "decision": decision,
                "delta_w52_spy_vs_parent": delta,
            }
        )

    total = len(matched)
    rejected = sum(1 for x in matched if x.get("decision") != "accepted")
    reject_ratio = (float(rejected) / float(total)) if total > 0 else 0.0
    deltas = [to_float(x.get("delta_w52_spy_vs_parent")) for x in matched]
    deltas = [float(d) for d in deltas if d is not None and math.isfinite(float(d))]
    max_delta = max(deltas) if deltas else None
    has_incremental_improvement = bool(max_delta is not None and max_delta > 0.10)
    return {
        "total_repeats": total,
        "rejected_count": rejected,
        "reject_ratio": round(reject_ratio, 6),
        "max_delta_w52_spy_vs_parent": (round(max_delta, 6) if max_delta is not None else None),
        "has_incremental_improvement": has_incremental_improvement,
        "run_ids": [clean_text(x.get("run_id", "")) for x in matched if clean_text(x.get("run_id", ""))],
    }


def update_learning_memory_after_run(
    parameter_effect_memory: Dict[str, Any],
    subspace_cooldowns: Dict[str, Any],
    run_id: str,
    proposal: Dict[str, Any],
    decision_type: str,
    executor_status: str,
    compare_obj: Dict[str, Any],
    executor_output: Dict[str, Any],
    last_valid_ctx: Optional[Dict[str, Any]],
    branch_state_snapshot: Dict[str, Any],
    auditor_eval: Dict[str, Any],
    rows_for_recent_stats: List[Dict[str, str]],
) -> Tuple[bool, bool]:
    changed_effect = False
    changed_cooldown = False
    main_change = proposal.get("main_change", {}) if isinstance(proposal, dict) else {}
    parameter = clean_text(main_change.get("parameter", ""))
    if not parameter:
        return changed_effect, changed_cooldown
    from_value = main_change.get("from_value")
    to_value = main_change.get("to_value")
    key = transition_key(parameter, from_value, to_value)
    if key[1] == key[2]:
        return changed_effect, changed_cooldown
    if clean_text(executor_status) not in {"run_ok", "run_partial_valid", "run_error"}:
        return changed_effect, changed_cooldown

    entry = get_parameter_effect_entry(
        parameter_effect_memory,
        parameter=parameter,
        from_value=key[1],
        to_value=key[2],
        create_if_missing=True,
    )
    if not isinstance(entry, dict):
        return changed_effect, changed_cooldown

    entry["total_attempts"] = int(to_float(entry.get("total_attempts")) or 0) + 1
    if clean_text(decision_type) in {"accepted_for_followup", "promoted_to_baseline"}:
        entry["accepted_count"] = int(to_float(entry.get("accepted_count")) or 0) + 1
    else:
        entry["rejected_count"] = int(to_float(entry.get("rejected_count")) or 0) + 1
    last_ids = [clean_text(x) for x in (entry.get("last_run_ids") or []) if clean_text(x)]
    if clean_text(run_id):
        last_ids.append(clean_text(run_id))
    entry["last_run_ids"] = list(dict.fromkeys(last_ids))[-12:]

    deltas = compute_current_vs_parent_deltas(last_valid_ctx=last_valid_ctx, executor_output=executor_output)
    _update_running_avg(
        entry,
        "avg_delta_w24_spy_compare",
        "avg_delta_w24_spy_compare",
        to_float(deltas.get("delta_w24_spy_compare")),
    )
    _update_running_avg(
        entry,
        "avg_delta_w52_spy_compare",
        "avg_delta_w52_spy_compare",
        to_float(deltas.get("delta_w52_spy_compare")),
    )
    _update_running_avg(
        entry,
        "avg_delta_w52_pnl",
        "avg_delta_w52_pnl",
        to_float(deltas.get("delta_w52_pnl")),
    )
    _update_running_avg(
        entry,
        "avg_delta_w52_trades",
        "avg_delta_w52_trades",
        to_float(deltas.get("delta_w52_trades")),
    )
    _update_running_avg(
        entry,
        "avg_delta_w52_avg_net_return_pct",
        "avg_delta_w52_avg_net_return_pct",
        to_float(deltas.get("delta_w52_avg_net_return_pct")),
    )

    branch_health = clean_text(auditor_eval.get("branch_health", "")) or clean_text(branch_state_snapshot.get("branch_health", ""))
    main_friction = clean_text(auditor_eval.get("main_friction", "")) or clean_text(branch_state_snapshot.get("main_friction", ""))
    entry["branch_health_when_tested"] = branch_health
    entry["main_friction_when_tested"] = main_friction

    delta_w52_spy = to_float(deltas.get("delta_w52_spy_compare"))
    best_delta = to_float(entry.get("_best_delta_w52_spy_compare"))
    if delta_w52_spy is not None and (best_delta is None or float(delta_w52_spy) > float(best_delta)):
        entry["_best_delta_w52_spy_compare"] = round(float(delta_w52_spy), 6)
        entry["best_run_id"] = clean_text(run_id)
        entry["best_context_summary"] = (
            f"decision={clean_text(decision_type)}; "
            f"delta_w52_spy={round(float(delta_w52_spy), 6)}; "
            f"branch_health={branch_health}; main_friction={main_friction}"
        )

    long_depth_block = bool(
        clean_text(decision_type) == "accepted_for_followup"
        and bool(compare_obj.get("long_window_required_for_promotion", False))
        and (not bool(compare_obj.get("long_window_depth_ok", False)))
    )
    if long_depth_block and delta_w52_spy is not None and float(delta_w52_spy) >= 0.50:
        entry["champion_for_followup"] = True
        entry["reusable_parent"] = True
        entry["best_context_summary"] = (
            f"champion_for_followup=1; reusable_parent=1; "
            f"delta_w52_spy={round(float(delta_w52_spy), 6)}; "
            f"reason=strong_w52_but_long_window_depth_limited"
        )

    entry["current_effect_class"] = classify_parameter_effect_class(entry)
    changed_effect = True

    run_num = parse_run_id(run_id)
    metric_no_effect_current = bool(
        ((compare_obj.get("effective_change_vs_parent_w52", {}) or {}).get("metric_no_effect", False))
        or ((compare_obj.get("effective_change_vs_current_baseline_w52", {}) or {}).get("metric_no_effect", False))
    )
    if metric_no_effect_current:
        entry["current_effect_class"] = "exhausted_no_effect"
        entry["last_no_effect_run_id"] = clean_text(run_id)
        entry["no_effect_count"] = int(to_float(entry.get("no_effect_count")) or 0) + 1
        cooldown_entry = get_subspace_cooldown_entry(
            subspace_cooldowns,
            parameter=key[0],
            from_value=key[1],
            to_value=key[2],
            create_if_missing=True,
        )
        if isinstance(cooldown_entry, dict):
            cooldown_len = max(5, int(to_float(subspace_cooldowns.get("default_cooldown_iterations")) or 8))
            current_until = int(to_float(cooldown_entry.get("cooldown_until_iteration")) or 0)
            cooldown_entry["cooldown_active"] = True
            cooldown_entry["cooldown_until_iteration"] = max(current_until, int(parse_run_id(run_id)) + cooldown_len)
            cooldown_entry["reason"] = "metric_no_effect: transition produced identical 52w metrics vs parent/current_baseline"
            cooldown_entry["override_only_if"] = "new_parent_champion | changed_feature_set | explicit_human_override"
            changed_cooldown = True
        changed_effect = True

    recent_stats = compute_recent_transition_stats(
        rows=rows_for_recent_stats,
        parameter=key[0],
        normalized_from=key[1],
        normalized_to=key[2],
        lookback=25,
    )
    should_exhaust = bool(
        int(recent_stats.get("total_repeats", 0)) >= 3
        and float(to_float(recent_stats.get("reject_ratio")) or 0.0) >= 0.75
        and (not bool(recent_stats.get("has_incremental_improvement", False)))
    )
    if should_exhaust:
        cooldown_entry = get_subspace_cooldown_entry(
            subspace_cooldowns,
            parameter=key[0],
            from_value=key[1],
            to_value=key[2],
            create_if_missing=True,
        )
        if isinstance(cooldown_entry, dict):
            cooldown_len = max(3, int(to_float(subspace_cooldowns.get("default_cooldown_iterations")) or 8))
            current_until = int(to_float(cooldown_entry.get("cooldown_until_iteration")) or 0)
            next_until = max(current_until, int(run_num) + cooldown_len)
            cooldown_entry["cooldown_active"] = True
            cooldown_entry["cooldown_until_iteration"] = next_until
            cooldown_entry["reason"] = (
                "exhausted_transition: repeats>=3 and reject_ratio>=0.75 and no_incremental_improvement"
            )
            cooldown_entry["reject_ratio"] = round(float(to_float(recent_stats.get("reject_ratio")) or 0.0), 6)
            cooldown_entry["last_run_ids"] = [clean_text(x) for x in (recent_stats.get("run_ids") or []) if clean_text(x)][-10:]
            cooldown_entry["override_only_if"] = "evidence_based_retry_explicit | new_parent_champion | orthogonal_context_change"
            entry["current_effect_class"] = "exhausted"
            changed_cooldown = True
            changed_effect = True

    if refresh_subspace_cooldowns_state(subspace_cooldowns, int(run_num)):
        changed_cooldown = True
    return changed_effect, changed_cooldown


def _extract_primary_transition_class(compare_obj: Dict[str, Any]) -> str:
    tc = compare_obj.get("transition_classification", []) if isinstance(compare_obj, dict) else []
    if isinstance(tc, list):
        for x in tc:
            if isinstance(x, dict):
                c = clean_text(x.get("classification", ""))
                if c:
                    return c
            else:
                c = clean_text(x)
                if c:
                    return c
    return ""


def update_champion_runs_after_run(
    champion_runs: Dict[str, Any],
    run_id: str,
    parent_run_id: str,
    proposal: Dict[str, Any],
    decision_type: str,
    executor_status: str,
    compare_obj: Dict[str, Any],
    executor_output: Dict[str, Any],
) -> bool:
    if clean_text(executor_status) not in {"run_ok", "run_partial_valid"}:
        return False
    champions = champion_runs.get("champions", {}) if isinstance(champion_runs, dict) else {}
    metadata = champion_runs.get("metadata", {}) if isinstance(champion_runs, dict) else {}
    if not isinstance(champions, dict):
        champions = {}
        champion_runs["champions"] = champions
    if not isinstance(metadata, dict):
        metadata = {}
        champion_runs["metadata"] = metadata
    for slot in CHAMPION_SLOTS:
        if slot not in champions:
            champions[slot] = ""
        if slot not in metadata or not isinstance(metadata.get(slot), dict):
            metadata[slot] = {}

    w24 = ((executor_output.get("windows", {}) or {}).get("24", {}) or {}).get("metrics", {}) or {}
    w52 = ((executor_output.get("windows", {}) or {}).get("52", {}) or {}).get("metrics", {}) or {}
    w156_payload = get_window_payload(executor_output, 156)
    w156 = w156_payload.get("metrics", {}) if isinstance(w156_payload, dict) else {}
    w24_spy = to_float(w24.get("spy_compare"))
    w52_spy = to_float(w52.get("spy_compare"))
    w52_pnl = to_float(w52.get("total_net_pnl_dollars"))
    w52_avg = to_float(w52.get("avg_net_return_pct"))
    w52_trades = to_float(w52.get("trades"))
    w156_spy = to_float((w156 or {}).get("spy_compare"))
    w156_depth_ok = bool(w156_payload.get("depth_ok", False))
    transition_class = _extract_primary_transition_class(compare_obj)
    champion_for_followup = bool(compare_obj.get("champion_for_followup", False))
    useful_or_champion = (clean_text(decision_type) in {"accepted_for_followup", "promoted_to_baseline"} or champion_for_followup) and not bool(compare_obj.get("do_not_use_as_parent", False))
    if not useful_or_champion:
        return False

    run_num = parse_run_id(run_id)
    now_iso = datetime.now().isoformat(timespec="seconds")
    main_change_obj = proposal.get("main_change", {}) if isinstance(proposal, dict) else {}
    main_change = ""
    if isinstance(main_change_obj, dict) and clean_text(main_change_obj.get("parameter", "")):
        main_change = (
            f"{clean_text(main_change_obj.get('parameter', ''))}: "
            f"{normalize_scalar(main_change_obj.get('from_value'))} -> {normalize_scalar(main_change_obj.get('to_value'))}"
        )
    accepted_for_followup = clean_text(decision_type) == "accepted_for_followup"
    promoted_to_baseline = clean_text(decision_type) == "promoted_to_baseline"
    balance_score: Optional[float] = None
    if w52_spy is not None:
        balance_score = float(w52_spy)
        if w52_avg is not None:
            balance_score += 0.35 * float(w52_avg)
        if w52_trades is not None:
            balance_score += min(max(float(w52_trades), 0.0), 120.0) / 120.0

    changed = False

    def _update_slot(slot: str, score: Optional[float], reason: str, force_recent: bool = False) -> None:
        nonlocal changed
        if score is None and not force_recent:
            return
        curr_rid = clean_text(champions.get(slot, ""))
        curr_meta = metadata.get(slot, {}) if isinstance(metadata.get(slot), dict) else {}
        curr_score = to_float(curr_meta.get("score"))
        curr_num = parse_run_id(curr_rid)
        should_update = False
        if force_recent:
            should_update = run_num >= curr_num
        else:
            if curr_score is None:
                should_update = True
            elif score is not None and float(score) > float(curr_score):
                should_update = True
            elif score is not None and abs(float(score) - float(curr_score)) <= 1e-12 and run_num > curr_num:
                should_update = True
        if not should_update:
            return
        champions[slot] = clean_text(run_id)
        metadata[slot] = {
            "run_id": clean_text(run_id),
            "parent_run_id": clean_text(parent_run_id),
            "main_change": main_change,
            "w24_spy_compare": w24_spy,
            "decision_type": clean_text(decision_type),
            "status": clean_text(executor_status),
            "accepted_for_followup": bool(accepted_for_followup),
            "promoted_to_baseline": bool(promoted_to_baseline),
            "champion_for_followup": bool(champion_for_followup),
            "reusable_parent": bool(champion_for_followup or accepted_for_followup or promoted_to_baseline),
            "w52_spy_compare": w52_spy,
            "w52_pnl": w52_pnl,
            "w52_avg_net_return_pct": w52_avg,
            "w52_trades": w52_trades,
            "w156_spy_compare": w156_spy,
            "w156_depth_ok": bool(w156_depth_ok),
            "w156_status": clean_text(w156_payload.get("status", "")),
            "transition_classification": clean_text(transition_class),
            "score": (round(float(score), 6) if score is not None else None),
            "reason": clean_text(reason),
            "why_it_is_a_champion": clean_text(reason),
            "updated_at": now_iso,
        }
        changed = True

    if clean_text(decision_type) == "accepted_for_followup" or champion_for_followup:
        _update_slot(
            "best_recent_followup_run_id",
            score=float(run_num),
            reason="latest_followup_or_champion_candidate",
            force_recent=True,
        )
    _update_slot(
        "best_w52_spy_compare_run_id",
        score=w52_spy,
        reason="max_w52_spy_compare",
    )
    _update_slot(
        "best_balance_quality_frequency_run_id",
        score=balance_score,
        reason="best_balance_quality_frequency_score",
    )
    if w156_depth_ok and w156_spy is not None:
        _update_slot(
            "best_multi_year_real_run_id",
            score=w156_spy,
            reason="best_multi_year_real_depth_ok",
        )
    if clean_text(transition_class) in {"controlled_exploration", "fresh_change"}:
        ortho_score = w52_spy if w52_spy is not None else balance_score
        _update_slot(
            "best_orthogonal_exploration_run_id",
            score=ortho_score,
            reason="best_orthogonal_exploration_signal",
        )

    if changed:
        champion_runs["updated_at"] = now_iso
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--python-exe", default=sys.executable or "python")
    ap.add_argument("--baseline-json", default="state/current_baseline.json")
    ap.add_argument("--experiment-log", default="trackers/experiment_log.csv")
    ap.add_argument("--dependencies-json", default="config/parameter_dependencies.json")
    ap.add_argument("--evaluation-windows", default="4,8,24,52")
    ap.add_argument(
        "--allow-progressive-windows",
        action="store_true",
        help="If set, executor may extend beyond requested windows using the progressive plan.",
    )
    ap.add_argument("--year-validation-window-weeks", type=int, default=52)
    ap.add_argument("--long156-policy", default=None)
    ap.add_argument("--long156-cadence-useful-runs", type=int, default=None)
    ap.add_argument("--long156-min-w52-spy-compare", type=float, default=None)
    ap.add_argument("--long156-min-w52-weeks-traded", type=float, default=None)
    ap.add_argument("--long156-min-w52-trades", type=float, default=None)
    ap.add_argument("--min-years-vs-spy", type=int, default=2)
    ap.add_argument("--max-nonpositive-years-vs-spy", type=int, default=0)
    ap.add_argument("--tie-low", type=float, default=0.0)
    ap.add_argument("--tie-high", type=float, default=1.0)
    ap.add_argument("--timeout-sec-per-run", type=int, default=4500)
    ap.add_argument("--xlsx-cadence-runs", type=int, default=None)
    ap.add_argument(
        "--enable-tracker-xlsx-refresh",
        action="store_true",
        help="Regenerate the master XLSX tracker during this run. Default is off for autonomous-loop performance.",
    )
    ap.add_argument(
        "--enable-window-xlsx-artifacts",
        action="store_true",
        help="Allow window backtests to export XLSX artifacts. Default is off; CSV artifacts are used in the hot path.",
    )
    ap.add_argument("--profile-cadence-runs", type=int, default=None)
    ap.add_argument("--disable-fast-artifacts", action="store_true")
    ap.add_argument("--disable-early-prune", action="store_true")
    ap.add_argument("--disable-window-reuse", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--apply-baseline-promotion",
        action="store_true",
        help="If set, apply promoted_to_baseline changes to state/current_baseline.json. Otherwise, promotion remains pending.",
    )
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    cfg = load_paths_config(repo)

    baseline_rel = cfg_get_str(cfg, ["state", "current_baseline"], args.baseline_json)
    exp_log_rel = cfg_get_str(cfg, ["trackers", "experiment_log"], args.experiment_log)
    dep_rel = cfg_get_str(cfg, ["config", "parameter_dependencies"], args.dependencies_json)
    if dep_rel == args.dependencies_json:
        # paths_config.json uses config/parameter_dependencies.json but we keep this fallback
        dep_rel = args.dependencies_json

    queue_rel = cfg_get_str(
        cfg, ["state", "analyst_initial_tests_queue"], "state/queues/analyst_initial_tests_queue.json"
    )
    research_state_rel = cfg_get_str(cfg, ["state", "research_state"], "state/research_state.json")
    parameter_effect_memory_rel = cfg_get_str(
        cfg, ["state", "parameter_effect_memory"], "state/parameter_effect_memory.json"
    )
    subspace_cooldowns_rel = cfg_get_str(
        cfg, ["state", "subspace_cooldowns"], "state/subspace_cooldowns.json"
    )
    legacy_champion_runs_rel = cfg_get_str(
        cfg, ["runs", "champion_runs_json"], "runs/champion_runs/champion_runs.json"
    )
    champion_runs_rel = cfg_get_str(
        cfg, ["state", "champion_runs"], legacy_champion_runs_rel
    )
    runs_root_rel = cfg_get_str(cfg, ["runs", "multi_agent_runs"], "runs/multi_agent_runs")

    baseline_path = (repo / baseline_rel).resolve()
    exp_log_path = (repo / exp_log_rel).resolve()
    dep_path = (repo / dep_rel).resolve()
    queue_path = (repo / queue_rel).resolve()
    research_state_path = (repo / research_state_rel).resolve()
    parameter_effect_memory_path = (repo / parameter_effect_memory_rel).resolve()
    subspace_cooldowns_path = (repo / subspace_cooldowns_rel).resolve()
    legacy_subspace_cooldowns_path = (repo / "subspace_cooldowns.json").resolve()
    champion_runs_path = (repo / champion_runs_rel).resolve()
    legacy_champion_runs_path = (repo / legacy_champion_runs_rel).resolve()
    runs_root = (repo / runs_root_rel).resolve()
    runs_root.mkdir(parents=True, exist_ok=True)
    if (not subspace_cooldowns_path.exists()) and legacy_subspace_cooldowns_path.exists():
        legacy_cooldowns = load_json(legacy_subspace_cooldowns_path, default_subspace_cooldowns())
        if isinstance(legacy_cooldowns, dict):
            save_json(subspace_cooldowns_path, legacy_cooldowns)
    if (not champion_runs_path.exists()) and legacy_champion_runs_path.exists():
        legacy_champions = load_json(legacy_champion_runs_path, default_champion_runs())
        if isinstance(legacy_champions, dict):
            save_json(champion_runs_path, legacy_champions)

    baseline = ensure_baseline(baseline_path, repo)
    research_state = ensure_research_state(research_state_path, baseline)
    parameter_effect_memory = ensure_parameter_effect_memory(parameter_effect_memory_path)
    subspace_cooldowns = ensure_subspace_cooldowns(subspace_cooldowns_path)
    champion_runs = ensure_champion_runs(champion_runs_path)
    branch_anchor, anchor_synced = reconcile_branch_anchor_state(baseline, research_state)
    if anchor_synced:
        now_iso = datetime.now().isoformat(timespec="seconds")
        research_state["updated_at"] = now_iso
        save_json(research_state_path, research_state)
    validation_phase = str(baseline.get("validation_phase", "year1")).strip().lower()
    if validation_phase not in {"year1", "multi_year"}:
        validation_phase = "year1"
        # Do not persist baseline fixes implicitly (baseline immutability policy).
    baseline_cfg: Dict[str, Any] = dict(baseline.get("active_config", {}))
    tracked_keys = sorted(list(baseline_cfg.keys()))
    ensure_experiment_log(exp_log_path)
    initialize_test_queue(queue_path)

    rows = read_experiment_log(exp_log_path)
    global _AUDIT_RECENT_ROWS
    _AUDIT_RECENT_ROWS = list(rows)
    run_id = next_run_id(rows, runs_root)
    if refresh_subspace_cooldowns_state(subspace_cooldowns, parse_run_id(run_id)):
        subspace_cooldowns["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_json(subspace_cooldowns_path, subspace_cooldowns)
    run_dir = runs_root / f"{run_id}_{datetime.now().strftime('%y%m%d%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_status_log = run_dir / "run_live_status.log"
    exit_ctx: Dict[str, Any] = {
        "reason": "process_exit_before_finalization",
        "status_hint": "run_error",
        "requested_windows": [],
        "allowed_windows": [],
        "progressive_windows": [],
    }

    def run_log(msg: str) -> None:
        log(msg)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with run_status_log.open("a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

    def finalize_on_exit() -> None:
        # Best-effort finalization for controlled aborts / uncaught exceptions.
        try:
            ensure_controlled_abort_artifacts(
                run_dir=run_dir,
                run_id=run_id,
                requested_windows=[int(x) for x in (exit_ctx.get("requested_windows") or [])],
                allowed_windows=[int(x) for x in (exit_ctx.get("allowed_windows") or [])],
                progressive_windows=[int(x) for x in (exit_ctx.get("progressive_windows") or [])],
                reason=clean_text(exit_ctx.get("reason", "")),
                status_hint=clean_text(exit_ctx.get("status_hint", "")) or "run_error",
            )
        except Exception:
            pass

    atexit.register(finalize_on_exit)

    run_log(f"RUN START run_id={run_id} run_dir={run_dir}")

    baseline_parent_requested = research_state_requests_baseline_parent(research_state)
    latest_valid, parent_source, rejected_startup_parent_run_id, rejected_startup_parent_reason = get_preferred_parent_context(
        repo,
        baseline,
        research_state,
        champion_runs=champion_runs,
        rows=rows,
    )
    if not latest_valid and not baseline_parent_requested and parent_source != "current_baseline":
        latest_valid = get_latest_valid_run_context(repo)
        parent_source = "scan_latest_valid" if latest_valid else "baseline_reference"
    elif not latest_valid:
        parent_source = "current_baseline"
    baseline_script = Path(str(baseline.get("baseline_script", "")))
    if not baseline_script.is_absolute():
        baseline_script = (repo / baseline_script).resolve()
    parent_script = baseline_script
    parent_run_id = "BASELINE_CLEAN"
    if latest_valid:
        parent_script = Path(str(latest_valid.get("script_path", parent_script))).resolve()
        parent_run_id = str(latest_valid.get("run_id", "BASELINE_CLEAN")) or "BASELINE_CLEAN"
    run_log(
        "CONTEXT "
        f"validation_phase={validation_phase} parent_run_id={parent_run_id} "
        f"parent_script={parent_script.name} "
        f"parent_source={parent_source} "
        f"rejected_startup_parent_run_id={rejected_startup_parent_run_id} "
        f"rejected_startup_parent_reason={rejected_startup_parent_reason}"
    )
    run_log(
        "CONTEXT branch_anchor "
        f"active={int(bool(branch_anchor.get('active', False)))} "
        f"parameter={branch_anchor.get('parameter', '')} "
        f"value={branch_anchor.get('value', '')} "
        f"remaining_iterations={branch_anchor.get('remaining_iterations', 0)} "
        f"locked_by_duplicate_throttling={int(bool(branch_anchor.get('locked_by_duplicate_throttling', False)))}"
    )

    if not parent_script.exists():
        msg = f"Parent script inexistente: {parent_script}"
        run_log(msg)
        append_experiment_row(
            exp_log_path,
            {
                "run_id": run_id,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "parent_run_id": parent_run_id,
                "parent_script": str(parent_script),
                "baseline_reference": clean_text((baseline.get("baseline_reference") or {}).get("run_id")),
                "status": "blocked_parent_missing",
                "accepted_or_rejected": "rejected",
                "notes": f"decision_type=rejected; {msg}",
                "run_dir": str(run_dir),
            },
        )
        exit_ctx["status_hint"] = "blocked_parent_missing"
        exit_ctx["reason"] = msg
        return 2

    parent_cfg = load_script_config(parent_script, tracked_keys, baseline_cfg)

    long_window_policy_cfg = (
        ((baseline.get("validation_policy") or {}).get("long_window_policy") or {})
        if isinstance(baseline.get("validation_policy"), dict)
        else {}
    )
    if not isinstance(long_window_policy_cfg, dict):
        long_window_policy_cfg = {}

    def _resolve_int(cli_val: Any, cfg_key: str, default: int) -> int:
        if cli_val is not None:
            return int(cli_val)
        cfg_v = to_float(long_window_policy_cfg.get(cfg_key))
        return int(cfg_v) if cfg_v is not None else int(default)

    def _resolve_float(cli_val: Any, cfg_key: str, default: float) -> float:
        if cli_val is not None:
            return float(cli_val)
        cfg_v = to_float(long_window_policy_cfg.get(cfg_key))
        return float(cfg_v) if cfg_v is not None else float(default)

    long156_policy = normalize_long156_policy(
        args.long156_policy if args.long156_policy is not None else long_window_policy_cfg.get("run_156_policy", "cadence_only")
    )
    long156_cadence_useful_runs = max(
        1,
        _resolve_int(args.long156_cadence_useful_runs, "run_156_cadence_useful_runs", 4),
    )
    long156_min_w52_spy_compare = _resolve_float(
        args.long156_min_w52_spy_compare,
        "run_156_min_w52_spy_compare",
        0.5,
    )
    long156_min_w52_weeks_traded = _resolve_float(
        args.long156_min_w52_weeks_traded,
        "run_156_min_w52_weeks_traded",
        20.0,
    )
    long156_min_w52_trades = _resolve_float(
        args.long156_min_w52_trades,
        "run_156_min_w52_trades",
        15.0,
    )

    requested_windows = parse_windows(args.evaluation_windows)
    year_validation_window_weeks = max(53, int(args.year_validation_window_weeks))

    # Window constraints:
    # - By default, treat --evaluation-windows as strict allowed windows.
    # - Progressive extension is only allowed when --allow-progressive-windows is set.
    progressive_windows_enabled = bool(getattr(args, "allow_progressive_windows", False))
    if progressive_windows_enabled:
        windows = build_progressive_window_plan(requested_windows, year_validation_window_weeks)
        allowed_windows = list(windows)
    else:
        # Preserve caller order (no auto-extension).
        allowed_windows = []
        seen: set[int] = set()
        for w in requested_windows:
            iw = int(w)
            if iw > 0 and iw not in seen:
                allowed_windows.append(iw)
                seen.add(iw)
        windows = list(allowed_windows)

    standard_windows = [4, 8, 24, 52, 156]
    forbidden_windows = [w for w in standard_windows if int(w) not in {int(x) for x in allowed_windows}]
    exit_ctx["requested_windows"] = [int(w) for w in requested_windows]
    exit_ctx["allowed_windows"] = [int(w) for w in allowed_windows]
    exit_ctx["progressive_windows"] = [int(w) for w in windows]
    exit_ctx["status_hint"] = "running"
    exit_ctx["reason"] = "running"
    useful_runs_since_last_real_156 = count_useful_runs_since_last_real_156(rows, repo)
    run_log(
        "EXECUTOR windows_policy "
        f"requested={requested_windows} allowed={allowed_windows} progressive_enabled={int(progressive_windows_enabled)} progressive_plan={windows} "
        f"validation_phase={validation_phase} "
        f"long156_policy={long156_policy} "
        f"cadence_useful_runs={long156_cadence_useful_runs} "
        f"useful_since_last_real_156={useful_runs_since_last_real_156} "
        f"thresholds(w52_spy_compare>={long156_min_w52_spy_compare},"
        f"w52_weeks_traded>={long156_min_w52_weeks_traded},"
        f"w52_trades>={long156_min_w52_trades})"
    )

    # Persist auditable window execution plan early (even if the run fails mid-way).
    plan_path = run_dir / "window_execution_plan.json"
    window_plan: Dict[str, Any] = {
        "requested_windows": [int(w) for w in requested_windows],
        "allowed_windows": [int(w) for w in allowed_windows],
        "progressive_windows_enabled": bool(progressive_windows_enabled),
        "executed_windows": [],
        "blocked_windows": [],
        "forbidden_windows": [int(w) for w in forbidden_windows],
    }
    write_window_execution_plan(plan_path, window_plan)

    # Incremental executor checkpoint (survives long 52w runs even if process is killed externally).
    executor_partial_path = run_dir / "executor_output.partial.json"
    executor_partial: Dict[str, Any] = {
        "status": "running",
        "run_id": run_id,
        "executed_windows": [],
        "windows": {},
        "last_completed_window": None,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "partial": True,
    }
    try:
        save_json_atomic(executor_partial_path, executor_partial)
    except Exception:
        pass
    queue = load_json(queue_path, [])
    if not isinstance(queue, list):
        queue = []
    rs_branch = (research_state.get("branch_state", {}) if isinstance(research_state, dict) else {}) or {}
    rs_learning = (research_state.get("latest_learning_summary", {}) if isinstance(research_state, dict) else {}) or {}
    rs_branch_for_proposal = dict(rs_branch)
    rs_branch_for_proposal["recommended_change_directions"] = sanitize_text_list(
        rs_learning.get("recommended_change_directions", []) or []
    )
    rs_scores = (research_state.get("latest_scores", {}) if isinstance(research_state, dict) else {}) or {}
    existing_hashes = load_existing_config_hashes(runs_root, tracked_keys)
    proposal = select_analyst_proposal(
        queue,
        parent_cfg,
        latest_valid,
        windows,
        rows=rows,
        branch_anchor=branch_anchor,
        branch_state=rs_branch_for_proposal,
        existing_config_hashes=existing_hashes,
        tracked_keys=tracked_keys,
        parameter_effect_memory=parameter_effect_memory,
        subspace_cooldowns=subspace_cooldowns,
        current_iteration=parse_run_id(run_id),
    )
    proposal = ensure_analyst_output_contract(proposal, windows)
    afu = proposal.get("auditor_feedback_used", {}) if isinstance(proposal.get("auditor_feedback_used"), dict) else {}
    afu_default = {
        "process_reliability_score": rs_scores.get("process_reliability_score"),
        "analyst_quality_score": rs_scores.get("analyst_quality_score"),
        "coordinator_quality_score": rs_scores.get("coordinator_quality_score"),
        "research_effectiveness_score": rs_scores.get("research_effectiveness_score"),
        "branch_health": clean_text(rs_branch.get("branch_health", "")),
        "stagnation_risk": clean_text(rs_branch.get("stagnation_risk", "")),
        "main_friction": clean_text(rs_branch.get("main_friction", "")),
        "recommended_next_action": clean_text(rs_branch.get("recommended_next_action", "")),
    }
    for k, v in afu_default.items():
        if k not in afu or (afu.get(k) in {None, ""}):
            afu[k] = v
    proposal["auditor_feedback_used"] = afu
    proposal["timestamp"] = datetime.now().isoformat(timespec="seconds")
    proposal["parent_run_id"] = parent_run_id
    proposal["parent_script"] = str(parent_script)
    proposal["branch_anchor_context"] = branch_anchor
    proposal_validation = validate_main_change_materiality(proposal)
    proposal["proposal_validation"] = proposal_validation
    if bool(proposal_validation.get("invalid_no_op", False)):
        proposal["status"] = "no_material_candidate_found"
        invalid_msg = (
            "Proposal invalido por cambio nulo normalizado: "
            f"{proposal_validation.get('main_parameter','')} "
            f"{proposal_validation.get('normalized_from_value','')}->"
            f"{proposal_validation.get('normalized_to_value','')}"
        )
        diagnosis = clean_text(proposal.get("diagnosis", ""))
        if diagnosis:
            proposal["diagnosis"] = f"{diagnosis} | {invalid_msg}"
        else:
            proposal["diagnosis"] = invalid_msg
        proposal["hypothesis"] = invalid_msg
    proposal = ensure_analyst_output_contract(proposal, windows)
    save_json(run_dir / "analyst_output.json", proposal)
    candidate_generation_diagnostic = proposal.get("candidate_generation_diagnostic_output")
    if isinstance(candidate_generation_diagnostic, dict) and candidate_generation_diagnostic:
        save_json(run_dir / "candidate_generation_diagnostic_output.json", candidate_generation_diagnostic)
    main_ch = proposal.get("main_change") or {}
    dep_ch = proposal.get("dependent_change") or {}
    run_log(
        "ANALYST proposal "
        f"status={proposal.get('status','proposal_ready')} "
        f"source={proposal.get('source','')} queue_test_id={proposal.get('queue_test_id','')} "
        f"main={main_ch.get('parameter')}:{main_ch.get('from_value')}->{main_ch.get('to_value')} "
        f"dependent={dep_ch.get('parameter','')}"
    )
    if str(proposal.get("status", "")).strip().lower() == "no_material_candidate_found":
        reason = clean_text(proposal.get("hypothesis", "")) or "No se encontro propuesta material valida."
        no_material_effective_change_check = {
            "no_material_candidate_found": True,
            "proposal_invalid": bool(proposal_validation.get("invalid_no_op", False)),
            "no_op_detected": True,
            "active_logic_changed": False,
        }
        no_material_multi_year_validation = {
            "status": "not_run",
            "reason": "no_material_candidate_found",
            "requested_windows": [int(w) for w in requested_windows],
            "allowed_windows": [int(w) for w in allowed_windows],
        }
        executor_output = {
            "role": "executor",
            "status": "blocked_no_material_candidate",
            "run_id": run_id,
            "script_executed": "",
            "command": "",
            "windows_policy": {
                "requested": [int(w) for w in requested_windows],
                "allowed": [int(w) for w in allowed_windows],
                "progressive_plan": [int(w) for w in windows],
                "policy": "skipped_before_execution_no_material_candidate",
                "strict_progressive_windows": True,
            },
            "windows": {},
            "core_metrics": {},
            "validation_depth_summary": no_material_multi_year_validation,
            "errors": [reason],
        }
        save_json(run_dir / "executor_output.json", executor_output)
        learning_feedback = {
            "hypothesis_discarded": [reason],
            "worsened_dimensions": [],
            "next_change_type_recommendation": ["controlled_exploration", "gate_reactivation", "rank_adjustment"],
            "notes": ["Se agotaron capa 1 y capa 2 del fallback sin candidato material válido."],
        }
        coordinator_output = {
            "role": "coordinator",
            "status": "blocked_no_material_candidate",
            "decision_type": "rejected",
            "gate_decision": "blocked_no_material_candidate",
            "accepted_for_followup": False,
            "promoted_to_baseline": False,
            "reasons": [reason],
            "material_change_detected": False,
            "materiality": {
                "material_change_detected": False,
                "no_op_detected": True,
                "material_parameters": [],
                "details": [],
            },
            "proposal_validation": proposal_validation,
            "transition_classification": [],
            "promotion_reason": "",
            "promotion_blockers": ["no_material_candidate_found"],
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "validation_phase": validation_phase,
            "next_validation_phase": validation_phase,
            "multi_year_validation": no_material_multi_year_validation,
            "effective_change_check": no_material_effective_change_check,
            "fallback_diagnosis": proposal.get("fallback_diagnosis", {}),
            "fallback_candidate_pool_considered": proposal.get("fallback_candidate_pool_considered", []),
            "fallback_selected_reason": proposal.get("fallback_selected_reason", ""),
            "learning_feedback": learning_feedback,
        }
        coordinator_output = finalize_coordinator_output(
            coordinator_output=coordinator_output,
            proposal=proposal,
            executor_output=executor_output,
            compare_obj={},
            learning_feedback=learning_feedback,
        )
        save_json(run_dir / "coordinator_output.json", coordinator_output)
        manifest = {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "baseline_reference": baseline.get("baseline_reference", {}),
            "main_change": proposal.get("main_change"),
            "dependent_change": proposal.get("dependent_change"),
            "expected_effect": proposal.get("expected_effect", ""),
            "gate_decision": "blocked_no_material_candidate",
            "material_change_detected": False,
            "proposal_validation": proposal_validation,
            "transition_classification": [],
            "decision_type": "rejected",
            "accepted_for_followup": False,
            "promoted_to_baseline": False,
            "promotion_reason": "",
            "promotion_blockers": ["no_material_candidate_found"],
            "validation_phase": validation_phase,
            "next_validation_phase": validation_phase,
            "multi_year_validation": no_material_multi_year_validation,
            "effective_change_check": no_material_effective_change_check,
            "fallback_diagnosis": proposal.get("fallback_diagnosis", {}),
            "fallback_candidate_pool_considered": proposal.get("fallback_candidate_pool_considered", []),
            "fallback_selected_reason": proposal.get("fallback_selected_reason", ""),
            "learning_feedback": learning_feedback,
            "status": "blocked_no_material_candidate",
            "auditor_v2_evaluation": coordinator_output.get("auditor_v2_evaluation", {}),
        }
        save_json(run_dir / "experiment_manifest.json", manifest)
        append_experiment_row(
            exp_log_path,
            {
                "run_id": run_id,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "parent_run_id": parent_run_id,
                "parent_script": str(parent_script),
                "baseline_reference": clean_text((baseline.get("baseline_reference") or {}).get("run_id")),
                "queue_test_id": clean_text(proposal.get("queue_test_id")),
                "main_parameter": clean_text((proposal.get("main_change") or {}).get("parameter")),
                "main_from": clean_text((proposal.get("main_change") or {}).get("from_value")),
                "main_to": clean_text((proposal.get("main_change") or {}).get("to_value")),
                "dependent_parameter": clean_text((proposal.get("dependent_change") or {}).get("parameter")),
                "dependent_from": clean_text((proposal.get("dependent_change") or {}).get("from_value")),
                "dependent_to": clean_text((proposal.get("dependent_change") or {}).get("to_value")),
                "expected_effect": clean_text(proposal.get("expected_effect")),
                "status": "blocked_no_material_candidate",
                "preflight_pass": "false",
                "no_op_detected": "true",
                "effective_change_check": clean_text(json.dumps(manifest.get("effective_change_check", {}), ensure_ascii=False)),
                "accepted_or_rejected": "rejected",
                "notes": reason,
                "run_dir": str(run_dir),
            },
        )
        persist_governance_state(
            baseline_path=baseline_path,
            baseline=baseline,
            research_state_path=research_state_path,
            research_state=research_state,
            run_id=run_id,
            decision_type="rejected",
            coordinator_status="blocked_no_material_candidate",
            executor_output=executor_output,
            coordinator_output=coordinator_output,
            queue_id="",
            proposal=proposal,
            recent_rows=rows,
        )
        save_json_atomic(
            run_dir / "run_status.json",
            {
                "status": "blocked_no_material_candidate",
                "reason": reason,
                "completed_windows": [],
                "missing_artifacts": [],
                "finalized": True,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        save_json_atomic(
            run_dir / "recovery_status.json",
            {
                "status": "blocked_no_material_candidate_complete",
                "reason": reason,
                "safe_for_strategy_analysis": False,
                "safe_for_process_analysis": True,
                "do_not_use_as_parent": True,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        run_log(f"COORDINATOR blocked_no_material_candidate: {reason}")
        exit_ctx["status_hint"] = "blocked_no_material_candidate"
        exit_ctx["reason"] = clean_text(reason)
        return 0

    materiality = analyze_proposal_materiality(proposal, parent_cfg)
    transition_eval = classify_param_transition(rows, proposal, parent_cfg)
    save_json(run_dir / "proposal_materiality.json", materiality)
    save_json(run_dir / "proposal_transition_classification.json", transition_eval)
    materiality_summary = "; ".join(
        [
            f"{d.get('parameter')}:{d.get('normalized_from_value')}->{d.get('normalized_to_value')} material={d.get('material_change_detected')}"
            for d in (materiality.get("details") or [])
        ]
    )
    run_log(
        "COORDINATOR materiality "
        f"material_change_detected={materiality.get('material_change_detected')} "
        f"material_parameters={materiality.get('material_parameters', [])}"
    )
    if materiality_summary:
        run_log(f"COORDINATOR normalized_values {materiality_summary}")
    transition_summary = "; ".join(
        [
            (
                f"{d.get('parameter')}:{d.get('normalized_from_value')}->{d.get('normalized_to_value')} "
                f"class={d.get('classification')}"
            )
            for d in (transition_eval.get("details") or [])
        ]
    )
    if transition_summary:
        run_log(f"COORDINATOR transition_classification {transition_summary}")
    if not bool(materiality.get("material_change_detected", False)):
        coordinator_output = {
            "role": "coordinator",
            "status": "blocked_no_op",
            "decision_type": "rejected",
            "gate_decision": "blocked_no_op",
            "reasons": ["El cambio propuesto no altera la logica operativa (no-op normalizado)."],
            "material_change_detected": False,
            "materiality": materiality,
            "transition_classification": transition_eval.get("details", []),
            "promotion_reason": "",
            "promotion_blockers": ["blocked_no_op"],
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
        }
        coordinator_output = finalize_coordinator_output(
            coordinator_output=coordinator_output,
            proposal=proposal,
            executor_output={},
            compare_obj={},
            learning_feedback={},
        )
        save_json(run_dir / "coordinator_output.json", coordinator_output)
        manifest = {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "baseline_reference": baseline.get("baseline_reference", {}),
            "main_change": proposal.get("main_change"),
            "dependent_change": proposal.get("dependent_change"),
            "expected_effect": proposal.get("expected_effect", ""),
            "gate_decision": "blocked_no_op",
            "material_change_detected": False,
            "materiality": materiality,
            "transition_classification": transition_eval.get("details", []),
            "effective_change_check": {
                "no_op_detected": True,
                "material_change_detected": False,
                "normalized_changes": materiality.get("details", []),
            },
            "decision_type": "rejected",
            "promotion_reason": "",
            "promotion_blockers": ["blocked_no_op"],
            "status": "blocked_no_op",
            "auditor_v2_evaluation": coordinator_output.get("auditor_v2_evaluation", {}),
        }
        save_json(run_dir / "experiment_manifest.json", manifest)
        append_experiment_row(
            exp_log_path,
            {
                "run_id": run_id,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "parent_run_id": parent_run_id,
                "parent_script": str(parent_script),
                "baseline_reference": clean_text((baseline.get("baseline_reference") or {}).get("run_id")),
                "queue_test_id": clean_text(proposal.get("queue_test_id")),
                "main_parameter": clean_text((proposal.get("main_change") or {}).get("parameter")),
                "main_from": clean_text((proposal.get("main_change") or {}).get("from_value")),
                "main_to": clean_text((proposal.get("main_change") or {}).get("to_value")),
                "dependent_parameter": clean_text((proposal.get("dependent_change") or {}).get("parameter")),
                "dependent_from": clean_text((proposal.get("dependent_change") or {}).get("from_value")),
                "dependent_to": clean_text((proposal.get("dependent_change") or {}).get("to_value")),
                "expected_effect": clean_text(proposal.get("expected_effect")),
                "status": "blocked_no_op",
                "preflight_pass": "false",
                "no_op_detected": "true",
                "effective_change_check": clean_text(
                    json.dumps(
                        {
                            "no_op_detected": True,
                            "material_change_detected": False,
                            "normalized_changes": materiality.get("details", []),
                        },
                        ensure_ascii=False,
                    )
                ),
                "accepted_or_rejected": "rejected",
                "notes": "No-op normalizado detectado antes de zig-zag.",
                "run_dir": str(run_dir),
            },
        )
        persist_governance_state(
            baseline_path=baseline_path,
            baseline=baseline,
            research_state_path=research_state_path,
            research_state=research_state,
            run_id=run_id,
            decision_type="rejected",
            coordinator_status="blocked_no_op",
            executor_output={},
            coordinator_output=coordinator_output,
            queue_id="",
            proposal=proposal,
            recent_rows=rows,
        )
        run_log("COORDINATOR blocked_no_op: cambio nulo detectado antes de zig-zag.")
        exit_ctx["status_hint"] = "blocked_no_op"
        exit_ctx["reason"] = "blocked_no_op_before_zigzag"
        return 0

    anchor_eval = evaluate_branch_anchor_conflict(proposal, branch_anchor)
    if bool(anchor_eval.get("blocked", False)):
        anchor_reasons = [clean_text(x) for x in (anchor_eval.get("reasons") or []) if clean_text(x)]
        coordinator_output = {
            "role": "coordinator",
            "status": "blocked_branch_anchor",
            "gate_decision": "blocked_branch_anchor",
            "decision_type": "rejected",
            "accepted_for_followup": False,
            "promoted_to_baseline": False,
            "reasons": anchor_reasons or ["Propuesta bloqueada por branch_anchor activo."],
            "material_change_detected": bool(materiality.get("material_change_detected", False)),
            "materiality": materiality,
            "transition_classification": transition_eval.get("details", []),
            "promotion_reason": "",
            "promotion_blockers": ["blocked_branch_anchor"],
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "branch_anchor": branch_anchor,
            "branch_anchor_evaluation": anchor_eval,
        }
        coordinator_output = finalize_coordinator_output(
            coordinator_output=coordinator_output,
            proposal=proposal,
            executor_output={},
            compare_obj={"branch_anchor": branch_anchor},
            learning_feedback={},
        )
        save_json(run_dir / "coordinator_output.json", coordinator_output)
        manifest = {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "baseline_reference": baseline.get("baseline_reference", {}),
            "main_change": proposal.get("main_change"),
            "dependent_change": proposal.get("dependent_change"),
            "expected_effect": proposal.get("expected_effect", ""),
            "gate_decision": "blocked_branch_anchor",
            "material_change_detected": bool(materiality.get("material_change_detected", False)),
            "materiality": materiality,
            "transition_classification": transition_eval.get("details", []),
            "effective_change_check": {
                "blocked_branch_anchor": True,
                "branch_anchor_reasons": anchor_reasons,
                "branch_anchor_parameter": clean_text(branch_anchor.get("parameter", "")),
                "branch_anchor_value": branch_anchor.get("value"),
            },
            "decision_type": "rejected",
            "accepted_for_followup": False,
            "promoted_to_baseline": False,
            "promotion_reason": "",
            "promotion_blockers": ["blocked_branch_anchor"],
            "status": "blocked_branch_anchor",
            "branch_anchor": branch_anchor,
            "branch_anchor_evaluation": anchor_eval,
            "auditor_v2_evaluation": coordinator_output.get("auditor_v2_evaluation", {}),
        }
        save_json(run_dir / "experiment_manifest.json", manifest)
        append_experiment_row(
            exp_log_path,
            {
                "run_id": run_id,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "parent_run_id": parent_run_id,
                "parent_script": str(parent_script),
                "baseline_reference": clean_text((baseline.get("baseline_reference") or {}).get("run_id")),
                "queue_test_id": clean_text(proposal.get("queue_test_id")),
                "main_parameter": clean_text((proposal.get("main_change") or {}).get("parameter")),
                "main_from": clean_text((proposal.get("main_change") or {}).get("from_value")),
                "main_to": clean_text((proposal.get("main_change") or {}).get("to_value")),
                "dependent_parameter": clean_text((proposal.get("dependent_change") or {}).get("parameter")),
                "dependent_from": clean_text((proposal.get("dependent_change") or {}).get("from_value")),
                "dependent_to": clean_text((proposal.get("dependent_change") or {}).get("to_value")),
                "expected_effect": clean_text(proposal.get("expected_effect")),
                "status": "blocked_branch_anchor",
                "preflight_pass": "false",
                "no_op_detected": "false",
                "effective_change_check": clean_text(json.dumps(manifest.get("effective_change_check", {}), ensure_ascii=False)),
                "accepted_or_rejected": "rejected",
                "notes": clean_text("; ".join(anchor_reasons)),
                "run_dir": str(run_dir),
            },
        )
        persist_governance_state(
            baseline_path=baseline_path,
            baseline=baseline,
            research_state_path=research_state_path,
            research_state=research_state,
            run_id=run_id,
            decision_type="rejected",
            coordinator_status="blocked_branch_anchor",
            executor_output={},
            coordinator_output=coordinator_output,
            queue_id="",
            proposal=proposal,
            recent_rows=rows,
        )
        run_log("COORDINATOR blocked_branch_anchor: propuesta rechazada por bloqueo temporal de parametro anclado.")
        exit_ctx["status_hint"] = "blocked_branch_anchor"
        exit_ctx["reason"] = clean_text("; ".join(anchor_reasons))
        return 0

    proposal_source = clean_text(proposal.get("proposal_source", "")) or clean_text(proposal.get("source", ""))
    next_change_consumed = bool(proposal.get("next_change_consumed", False))
    next_change_zigzag_override = bool(proposal.get("next_change_zigzag_override", False))
    next_change_zigzag_override_allowed = is_next_change_zigzag_override_allowed(proposal)
    original_rejection_reason = clean_text(proposal.get("original_rejection_reason", "")) or clean_text(
        proposal.get("next_change_rejected_reason", "")
    )
    main_change_obj = proposal.get("main_change") or {}
    main_parameter = clean_text(main_change_obj.get("parameter", ""))
    main_from = normalize_scalar(main_change_obj.get("from_value"))
    main_to = normalize_scalar(main_change_obj.get("to_value"))
    transition_class = clean_text(transition_eval.get("details", [{}])[0].get("classification", "")) if transition_eval.get("details") else ""
    revert_allowed = is_explicit_revert_allowed(proposal, rows) or next_change_zigzag_override_allowed
    duplicate_transition_details = [
        d for d in (transition_eval.get("details", []) or [])
        if clean_text(d.get("classification", "")) == "duplicate_recent_proposal"
    ]
    if duplicate_transition_details:
        duplicate_reasons = [
            f"{clean_text(d.get('parameter'))}:{clean_text(d.get('reason'))}"
            for d in duplicate_transition_details
        ]
        coordinator_output = {
            "role": "coordinator",
            "status": "blocked_duplicate",
            "gate_decision": "blocked_duplicate",
            "decision_type": "rejected",
            "accepted_for_followup": False,
            "promoted_to_baseline": False,
            "reasons": duplicate_reasons or ["Propuesta duplicada reciente."],
            "material_change_detected": True,
            "materiality": materiality,
            "transition_classification": transition_eval.get("details", []),
            "promotion_reason": "",
            "promotion_blockers": ["blocked_duplicate"],
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
        }
        coordinator_output = finalize_coordinator_output(
            coordinator_output=coordinator_output,
            proposal=proposal,
            executor_output={},
            compare_obj={},
            learning_feedback={},
        )
        save_json(run_dir / "coordinator_output.json", coordinator_output)
        manifest = {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "baseline_reference": baseline.get("baseline_reference", {}),
            "main_change": proposal.get("main_change"),
            "dependent_change": proposal.get("dependent_change"),
            "expected_effect": proposal.get("expected_effect", ""),
            "gate_decision": "blocked_duplicate",
            "material_change_detected": True,
            "materiality": materiality,
            "transition_classification": transition_eval.get("details", []),
            "effective_change_check": {
                "blocked_duplicate_transition": True,
                "duplicate_reasons": duplicate_reasons,
            },
            "decision_type": "rejected",
            "accepted_for_followup": False,
            "promoted_to_baseline": False,
            "promotion_reason": "",
            "promotion_blockers": ["blocked_duplicate"],
            "status": "blocked_duplicate",
            "auditor_v2_evaluation": coordinator_output.get("auditor_v2_evaluation", {}),
        }
        save_json(run_dir / "experiment_manifest.json", manifest)
        append_experiment_row(
            exp_log_path,
            {
                "run_id": run_id,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "parent_run_id": parent_run_id,
                "parent_script": str(parent_script),
                "baseline_reference": clean_text((baseline.get("baseline_reference") or {}).get("run_id")),
                "queue_test_id": clean_text(proposal.get("queue_test_id")),
                "main_parameter": clean_text((proposal.get("main_change") or {}).get("parameter")),
                "main_from": clean_text((proposal.get("main_change") or {}).get("from_value")),
                "main_to": clean_text((proposal.get("main_change") or {}).get("to_value")),
                "dependent_parameter": clean_text((proposal.get("dependent_change") or {}).get("parameter")),
                "dependent_from": clean_text((proposal.get("dependent_change") or {}).get("from_value")),
                "dependent_to": clean_text((proposal.get("dependent_change") or {}).get("to_value")),
                "expected_effect": clean_text(proposal.get("expected_effect")),
                "status": "blocked_duplicate",
                "preflight_pass": "false",
                "no_op_detected": "false",
                "effective_change_check": clean_text(json.dumps(manifest.get("effective_change_check", {}), ensure_ascii=False)),
                "accepted_or_rejected": "rejected",
                "notes": clean_text("; ".join(duplicate_reasons)),
                "run_dir": str(run_dir),
            },
        )
        persist_governance_state(
            baseline_path=baseline_path,
            baseline=baseline,
            research_state_path=research_state_path,
            research_state=research_state,
            run_id=run_id,
            decision_type="rejected",
            coordinator_status="blocked_duplicate",
            executor_output={},
            coordinator_output=coordinator_output,
            queue_id="",
            proposal=proposal,
            recent_rows=rows,
        )
        run_log("COORDINATOR blocked_duplicate: duplicate_recent_proposal detectado en transicion.")
        exit_ctx["status_hint"] = "blocked_duplicate"
        exit_ctx["reason"] = "blocked_duplicate_recent_proposal"
        return 0

    transition_blocks = transition_eval.get("block_reasons", [])
    has_zigzag_block = bool(transition_eval.get("blocked", False))
    if has_zigzag_block and not revert_allowed:
        run_log(
            "COORDINATOR blocked_zigzag precheck "
            f"proposal_source={proposal_source} "
            f"next_change_consumed={next_change_consumed} "
            f"next_change_zigzag_override={next_change_zigzag_override} "
            f"next_change_zigzag_override_allowed={next_change_zigzag_override_allowed} "
            f"original_rejection_reason={original_rejection_reason} "
            f"transition_class={transition_class} "
            f"parameter={main_parameter} from={main_from} to={main_to} "
            f"hard_block_bypassed=False"
        )
        coordinator_output = {
            "role": "coordinator",
            "status": "blocked_zigzag",
            "gate_decision": "blocked_zigzag",
            "decision_type": "rejected",
            "reasons": [f"Bloqueado por transicion: {transition_blocks}"],
            "material_change_detected": True,
            "materiality": materiality,
            "transition_classification": transition_eval.get("details", []),
            "promotion_reason": "",
            "promotion_blockers": transition_blocks,
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "changed_parameters": list(materiality.get("material_parameters", [])),
        }
        coordinator_output = finalize_coordinator_output(
            coordinator_output=coordinator_output,
            proposal=proposal,
            executor_output={},
            compare_obj={},
            learning_feedback={},
        )
        save_json(run_dir / "coordinator_output.json", coordinator_output)
        manifest = {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "baseline_reference": baseline.get("baseline_reference", {}),
            "main_change": proposal.get("main_change"),
            "dependent_change": proposal.get("dependent_change"),
            "expected_effect": proposal.get("expected_effect", ""),
            "gate_decision": "blocked_zigzag",
            "material_change_detected": True,
            "materiality": materiality,
            "transition_classification": transition_eval.get("details", []),
            "effective_change_check": {
                "blocked_by_zigzag": True,
                "material_change_detected": True,
                "normalized_changes": materiality.get("details", []),
                "transition_block_reasons": transition_blocks,
            },
            "decision_type": "rejected",
            "promotion_reason": "",
            "promotion_blockers": transition_blocks,
            "status": "blocked_zigzag",
            "auditor_v2_evaluation": coordinator_output.get("auditor_v2_evaluation", {}),
        }
        save_json(run_dir / "experiment_manifest.json", manifest)
        append_experiment_row(
            exp_log_path,
            {
                "run_id": run_id,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "parent_run_id": parent_run_id,
                "parent_script": str(parent_script),
                "baseline_reference": clean_text((baseline.get("baseline_reference") or {}).get("run_id")),
                "queue_test_id": clean_text(proposal.get("queue_test_id")),
                "main_parameter": clean_text((proposal.get("main_change") or {}).get("parameter")),
                "main_from": clean_text((proposal.get("main_change") or {}).get("from_value")),
                "main_to": clean_text((proposal.get("main_change") or {}).get("to_value")),
                "dependent_parameter": clean_text((proposal.get("dependent_change") or {}).get("parameter")),
                "dependent_from": clean_text((proposal.get("dependent_change") or {}).get("from_value")),
                "dependent_to": clean_text((proposal.get("dependent_change") or {}).get("to_value")),
                "expected_effect": clean_text(proposal.get("expected_effect")),
                "status": "blocked_zigzag",
                "preflight_pass": "false",
                "no_op_detected": "false",
                "effective_change_check": clean_text(
                    json.dumps(
                        {
                            "blocked_by_zigzag": True,
                            "material_change_detected": True,
                            "normalized_changes": materiality.get("details", []),
                        },
                        ensure_ascii=False,
                    )
                ),
                "accepted_or_rejected": "rejected",
                "notes": clean_text("; ".join(coordinator_output.get("reasons", []))),
                "run_dir": str(run_dir),
            },
        )
        persist_governance_state(
            baseline_path=baseline_path,
            baseline=baseline,
            research_state_path=research_state_path,
            research_state=research_state,
            run_id=run_id,
            decision_type="rejected",
            coordinator_status="blocked_zigzag",
            executor_output={},
            coordinator_output=coordinator_output,
            queue_id="",
            proposal=proposal,
            recent_rows=rows,
        )
        run_log("COORDINATOR blocked_zigzag: transicion clasificada como true_zigzag_reversal.")
        exit_ctx["status_hint"] = "blocked_zigzag"
        exit_ctx["reason"] = "blocked_true_zigzag_reversal"
        return 0
    if has_zigzag_block and revert_allowed:
        if bool(proposal.get("next_change_zigzag_override", False)):
            run_log(
                "COORDINATOR zigzag_override_allowed "
                f"parameter={main_parameter} from={main_from} to={main_to} "
                f"reason={clean_text(proposal.get('next_change_zigzag_override_reason', '')) or clean_text(proposal.get('override_reason', '')) or clean_text(proposal.get('evidence_reason', ''))}"
            )
            run_log(
                "COORDINATOR zigzag override: next_change override activo con justificacion valida."
            )
        else:
            run_log("COORDINATOR zigzag override: revert_explicit=true con justificacion valida.")
    run_log("COORDINATOR continue: cambio material valido y sin conflicto zig-zag bloqueante.")

    candidate_cfg = dict(proposal.get("proposal_config") or parent_cfg)

    existing_hashes = load_existing_config_hashes(runs_root, tracked_keys)
    h = config_hash(candidate_cfg, tracked_keys)
    if h in existing_hashes:
        reason = f"Configuracion ya probada en {existing_hashes[h]}"
        coordinator_output = {
            "role": "coordinator",
            "status": "blocked_duplicate",
            "decision_type": "rejected",
            "gate_decision": "blocked_duplicate",
            "accepted_for_followup": False,
            "promoted_to_baseline": False,
            "reasons": [reason],
            "material_change_detected": bool(materiality.get("material_change_detected", False)),
            "materiality": materiality,
            "transition_classification": transition_eval.get("details", []),
            "promotion_reason": "",
            "promotion_blockers": ["blocked_duplicate"],
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "fallback_diagnosis": proposal.get("fallback_diagnosis", {}),
            "fallback_candidate_pool_considered": proposal.get("fallback_candidate_pool_considered", []),
            "fallback_selected_reason": proposal.get("fallback_selected_reason", ""),
        }
        coordinator_output = finalize_coordinator_output(
            coordinator_output=coordinator_output,
            proposal=proposal,
            executor_output={},
            compare_obj={},
            learning_feedback={},
        )
        save_json(run_dir / "coordinator_output.json", coordinator_output)
        manifest = {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "baseline_reference": baseline.get("baseline_reference", {}),
            "main_change": proposal.get("main_change"),
            "dependent_change": proposal.get("dependent_change"),
            "expected_effect": proposal.get("expected_effect", ""),
            "gate_decision": "blocked_duplicate",
            "material_change_detected": bool(materiality.get("material_change_detected", False)),
            "materiality": materiality,
            "transition_classification": transition_eval.get("details", []),
            "decision_type": "rejected",
            "accepted_for_followup": False,
            "promoted_to_baseline": False,
            "promotion_reason": "",
            "promotion_blockers": ["blocked_duplicate"],
            "effective_change_check": {"blocked_duplicate": True},
            "fallback_diagnosis": proposal.get("fallback_diagnosis", {}),
            "fallback_candidate_pool_considered": proposal.get("fallback_candidate_pool_considered", []),
            "fallback_selected_reason": proposal.get("fallback_selected_reason", ""),
            "status": "blocked_duplicate",
            "auditor_v2_evaluation": coordinator_output.get("auditor_v2_evaluation", {}),
        }
        save_json(run_dir / "experiment_manifest.json", manifest)
        append_experiment_row(
            exp_log_path,
            {
                "run_id": run_id,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "parent_run_id": parent_run_id,
                "parent_script": str(parent_script),
                "baseline_reference": clean_text((baseline.get("baseline_reference") or {}).get("run_id")),
                "queue_test_id": clean_text(proposal.get("queue_test_id")),
                "main_parameter": clean_text((proposal.get("main_change") or {}).get("parameter")),
                "main_from": clean_text((proposal.get("main_change") or {}).get("from_value")),
                "main_to": clean_text((proposal.get("main_change") or {}).get("to_value")),
                "dependent_parameter": clean_text((proposal.get("dependent_change") or {}).get("parameter")),
                "dependent_from": clean_text((proposal.get("dependent_change") or {}).get("from_value")),
                "dependent_to": clean_text((proposal.get("dependent_change") or {}).get("to_value")),
                "expected_effect": clean_text(proposal.get("expected_effect")),
                "status": "blocked_duplicate",
                "preflight_pass": "false",
                "no_op_detected": "true",
                "accepted_or_rejected": "rejected",
                "notes": clean_text(reason),
                "run_dir": str(run_dir),
            },
        )
        persist_governance_state(
            baseline_path=baseline_path,
            baseline=baseline,
            research_state_path=research_state_path,
            research_state=research_state,
            run_id=run_id,
            decision_type="rejected",
            coordinator_status="blocked_duplicate",
            executor_output={},
            coordinator_output=coordinator_output,
            queue_id="",
            proposal=proposal,
            recent_rows=rows,
        )
        run_log(f"COORDINATOR blocked_duplicate: {reason}")
        exit_ctx["status_hint"] = "blocked_duplicate"
        exit_ctx["reason"] = clean_text(reason)
        return 0

    save_json(run_dir / "parent_config.json", parent_cfg)
    save_json(run_dir / "candidate_config.json", candidate_cfg)
    change_set = {
        "main_change": proposal.get("main_change"),
        "dependent_change": proposal.get("dependent_change") or {},
    }
    save_json(run_dir / "change_set.json", change_set)

    preflight_out = run_preflight(
        repo=repo,
        dependencies_path=dep_path,
        candidate_cfg_path=run_dir / "candidate_config.json",
        parent_cfg_path=run_dir / "parent_config.json",
        change_set_path=run_dir / "change_set.json",
        output_path=run_dir / "preflight_output.json",
    )
    save_json(run_dir / "preflight_output.json", preflight_out)
    run_log(
        "PREFLIGHT result "
        f"pass={bool(preflight_out.get('pass', False))} "
        f"no_op={((preflight_out.get('effective_change_check') or {}).get('no_op_detected', False))}"
    )
    if not bool(preflight_out.get("pass", False)):
        reasons = preflight_out.get("blocked", []) or ["Preflight rechazado."]
        coordinator_output = {
            "role": "coordinator",
            "status": "blocked_preflight",
            "decision_type": "rejected",
            "gate_decision": "continue",
            "reasons": reasons,
            "material_change_detected": bool(materiality.get("material_change_detected", False)),
            "materiality": materiality,
            "transition_classification": transition_eval.get("details", []),
            "promotion_reason": "",
            "promotion_blockers": ["blocked_preflight"],
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "fallback_diagnosis": proposal.get("fallback_diagnosis", {}),
            "fallback_candidate_pool_considered": proposal.get("fallback_candidate_pool_considered", []),
            "fallback_selected_reason": proposal.get("fallback_selected_reason", ""),
        }
        coordinator_output = finalize_coordinator_output(
            coordinator_output=coordinator_output,
            proposal=proposal,
            executor_output={},
            compare_obj={},
            learning_feedback={},
        )
        save_json(run_dir / "coordinator_output.json", coordinator_output)
        manifest = {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "baseline_reference": baseline.get("baseline_reference", {}),
            "main_change": proposal.get("main_change"),
            "dependent_change": proposal.get("dependent_change"),
            "expected_effect": proposal.get("expected_effect", ""),
            "gate_decision": "continue",
            "material_change_detected": bool(materiality.get("material_change_detected", False)),
            "materiality": materiality,
            "transition_classification": transition_eval.get("details", []),
            "decision_type": "rejected",
            "promotion_reason": "",
            "promotion_blockers": ["blocked_preflight"],
            "effective_change_check": preflight_out.get("effective_change_check", {}),
            "fallback_diagnosis": proposal.get("fallback_diagnosis", {}),
            "fallback_candidate_pool_considered": proposal.get("fallback_candidate_pool_considered", []),
            "fallback_selected_reason": proposal.get("fallback_selected_reason", ""),
            "status": "blocked_preflight",
            "auditor_v2_evaluation": coordinator_output.get("auditor_v2_evaluation", {}),
        }
        save_json(run_dir / "experiment_manifest.json", manifest)
        append_experiment_row(
            exp_log_path,
            {
                "run_id": run_id,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "parent_run_id": parent_run_id,
                "parent_script": str(parent_script),
                "baseline_reference": clean_text((baseline.get("baseline_reference") or {}).get("run_id")),
                "queue_test_id": clean_text(proposal.get("queue_test_id")),
                "main_parameter": clean_text((proposal.get("main_change") or {}).get("parameter")),
                "main_from": clean_text((proposal.get("main_change") or {}).get("from_value")),
                "main_to": clean_text((proposal.get("main_change") or {}).get("to_value")),
                "dependent_parameter": clean_text((proposal.get("dependent_change") or {}).get("parameter")),
                "dependent_from": clean_text((proposal.get("dependent_change") or {}).get("from_value")),
                "dependent_to": clean_text((proposal.get("dependent_change") or {}).get("to_value")),
                "expected_effect": clean_text(proposal.get("expected_effect")),
                "status": "blocked_preflight",
                "preflight_pass": "false",
                "no_op_detected": clean_text((preflight_out.get("effective_change_check") or {}).get("no_op_detected", False)),
                "effective_change_check": clean_text(json.dumps(preflight_out.get("effective_change_check", {}), ensure_ascii=False)),
                "accepted_or_rejected": "rejected",
                "notes": clean_text("; ".join(reasons)),
                "run_dir": str(run_dir),
            },
        )
        persist_governance_state(
            baseline_path=baseline_path,
            baseline=baseline,
            research_state_path=research_state_path,
            research_state=research_state,
            run_id=run_id,
            decision_type="rejected",
            coordinator_status="blocked_preflight",
            executor_output={},
            coordinator_output=coordinator_output,
            queue_id="",
            proposal=proposal,
            recent_rows=rows,
        )
        run_log("COORDINATOR blocked_preflight: preflight rechazo la corrida.")
        exit_ctx["status_hint"] = "blocked_preflight"
        exit_ctx["reason"] = clean_text("; ".join(reasons))
        try:
            run_status = {
                "status": "blocked_preflight",
                "reason": clean_text("; ".join(reasons)) or "preflight_blocked",
                "completed_windows": [],
                "missing_artifacts": [],
                "finalized": True,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            save_json_atomic(run_dir / "run_status.json", run_status)
        except Exception:
            pass
        try:
            recovery_status = {
                "status": "blocked_preflight_complete",
                "reason": clean_text("; ".join(reasons)) or "preflight_blocked",
                "safe_for_strategy_analysis": False,
                "safe_for_process_analysis": True,
                "do_not_use_as_parent": True,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            save_json_atomic(run_dir / "recovery_status.json", recovery_status)
        except Exception:
            pass
        return 0

    try:
        parent_text = parent_script.read_text(encoding="utf-8", errors="ignore")
        candidate_text = apply_config_to_script_text(parent_text, candidate_cfg, tracked_keys)
        candidate_text = ensure_ties_total_in_summary(candidate_text)
        candidate_script = generated_script_path(run_dir, parent_script.stem, run_id)
        candidate_script.write_text(candidate_text, encoding="utf-8")
    except Exception as e:
        reason = f"candidate_script_generation_failed:{type(e).__name__}:{e}"
        run_log(f"CODER failed: {reason}")
        exit_ctx["status_hint"] = "run_error"
        exit_ctx["reason"] = reason
        ensure_controlled_abort_artifacts(
            run_dir=run_dir,
            run_id=run_id,
            requested_windows=[int(w) for w in requested_windows],
            allowed_windows=[int(w) for w in allowed_windows],
            progressive_windows=[int(w) for w in allowed_windows],
            reason=reason,
            status_hint="run_error",
        )
        return 1

    diff_vs_parent = compute_diff(parent_cfg, candidate_cfg, tracked_keys)
    diff_vs_baseline = compute_diff(baseline_cfg, candidate_cfg, tracked_keys)
    no_op_detected = len(diff_vs_parent) == 0
    change_scope = "strategy_param_change"
    if clean_text(proposal.get("problem_layer", "")) == "process_blocked":
        change_scope = "process_change"

    coder_output = {
        "role": "coder",
        "status": "implemented" if not no_op_detected else "no_op_detected",
        "change_scope": change_scope,
        "parent_script_used": str(parent_script),
        "parent_run_id": parent_run_id,
        "effective_param_diff_vs_parent": diff_vs_parent,
        "effective_param_diff_vs_baseline": diff_vs_baseline,
        "no_op_detected": no_op_detected,
        "files_modified": [str(candidate_script)],
        "exact_changes": diff_vs_parent,
        "notes": "Implementacion exacta de analyst_output sobre parent tecnico.",
    }
    save_json(run_dir / "coder_output.json", coder_output)
    run_log(
        "CODER result "
        f"status={coder_output.get('status')} "
        f"effective_changes={len(diff_vs_parent)} "
        f"candidate_script={candidate_script.name}"
    )
    if no_op_detected:
        coordinator_output = {
            "role": "coordinator",
            "status": "blocked_no_op",
            "decision_type": "rejected",
            "gate_decision": "continue",
            "reasons": ["El cambio no modifica valores efectivos vs parent."],
            "material_change_detected": bool(materiality.get("material_change_detected", False)),
            "materiality": materiality,
            "transition_classification": transition_eval.get("details", []),
            "promotion_reason": "",
            "promotion_blockers": ["blocked_no_op"],
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "candidate_script": str(candidate_script),
            "fallback_diagnosis": proposal.get("fallback_diagnosis", {}),
            "fallback_candidate_pool_considered": proposal.get("fallback_candidate_pool_considered", []),
            "fallback_selected_reason": proposal.get("fallback_selected_reason", ""),
        }
        coordinator_output = finalize_coordinator_output(
            coordinator_output=coordinator_output,
            proposal=proposal,
            executor_output={},
            compare_obj={},
            learning_feedback={},
        )
        save_json(run_dir / "coordinator_output.json", coordinator_output)
        manifest = {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "baseline_reference": baseline.get("baseline_reference", {}),
            "main_change": proposal.get("main_change"),
            "dependent_change": proposal.get("dependent_change"),
            "expected_effect": proposal.get("expected_effect", ""),
            "gate_decision": "continue",
            "material_change_detected": bool(materiality.get("material_change_detected", False)),
            "materiality": materiality,
            "transition_classification": transition_eval.get("details", []),
            "decision_type": "rejected",
            "promotion_reason": "",
            "promotion_blockers": ["blocked_no_op"],
            "effective_change_check": {"no_op_detected": True, "active_logic_changed": False},
            "fallback_diagnosis": proposal.get("fallback_diagnosis", {}),
            "fallback_candidate_pool_considered": proposal.get("fallback_candidate_pool_considered", []),
            "fallback_selected_reason": proposal.get("fallback_selected_reason", ""),
            "status": "blocked_no_op",
            "auditor_v2_evaluation": coordinator_output.get("auditor_v2_evaluation", {}),
        }
        save_json(run_dir / "experiment_manifest.json", manifest)
        append_experiment_row(
            exp_log_path,
            {
                "run_id": run_id,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "parent_run_id": parent_run_id,
                "parent_script": str(parent_script),
                "baseline_reference": clean_text((baseline.get("baseline_reference") or {}).get("run_id")),
                "queue_test_id": clean_text(proposal.get("queue_test_id")),
                "main_parameter": clean_text((proposal.get("main_change") or {}).get("parameter")),
                "main_from": clean_text((proposal.get("main_change") or {}).get("from_value")),
                "main_to": clean_text((proposal.get("main_change") or {}).get("to_value")),
                "dependent_parameter": clean_text((proposal.get("dependent_change") or {}).get("parameter")),
                "dependent_from": clean_text((proposal.get("dependent_change") or {}).get("from_value")),
                "dependent_to": clean_text((proposal.get("dependent_change") or {}).get("to_value")),
                "expected_effect": clean_text(proposal.get("expected_effect")),
                "status": "blocked_no_op",
                "preflight_pass": "true",
                "no_op_detected": "true",
                "effective_change_check": clean_text(json.dumps(preflight_out.get("effective_change_check", {}), ensure_ascii=False)),
                "accepted_or_rejected": "rejected",
                "notes": "No-op detectado por coder.",
                "run_dir": str(run_dir),
            },
        )
        persist_governance_state(
            baseline_path=baseline_path,
            baseline=baseline,
            research_state_path=research_state_path,
            research_state=research_state,
            run_id=run_id,
            decision_type="rejected",
            coordinator_status="blocked_no_op",
            executor_output={},
            coordinator_output=coordinator_output,
            queue_id="",
            proposal=proposal,
            recent_rows=rows,
        )
        run_log("COORDINATOR blocked_no_op: cambio sin efecto real.")
        exit_ctx["status_hint"] = "blocked_no_op"
        exit_ctx["reason"] = "blocked_no_op_after_coder"
        return 0

    if args.dry_run:
        run_log("DRY_RUN completado: analyst+coder+preflight OK, sin ejecutar backtests.")
        exit_ctx["status_hint"] = "dry_run"
        exit_ctx["reason"] = "dry_run_completed"
        return 0

    weekly_csv = get_latest_weekly_csv(repo)
    windows_results: Dict[str, Any] = {}
    exec_errors: List[str] = []
    windows_sorted = [int(w) for w in (windows or []) if int(w) > 0]
    runtime_perf_cfg = (
        ((baseline.get("validation_policy") or {}).get("runtime_performance") or {})
        if isinstance(baseline.get("validation_policy"), dict)
        else {}
    )
    if not isinstance(runtime_perf_cfg, dict):
        runtime_perf_cfg = {}
    early_prune_enabled = not bool(args.disable_early_prune)
    strict_progressive_windows = bool(runtime_perf_cfg.get("strict_progressive_windows", True))
    # Performance mode: when requested windows include 52, execute the max window once
    # and derive smaller window metrics from the 52w artifacts.
    #
    # Important: strict_progressive_windows means "do not add windows outside the
    # allowed/requested set". It must NOT disable reuse/derivation. Older code
    # disabled reuse under strict mode, which forced 4+8+24+52 to run serially.
    window_reuse_enabled = bool(runtime_perf_cfg.get("window_reuse_enabled", True)) and (not bool(args.disable_window_reuse))
    run_num = parse_run_id(run_id)
    xlsx_cadence_runs = max(1, int(to_float(getattr(args, "xlsx_cadence_runs", None)) or to_float(runtime_perf_cfg.get("xlsx_cadence_runs")) or 5))
    tracker_xlsx_refresh_enabled = bool(getattr(args, "enable_tracker_xlsx_refresh", False)) or cfg_bool(
        runtime_perf_cfg.get("tracker_xlsx_refresh_enabled"), False
    )
    window_xlsx_artifacts_enabled = bool(getattr(args, "enable_window_xlsx_artifacts", False)) or cfg_bool(
        runtime_perf_cfg.get("window_xlsx_artifacts_enabled"), False
    )
    profile_cadence_runs = max(1, int(to_float(getattr(args, "profile_cadence_runs", None)) or to_float(runtime_perf_cfg.get("profile_cadence_runs")) or 10))
    profile_this_run = bool((run_num > 0) and (run_num % profile_cadence_runs == 0))
    fast_artifacts_enabled = bool(runtime_perf_cfg.get("fast_artifacts_enabled", True)) and (not bool(getattr(args, "disable_fast_artifacts", False)))
    run_log(
        "EXECUTOR plan "
        f"windows={windows_sorted} early_prune={early_prune_enabled} "
        f"reuse={window_reuse_enabled} strict_progressive_windows={int(strict_progressive_windows)} "
        f"fast_artifacts={fast_artifacts_enabled} "
        f"xlsx_cadence={xlsx_cadence_runs} tracker_xlsx={int(tracker_xlsx_refresh_enabled)} "
        f"window_xlsx={int(window_xlsx_artifacts_enabled)} profile_every={profile_cadence_runs} "
        f"profile_this_run={int(profile_this_run)} policy=progressive_real_windows"
    )

    def _run_window(weeks: int, lightweight: bool, allow_xlsx: bool) -> Dict[str, Any]:
        if int(weeks) not in {int(x) for x in allowed_windows}:
            # Strict window constraints: abort before creating window folder.
            msg = f"blocked_window_not_allowed weeks={weeks} allowed={allowed_windows} requested={requested_windows}"
            run_log(msg)
            try:
                window_plan["blocked_windows"].append(int(weeks))
                write_window_execution_plan(plan_path, window_plan)
            except Exception:
                pass
            return {"status": "blocked_window_not_allowed", "errors": [msg], "window": int(weeks)}
        started_at = datetime.now().isoformat(timespec="seconds")
        run_log(
            "EXECUTOR window_start "
            f"weeks={weeks} lightweight={int(lightweight)} allow_xlsx={int(allow_xlsx)} "
            f"fast_artifacts={int(fast_artifacts_enabled)}"
        )
        wr_local = run_window_backtest(
            repo=repo,
            python_exe=args.python_exe,
            candidate_script=candidate_script,
            run_dir=run_dir,
            window_weeks=int(weeks),
            tie_low=args.tie_low,
            tie_high=args.tie_high,
            weekly_csv=weekly_csv,
            timeout_sec=args.timeout_sec_per_run,
            lightweight_mode=lightweight,
            fast_artifacts_mode=bool(fast_artifacts_enabled and (not allow_xlsx)),
            export_xlsx=allow_xlsx,
            adaptive_workers_mode=True,
            profile_enabled=profile_this_run,
        )
        wm_local = wr_local.get("metrics", {}) if isinstance(wr_local, dict) else {}
        perf_local = wr_local.get("perf", {}) if isinstance(wr_local, dict) else {}
        run_log(
            "EXECUTOR window_done "
            f"weeks={weeks} status={wr_local.get('status')} "
            f"test_start_used={wr_local.get('test_start_used','')} "
            f"actual_weeks_run={wr_local.get('actual_weeks_run','')} depth_ok={int(bool(wr_local.get('depth_ok', False)))} "
            f"weeks_traded={wm_local.get('weeks_traded','')} "
            f"trades={wm_local.get('trades','')} "
            f"wins={wm_local.get('wins','')} "
            f"losses={wm_local.get('losses','')} "
            f"ties={wm_local.get('ties','')} "
            f"spy_compare={wm_local.get('spy_compare','')} "
            f"window_sec={perf_local.get('total_window_sec','')}"
        )
        completed_at = datetime.now().isoformat(timespec="seconds")

        # Per-window wrapper summary (small, auditable, avoids parsing stdout later).
        try:
            window_dir = run_dir / f"window_{int(weeks):02d}"
            wm_local = wr_local.get("metrics", {}) if isinstance(wr_local, dict) else {}
            perf_local = wr_local.get("perf", {}) if isinstance(wr_local, dict) else {}
            window_result = {
                "window": int(weeks),
                "status": clean_text(wr_local.get("status", "")) if isinstance(wr_local, dict) else "",
                "started_at": started_at,
                "completed_at": completed_at,
                "metrics": {
                    "weeks_traded": wm_local.get("weeks_traded"),
                    "trades": wm_local.get("trades"),
                    "wins": wm_local.get("wins"),
                    "losses": wm_local.get("losses"),
                    "ties": wm_local.get("ties"),
                    "avg_net_return_pct": wm_local.get("avg_net_return_pct"),
                    "total_net_pnl_dollars": wm_local.get("total_net_pnl_dollars"),
                    "spy_compare": wm_local.get("spy_compare"),
                },
                "output_files": {
                    "stdout_log": str(window_dir / "stdout.log"),
                    "stderr_log": str(window_dir / "stderr.log"),
                },
                "perf": {
                    "total_window_sec": perf_local.get("total_window_sec") if isinstance(perf_local, dict) else None,
                },
                "errors": (wr_local.get("errors", []) if isinstance(wr_local, dict) else []) or [],
            }
            save_json_atomic(window_dir / "window_result.json", window_result)
        except Exception:
            pass

        try:
            window_plan["executed_windows"].append(int(weeks))
            write_window_execution_plan(plan_path, window_plan)
        except Exception:
            pass

        # Incremental executor partial checkpoint after each completed window.
        try:
            wk = str(int(weeks))
            executor_partial["windows"][wk] = {
                "status": clean_text(wr_local.get("status", "")) if isinstance(wr_local, dict) else "",
                "metrics": (wr_local.get("metrics", {}) if isinstance(wr_local, dict) else {}) or {},
            }
            if int(weeks) not in executor_partial["executed_windows"]:
                executor_partial["executed_windows"].append(int(weeks))
            executor_partial["last_completed_window"] = int(weeks)
            executor_partial["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_json_atomic(executor_partial_path, executor_partial)
        except Exception:
            pass
        return wr_local

    prune_active = False
    prune_reason = ""
    prune_source_log = ""
    long156_decision: Dict[str, Any] = {
        "requested": bool(156 in [int(x) for x in windows_sorted]),
        "policy": long156_policy,
        "trigger": "not_requested",
        "executed": None,
        "threshold_met": None,
        "cadence_met": None,
        "useful_runs_since_last_real_156": int(useful_runs_since_last_real_156),
        "cadence_useful_runs_required": int(long156_cadence_useful_runs),
    }
    execution_order = list(windows_sorted)
    if window_reuse_enabled and 52 in execution_order:
        execution_order = [52] + [w for w in execution_order if int(w) != 52]
    base_reuse_window = 52 if (window_reuse_enabled and 52 in windows_sorted) else None
    base_reuse_result: Optional[Dict[str, Any]] = None
    multi_window_derived_metrics: Dict[str, Any] = {
        "enabled": bool(base_reuse_window is not None),
        "source_window": int(base_reuse_window) if base_reuse_window is not None else None,
        "derived_windows": [],
        "windows": {},
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if base_reuse_window is not None:
        run_log(
            "EXECUTOR multi_window_single_run enabled=1 "
            f"source_window={base_reuse_window} derive_windows={[int(x) for x in windows_sorted if int(x) != int(base_reuse_window)]}"
        )
    for w in execution_order:
        if int(w) not in {int(x) for x in allowed_windows}:
            # Hard abort before any folder creation for forbidden windows.
            msg = f"blocked_window_not_allowed weeks={int(w)} allowed={allowed_windows} requested={requested_windows}"
            run_log(msg)
            try:
                window_plan["blocked_windows"].append(int(w))
                write_window_execution_plan(plan_path, window_plan)
            except Exception:
                pass
            exec_errors.append(msg)
            executor_status = "blocked_window_not_allowed"
            break
        wk = str(int(w))
        if prune_active:
            windows_results[wk] = {
                "status": "insufficient_depth",
                "window": int(w),
                "requested_weeks": int(w),
                "actual_weeks_run": None,
                "depth_ok": False,
                "test_start_used": "",
                "command": "",
                "stdout_log": prune_source_log,
                "stderr_log": prune_source_log,
                "outputs": {"excel": "", "txt": ""},
                "errors": [f"early_prune_not_executed: {prune_reason}"],
                "metrics": {},
                "execution_mode": "skipped_pruned",
            }
            continue

        if (
            window_reuse_enabled
            and base_reuse_window is not None
            and int(w) in {4, 8, 24}
            and isinstance(base_reuse_result, dict)
            and clean_text(base_reuse_result.get("status", "")) in {"run_ok", "insufficient_depth"}
        ):
            wr = derive_window_result_from_existing_run(
                repo=repo,
                python_exe=args.python_exe,
                base_result=base_reuse_result,
                window_weeks=int(w),
                tie_low=args.tie_low,
                tie_high=args.tie_high,
                weekly_csv=weekly_csv,
            )
            windows_results[wk] = wr
            wm = wr.get("metrics", {}) if isinstance(wr, dict) else {}

            # Persist derived window summary so downstream validators/tools see a
            # normal per-window artifact even though no separate subprocess ran.
            try:
                derived_dir = run_dir / f"window_{int(w):02d}"
                derived_dir.mkdir(parents=True, exist_ok=True)
                window_result = {
                    "window": int(w),
                    "status": wr.get("status"),
                    "reason": wr.get("reason", ""),
                    "started_at": datetime.now().isoformat(timespec="seconds"),
                    "completed_at": datetime.now().isoformat(timespec="seconds"),
                    "execution_mode": "derived_reuse",
                    "derived_from_window": int(base_reuse_window) if base_reuse_window is not None else None,
                    "metrics": {
                        "trades": wm.get("trades"),
                        "wins": wm.get("wins"),
                        "losses": wm.get("losses"),
                        "ties": wm.get("ties"),
                        "weeks_traded": wm.get("weeks_traded"),
                        "avg_net_return_pct": wm.get("avg_net_return_pct"),
                        "total_net_pnl_dollars": wm.get("total_net_pnl_dollars"),
                        "spy_compare": wm.get("spy_compare"),
                    },
                    "output_files": {
                        "stdout_log": str(wr.get("stdout_log", "")),
                        "stderr_log": str(wr.get("stderr_log", "")),
                    },
                    "errors": wr.get("errors", []) or [],
                }
                save_json_atomic(derived_dir / "window_result.json", window_result)
            except Exception:
                pass

            try:
                if int(w) not in window_plan["executed_windows"]:
                    window_plan["executed_windows"].append(int(w))
                write_window_execution_plan(plan_path, window_plan)
            except Exception:
                pass

            try:
                executor_partial["windows"][wk] = {
                    "status": clean_text(wr.get("status", "")),
                    "reason": clean_text(wr.get("reason", "")),
                    "metrics": wm or {},
                    "execution_mode": "derived_reuse",
                    "derived_from_window": int(base_reuse_window) if base_reuse_window is not None else None,
                }
                if int(w) not in executor_partial["executed_windows"]:
                    executor_partial["executed_windows"].append(int(w))
                executor_partial["last_completed_window"] = int(w)
                executor_partial["updated_at"] = datetime.now().isoformat(timespec="seconds")
                save_json_atomic(executor_partial_path, executor_partial)
            except Exception:
                pass

            try:
                if int(w) not in multi_window_derived_metrics["derived_windows"]:
                    multi_window_derived_metrics["derived_windows"].append(int(w))
                multi_window_derived_metrics["windows"][wk] = {
                    "status": wr.get("status"),
                    "reason": wr.get("reason", ""),
                    "requested_weeks": int(w),
                    "actual_weeks_run": wr.get("actual_weeks_run"),
                    "depth_ok": bool(wr.get("depth_ok", False)),
                    "test_start_used": wr.get("test_start_used"),
                    "trades": wm.get("trades"),
                    "wins": wm.get("wins"),
                    "losses": wm.get("losses"),
                    "ties": wm.get("ties"),
                    "pnl": wm.get("total_net_pnl_dollars"),
                    "avg_net_return_pct": wm.get("avg_net_return_pct"),
                    "spy_compare": wm.get("spy_compare"),
                }
                save_json_atomic(run_dir / "multi_window_derived_metrics.json", multi_window_derived_metrics)
            except Exception:
                pass

            run_log(
                "EXECUTOR window_derived "
                f"weeks={w} from_window={base_reuse_window} "
                f"status={wr.get('status')} actual_weeks_run={wr.get('actual_weeks_run','')} "
                f"spy_compare={wm.get('spy_compare','')}"
            )
            if wr.get("status") not in {"run_ok", "insufficient_depth", "short_window_no_trades"}:
                exec_errors.extend(wr.get("errors", []) or [])
                prune_active = True
                prune_reason = clean_text("; ".join(wr.get("errors", []) or [f"window_{w}_failed"]))
                prune_source_log = str(wr.get("stdout_log", ""))
                run_log(f"EXECUTOR stop_after_window weeks={w} reason={prune_reason}")
                if base_reuse_window is not None and int(w) == int(base_reuse_window):
                    window_reuse_enabled = False
                    base_reuse_window = None
                    base_reuse_result = None
                    prune_active = False
                    prune_reason = ""
                    prune_source_log = ""
                    run_log(
                        "EXECUTOR multi_window_single_run fallback=legacy_sequential "
                        f"source_window={w} reason={prune_reason or 'source_window_failed'}"
                    )
            elif wr.get("status") == "short_window_no_trades":
                run_log(
                    "EXECUTOR window_short_no_trades "
                    f"weeks={w} reason={clean_text(wr.get('reason', 'insufficient_short_window_activity'))}"
                )
            elif early_prune_enabled and int(w) in {4, 8, 24}:
                prune, reason = should_early_prune_after_window(int(w), wr)
                if prune:
                    prune_active = True
                    prune_reason = reason
                    prune_source_log = str(wr.get("stdout_log", ""))
                    exec_errors.append(f"early_prune_after_{w}: {reason}")
                    run_log(f"EXECUTOR early_prune activated after_window={w} reason={reason}")
            continue

        if int(w) == 156:
            run_156, long156_eval = should_execute_156_window(
                policy=long156_policy,
                windows_results=windows_results,
                useful_runs_since_last_real_156=useful_runs_since_last_real_156,
                cadence_useful_runs=long156_cadence_useful_runs,
                min_w52_spy_compare=long156_min_w52_spy_compare,
                min_w52_weeks_traded=long156_min_w52_weeks_traded,
                min_w52_trades=long156_min_w52_trades,
            )
            long156_decision = dict(long156_eval)
            if not run_156:
                skip_reason = (
                    "skipped_by_policy: "
                    f"policy={long156_decision.get('policy')} "
                    f"trigger={long156_decision.get('trigger')} "
                    f"threshold_met={int(bool(long156_decision.get('threshold_met')))} "
                    f"cadence_met={int(bool(long156_decision.get('cadence_met')))} "
                    f"useful_since_last_real_156={long156_decision.get('useful_runs_since_last_real_156')} "
                    f"cadence_required={long156_decision.get('cadence_useful_runs_required')}"
                )
                windows_results[wk] = {
                    "status": "insufficient_depth",
                    "window": int(w),
                    "requested_weeks": int(w),
                    "actual_weeks_run": None,
                    "depth_ok": False,
                    "test_start_used": "",
                    "command": "",
                    "stdout_log": "",
                    "stderr_log": "",
                    "outputs": {"excel": "", "txt": ""},
                    "errors": [skip_reason],
                    "metrics": {},
                    "execution_mode": "skipped_by_policy",
                }
                long156_decision["executed"] = False
                run_log(
                    "EXECUTOR window_skip "
                    f"weeks=156 policy={long156_decision.get('policy')} "
                    f"trigger={long156_decision.get('trigger')} "
                    f"threshold_met={int(bool(long156_decision.get('threshold_met')))} "
                    f"cadence_met={int(bool(long156_decision.get('cadence_met')))} "
                    f"useful_since_last_real_156={long156_decision.get('useful_runs_since_last_real_156')} "
                    f"cadence_required={long156_decision.get('cadence_useful_runs_required')}"
                )
                continue
            long156_decision["executed"] = True
            run_log(
                "EXECUTOR window_gate "
                f"weeks=156 policy={long156_decision.get('policy')} "
                f"trigger={long156_decision.get('trigger')} "
                f"threshold_met={int(bool(long156_decision.get('threshold_met')))} "
                f"cadence_met={int(bool(long156_decision.get('cadence_met')))}"
            )

        allow_xlsx = bool(
            window_xlsx_artifacts_enabled
            and (int(w) in {52, 156})
            and (run_num <= 0 or (run_num % xlsx_cadence_runs == 0))
        )
        wr = _run_window(int(w), lightweight=(int(w) <= 24), allow_xlsx=allow_xlsx)
        if int(w) == 156 and isinstance(wr, dict):
            wr["execution_mode"] = "executed"
        if base_reuse_window is not None and int(w) == int(base_reuse_window) and isinstance(wr, dict):
            wr["execution_mode"] = "executed_reuse_base"
            base_reuse_result = wr
        windows_results[wk] = wr
        if wr.get("status") != "run_ok":
            exec_errors.extend(wr.get("errors", []) or [])
            # Si falla una ventana, no seguimos profundizando.
            prune_active = True
            prune_reason = clean_text("; ".join(wr.get("errors", []) or [f"window_{w}_failed"]))
            prune_source_log = str(wr.get("stdout_log", ""))
            run_log(f"EXECUTOR stop_after_window weeks={w} reason={prune_reason}")
            continue

        if early_prune_enabled and int(w) in {4, 8, 24}:
            prune, reason = should_early_prune_after_window(int(w), wr)
            if prune:
                prune_active = True
                prune_reason = reason
                prune_source_log = str(wr.get("stdout_log", ""))
                exec_errors.append(f"early_prune_after_{w}: {reason}")
                run_log(f"EXECUTOR early_prune activated after_window={w} reason={reason}")

    executor_status = classify_executor_run_status(windows_results, exec_errors)
    if any("blocked_window_not_allowed" in clean_text(e) for e in (exec_errors or [])):
        executor_status = "blocked_window_not_allowed"
    core_window = "52" if "52" in windows_results else (str(max(windows_sorted)) if windows_sorted else "52")
    core_metrics = (windows_results.get(core_window, {}) or {}).get("metrics", {})
    validation_depth_summary = build_validation_depth_summary(
        windows_results=windows_results,
        requested_windows=requested_windows,
        progressive_windows=windows_sorted,
    )
    perf_rows: List[Dict[str, Any]] = []
    for wk_key, payload in (windows_results or {}).items():
        if not isinstance(payload, dict):
            continue
        perf = payload.get("perf", {}) if isinstance(payload.get("perf"), dict) else {}
        total = to_float(perf.get("total_window_sec"))
        perf_rows.append(
            {
                "window": int(to_float(payload.get("window")) or int(wk_key)),
                "execution_mode": clean_text(payload.get("execution_mode", "executed")),
                "total_window_sec": float(total) if total is not None else math.nan,
                "patch_constants_sec": to_float(perf.get("patch_constants_sec")),
                "subprocess_exec_sec": to_float(perf.get("subprocess_exec_sec")),
                "extract_metrics_sec": to_float(perf.get("extract_metrics_sec")),
            }
        )
    perf_rows_sorted = sorted(
        perf_rows,
        key=lambda x: (-1 if (x.get("total_window_sec") is None or not math.isfinite(float(x.get("total_window_sec")))) else float(x.get("total_window_sec"))),
        reverse=True,
    )
    perf_total = 0.0
    for r in perf_rows:
        tv = r.get("total_window_sec")
        if tv is not None and math.isfinite(float(tv)):
            perf_total += float(tv)
    perf_summary = {
        "profile_this_run": bool(profile_this_run),
        "total_window_runtime_sec": round(float(perf_total), 6),
        "top_hotspots": perf_rows_sorted[:3],
        "multi_window_single_run": bool(base_reuse_window is not None),
        "derived_windows": list(multi_window_derived_metrics.get("derived_windows", [])),
    }
    run_log(
        "EXECUTOR perf_summary "
        f"total_window_runtime_sec={perf_summary.get('total_window_runtime_sec')} "
        f"top_hotspots={perf_summary.get('top_hotspots')}"
    )
    executor_output = {
        "role": "executor",
        "status": executor_status,
        "run_id": run_id,
        "script_executed": str(candidate_script),
        "command": f"{args.python_exe} {candidate_script.name}",
        "windows_policy": {
            "requested": [int(w) for w in requested_windows],
            "progressive_plan": [int(w) for w in windows_sorted],
            "execution_order": [int(w) for w in execution_order],
            "policy": "progressive_real_windows",
            "strict_progressive_windows": bool(strict_progressive_windows),
            "window_reuse_enabled": bool(window_reuse_enabled),
            "multi_window_single_run": bool(base_reuse_window is not None),
            "fast_artifacts_enabled": bool(fast_artifacts_enabled),
            "xlsx_cadence_runs": int(xlsx_cadence_runs),
            "profile_cadence_runs": int(profile_cadence_runs),
            "profile_this_run": bool(profile_this_run),
            "long156_policy": long156_policy,
            "long156_cadence_useful_runs": int(long156_cadence_useful_runs),
            "long156_useful_runs_since_last_real_156": int(useful_runs_since_last_real_156),
            "long156_thresholds": {
                "min_w52_spy_compare": float(long156_min_w52_spy_compare),
                "min_w52_weeks_traded": float(long156_min_w52_weeks_traded),
                "min_w52_trades": float(long156_min_w52_trades),
            },
            "long156_decision": long156_decision,
        },
        "windows": windows_results,
        "core_metrics": core_metrics,
        "validation_depth_summary": validation_depth_summary,
        "performance_profile": perf_summary,
        "errors": exec_errors,
    }
    save_json(run_dir / "executor_output.json", executor_output)
    try:
        executor_partial["status"] = executor_output.get("status", "run_ok")
        executor_partial["partial"] = False
        executor_partial["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_json_atomic(executor_partial_path, executor_partial)
    except Exception:
        pass

    baseline_ref_metrics: Dict[str, Any] = {}
    b_ref = baseline.get("baseline_reference", {})
    b_ref_run = str(b_ref.get("run_id", ""))
    if b_ref_run and b_ref_run.startswith("EXP_"):
        for d in runs_root.iterdir():
            if d.is_dir() and d.name.startswith(b_ref_run):
                eo = load_json(d / "executor_output.json", {})
                for wk in windows:
                    wk_key = str(wk)
                    baseline_ref_metrics[wk_key] = (eo.get("windows", {}).get(wk_key, {}) or {}).get("metrics", {})
                break

    decision_type, decision_reasons, compare_obj = decide_acceptance(
        executor_output=executor_output,
        last_valid_ctx=latest_valid,
        baseline_ref_metrics=baseline_ref_metrics,
        validation_phase=validation_phase,
        year_validation_window_weeks=year_validation_window_weeks,
        min_years_vs_spy=max(1, int(args.min_years_vs_spy)),
        max_nonpositive_years_vs_spy=max(0, int(args.max_nonpositive_years_vs_spy)),
    )
    learning_feedback = build_learning_feedback(
        proposal=proposal,
        decision_type=decision_type,
        compare_obj=compare_obj,
        executor_output=executor_output,
    )
    accepted_or_rejected = "accepted" if decision_type in {"accepted_for_followup", "promoted_to_baseline"} else "rejected"
    promotion_reason = clean_text(compare_obj.get("promotion_reason", ""))
    promotion_blockers = [clean_text(x) for x in (compare_obj.get("promotion_blockers") or []) if clean_text(x)]
    champion_for_followup = bool(compare_obj.get("champion_for_followup", False))
    next_validation_phase = validation_phase
    if executor_status == "run_ok" and decision_type == "promoted_to_baseline" and validation_phase == "year1":
        next_validation_phase = "multi_year"
    run_log(
        "COORDINATOR decision "
        f"status={executor_status} decision_type={decision_type} accepted_or_rejected={accepted_or_rejected} "
        f"phase={validation_phase} next_phase={next_validation_phase} "
        f"global_state_rule_applies={int(bool((compare_obj.get('global_state_rule') or {}).get('applies', False)))} "
        f"champion_for_followup={int(champion_for_followup)} "
        f"promotion_reason={promotion_reason} "
        f"promotion_blockers={promotion_blockers} "
        f"reasons={'; '.join(decision_reasons)}"
    )
    run_log(
        "COORDINATOR feedback "
        f"discarded={learning_feedback.get('hypothesis_discarded', [])} "
        f"worsened={learning_feedback.get('worsened_dimensions', [])} "
        f"next={learning_feedback.get('next_change_type_recommendation', [])}"
    )
    coordinator_output = {
        "role": "coordinator",
        "status": executor_status,
        "gate_decision": "continue",
        "decision_type": decision_type,
        "accepted_for_followup": decision_type == "accepted_for_followup",
        "promoted_to_baseline": decision_type == "promoted_to_baseline",
        "champion_for_followup": champion_for_followup,
        "accepted_or_rejected": accepted_or_rejected,
        "validation_phase": validation_phase,
        "next_validation_phase": next_validation_phase,
        "material_change_detected": bool(materiality.get("material_change_detected", False)),
        "materiality": materiality,
        "transition_classification": transition_eval.get("details", []),
        "reasons": decision_reasons,
        "promotion_reason": promotion_reason,
        "promotion_blockers": promotion_blockers,
        "multi_year_validation": compare_obj.get("multi_year_validation", {}),
        "parent_run_id": parent_run_id,
        "parent_source": parent_source,
        "parent_script": str(parent_script),
        "candidate_script": str(candidate_script),
        "fallback_diagnosis": proposal.get("fallback_diagnosis", {}),
        "fallback_candidate_pool_considered": proposal.get("fallback_candidate_pool_considered", []),
        "fallback_selected_reason": proposal.get("fallback_selected_reason", ""),
        "learning_feedback": learning_feedback,
        "effective_change_check": preflight_out.get("effective_change_check", {}),
        "compare": compare_obj,
        "global_state_rule": compare_obj.get("global_state_rule", {}),
    }
    coordinator_output = finalize_coordinator_output(
        coordinator_output=coordinator_output,
        proposal=proposal,
        executor_output=executor_output,
        compare_obj=compare_obj,
        learning_feedback=learning_feedback,
    )
    save_json(run_dir / "coordinator_output.json", coordinator_output)

    manifest = {
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "parent_script": str(parent_script),
        "baseline_reference": baseline.get("baseline_reference", {}),
        "main_change": proposal.get("main_change"),
        "dependent_change": proposal.get("dependent_change"),
        "expected_effect": proposal.get("expected_effect", ""),
        "gate_decision": "continue",
        "material_change_detected": bool(materiality.get("material_change_detected", False)),
        "materiality": materiality,
        "transition_classification": transition_eval.get("details", []),
        "effective_change_check": preflight_out.get("effective_change_check", {}),
        "decision_type": decision_type,
        "accepted_for_followup": decision_type == "accepted_for_followup",
        "promoted_to_baseline": decision_type == "promoted_to_baseline",
        "champion_for_followup": champion_for_followup,
        "promotion_reason": promotion_reason,
        "promotion_blockers": promotion_blockers,
        "compare_windows": windows,
        "validation_phase": validation_phase,
        "next_validation_phase": next_validation_phase,
        "year_validation_window_weeks": year_validation_window_weeks,
        "multi_year_validation": compare_obj.get("multi_year_validation", {}),
        "compare_vs_spy": True,
        "fallback_diagnosis": proposal.get("fallback_diagnosis", {}),
        "fallback_candidate_pool_considered": proposal.get("fallback_candidate_pool_considered", []),
        "fallback_selected_reason": proposal.get("fallback_selected_reason", ""),
        "learning_feedback": learning_feedback,
        "global_state_rule": compare_obj.get("global_state_rule", {}),
        "auditor_v2_evaluation": coordinator_output.get("auditor_v2_evaluation", {}),
        "status": executor_status,
        "accepted_or_rejected": accepted_or_rejected,
    }
    save_json(run_dir / "experiment_manifest.json", manifest)

    # Always write a final run status summary (best-effort).
    try:
        missing = []
        for fname in ["executor_output.json", "coordinator_output.json", "experiment_manifest.json"]:
            if not (run_dir / fname).exists():
                missing.append(fname)
        run_status = {
            "status": clean_text(executor_status),
            "reason": "",
            "completed_windows": [int(x) for x in (executor_partial.get("executed_windows") or [])],
            "missing_artifacts": missing,
            "finalized": True,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        save_json_atomic(run_dir / "run_status.json", run_status)
    except Exception:
        pass

    if executor_status in {"run_ok", "run_partial_valid"} and decision_type == "promoted_to_baseline":
        if bool(getattr(args, "apply_baseline_promotion", False)):
            baseline["active_config"] = candidate_cfg
            baseline["last_accepted_run_id"] = run_id
            baseline["validation_phase"] = next_validation_phase
            if validation_phase == "year1" and next_validation_phase == "multi_year":
                baseline["year1_milestone"] = {
                    "achieved": True,
                    "run_id": run_id,
                    "at": datetime.now().isoformat(timespec="seconds"),
                }
            baseline["baseline_reference"] = {
                "run_id": run_id,
                "script": str(candidate_script),
                "accepted_at": datetime.now().isoformat(timespec="seconds"),
                "windows_metrics": {str(wk): (windows_results.get(str(wk), {}) or {}).get("metrics", {}) for wk in windows},
            }
            save_json(baseline_path, baseline)
            try:
                rs = load_json(research_state_path, {})
                if isinstance(rs, dict):
                    st = rs.get("state_tracking", {})
                    if not isinstance(st, dict):
                        st = {}
                    st["last_promoted_baseline_at"] = datetime.now().isoformat(timespec="seconds")
                    st["last_promoted_baseline_run_id"] = run_id
                    rs["state_tracking"] = st
                    rs["updated_at"] = datetime.now().isoformat(timespec="seconds")
                    save_json(research_state_path, rs)
            except Exception:
                pass
            run_log(f"BASELINE promoted run_id={run_id} new_validation_phase={next_validation_phase}")
        else:
            pending = {
                "run_id": run_id,
                "at": datetime.now().isoformat(timespec="seconds"),
                "note": "promoted_to_baseline recommended but not applied (missing --apply-baseline-promotion)",
                "candidate_script": str(candidate_script),
                "next_validation_phase": next_validation_phase,
            }
            save_json(run_dir / "pending_baseline_promotion.json", pending)
            run_log(f"BASELINE promotion pending run_id={run_id} (not applied; missing --apply-baseline-promotion)")
    elif executor_status in {"run_ok", "run_partial_valid"} and decision_type == "accepted_for_followup":
        run_log(f"BASELINE not promoted run_id={run_id} decision_type=accepted_for_followup")

    queue_id = str(proposal.get("queue_test_id", ""))
    if queue_id and executor_status in {"run_ok", "run_partial_valid"}:
        mark_queue_item(queue_path, queue_id, "completed", run_id)

    persist_governance_state(
        baseline_path=baseline_path,
        baseline=baseline,
        research_state_path=research_state_path,
        research_state=research_state,
        run_id=run_id,
        decision_type=decision_type,
        coordinator_status=executor_status,
        executor_output=executor_output,
        coordinator_output=coordinator_output,
        queue_id=queue_id if queue_id else "",
        proposal=proposal,
        recent_rows=rows,
    )

    def wm(window: int, metric: str) -> Any:
        return (windows_results.get(str(window), {}) or {}).get("metrics", {}).get(metric)

    append_experiment_row(
        exp_log_path,
        {
            "run_id": run_id,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "parent_run_id": parent_run_id,
            "parent_script": str(parent_script),
            "baseline_reference": clean_text((baseline.get("baseline_reference") or {}).get("run_id")),
            "queue_test_id": clean_text(queue_id),
            "main_parameter": clean_text((proposal.get("main_change") or {}).get("parameter")),
            "main_from": clean_text((proposal.get("main_change") or {}).get("from_value")),
            "main_to": clean_text((proposal.get("main_change") or {}).get("to_value")),
            "dependent_parameter": clean_text((proposal.get("dependent_change") or {}).get("parameter")),
            "dependent_from": clean_text((proposal.get("dependent_change") or {}).get("from_value")),
            "dependent_to": clean_text((proposal.get("dependent_change") or {}).get("to_value")),
            "expected_effect": clean_text(proposal.get("expected_effect")),
            "status": executor_status,
            "preflight_pass": "true",
            "no_op_detected": "false",
            "effective_change_check": clean_text(json.dumps(preflight_out.get("effective_change_check", {}), ensure_ascii=False)),
            "w8_weeks_traded": csv_num(wm(8, "weeks_traded")),
            "w24_weeks_traded": csv_num(wm(24, "weeks_traded")),
            "w52_weeks_traded": csv_num(wm(52, "weeks_traded")),
            "w8_trades": csv_num(wm(8, "trades")),
            "w24_trades": csv_num(wm(24, "trades")),
            "w52_trades": csv_num(wm(52, "trades")),
            "w8_wins": csv_num(wm(8, "wins")),
            "w24_wins": csv_num(wm(24, "wins")),
            "w52_wins": csv_num(wm(52, "wins")),
            "w8_losses": csv_num(wm(8, "losses")),
            "w24_losses": csv_num(wm(24, "losses")),
            "w52_losses": csv_num(wm(52, "losses")),
            "w8_ties": csv_num(wm(8, "ties")),
            "w24_ties": csv_num(wm(24, "ties")),
            "w52_ties": csv_num(wm(52, "ties")),
            "w8_pnl": csv_num(wm(8, "total_net_pnl_dollars")),
            "w24_pnl": csv_num(wm(24, "total_net_pnl_dollars")),
            "w52_pnl": csv_num(wm(52, "total_net_pnl_dollars")),
            "w8_spy_compare": csv_num(wm(8, "spy_compare")),
            "w24_spy_compare": csv_num(wm(24, "spy_compare")),
            "w52_spy_compare": csv_num(wm(52, "spy_compare")),
            "accepted_or_rejected": accepted_or_rejected,
            "notes": clean_text(f"decision_type={decision_type}; promotion_reason={promotion_reason}; {'; '.join(decision_reasons)}"),
            "run_dir": str(run_dir),
        },
    )
    rows_after_append = read_experiment_log(exp_log_path)
    auditor_eval = coordinator_output.get("auditor_v2_evaluation", {}) if isinstance(coordinator_output, dict) else {}
    branch_state_snapshot = (
        research_state.get("branch_state", {}) if isinstance(research_state.get("branch_state"), dict) else {}
    )
    effect_changed, cooldown_changed = update_learning_memory_after_run(
        parameter_effect_memory=parameter_effect_memory,
        subspace_cooldowns=subspace_cooldowns,
        run_id=run_id,
        proposal=proposal,
        decision_type=decision_type,
        executor_status=executor_status,
        compare_obj=compare_obj,
        executor_output=executor_output,
        last_valid_ctx=latest_valid,
        branch_state_snapshot=branch_state_snapshot,
        auditor_eval=(auditor_eval if isinstance(auditor_eval, dict) else {}),
        rows_for_recent_stats=rows_after_append,
    )
    champion_changed = update_champion_runs_after_run(
        champion_runs=champion_runs,
        run_id=run_id,
        parent_run_id=parent_run_id,
        proposal=proposal,
        decision_type=decision_type,
        executor_status=executor_status,
        compare_obj=compare_obj,
        executor_output=executor_output,
    )
    if effect_changed:
        parameter_effect_memory["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_json(parameter_effect_memory_path, parameter_effect_memory)
    if cooldown_changed:
        subspace_cooldowns["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_json(subspace_cooldowns_path, subspace_cooldowns)
    if champion_changed:
        save_json(champion_runs_path, champion_runs)
    if effect_changed or cooldown_changed or champion_changed:
        run_log(
            "LEARNING_MEMORY updated "
            f"effect_changed={int(bool(effect_changed))} "
            f"cooldown_changed={int(bool(cooldown_changed))} "
            f"champion_changed={int(bool(champion_changed))}"
        )

    append_master_tracker(
        repo=repo,
        run_id=run_id,
        parent_run_id=parent_run_id,
        status=executor_status,
        accepted_or_rejected=accepted_or_rejected,
        proposal=proposal,
        cfg=candidate_cfg,
        executor_output=executor_output,
        run_dir=run_dir,
        xlsx_update_cadence=max(1, int(to_float(getattr(args, "xlsx_cadence_runs", None)) or xlsx_cadence_runs or 5)),
        refresh_xlsx=tracker_xlsx_refresh_enabled,
    )

    exit_ctx["status_hint"] = clean_text(executor_status) or "run_ok"
    exit_ctx["reason"] = "normal_completion"
    run_log(f"RUN END run_id={run_id} status={executor_status} decision_type={decision_type} accepted_or_rejected={accepted_or_rejected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
