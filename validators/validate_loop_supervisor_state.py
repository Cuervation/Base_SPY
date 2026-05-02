from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 2


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8-sig")
    except Exception:
        return ""


def _kv_value(text: str, key: str) -> str:
    pattern = rf"^\s*-\s*{re.escape(key)}:\s*`?(.*?)`?\s*$"
    for line in text.splitlines():
        m = re.match(pattern, line)
        if m:
            return m.group(1).strip()
    return ""


def _split_windows(raw: str) -> List[int]:
    out: List[int] = []
    for part in re.split(r"[,\s]+", raw.strip()):
        if not part:
            continue
        try:
            out.append(int(part))
        except Exception:
            continue
    return out


def _find_run_dir(repo: Path, run_id: str) -> Optional[Path]:
    runs_root = repo / "runs" / "multi_agent_runs"
    if not runs_root.exists() or not run_id:
        return None

    # Soporta run_id completo tipo EXP_160_260425... o corto tipo EXP_160.
    direct = runs_root / run_id
    if direct.exists() and direct.is_dir():
        return direct

    matches = [p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(f"{run_id}_")]
    if not matches:
        return None

    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]


def _run_is_invalid(repo: Path, run_id: str) -> bool:
    if run_id in {"", "BASELINE_CLEAN"}:
        return False

    run_dir = _find_run_dir(repo, run_id)
    if not run_dir:
        return True

    recovery = _load_json(run_dir / "recovery_status.json")
    if recovery.get("do_not_use_as_parent") is True:
        return True

    if not (run_dir / "executor_output.json").exists():
        return True
    if not (run_dir / "coordinator_output.json").exists():
        return True
    if not (run_dir / "experiment_manifest.json").exists():
        return True

    coordinator = _load_json(run_dir / "coordinator_output.json")
    decision_type = str(coordinator.get("decision_type", "")).strip()
    accepted_for_followup = bool(coordinator.get("accepted_for_followup", False))
    promoted_to_baseline = bool(coordinator.get("promoted_to_baseline", False))

    if decision_type == "rejected" and not accepted_for_followup:
        return True

    if not accepted_for_followup and not promoted_to_baseline:
        return True

    run_status = _load_json(run_dir / "run_status.json")
    status = str(run_status.get("status", "")).strip()
    if status in {"blocked_parent_missing", "blocked_preflight", "run_error"}:
        return True

    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate loop supervisor state and summary consistency.")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    live_path = repo / "reports" / "autonomous_loop_live_summary.md"
    final_path = repo / "reports" / "autonomous_loop_final_summary.md"
    state_path = repo / "state" / "autonomous_loop_state.json"

    live_text = _read_text(live_path)
    final_text = _read_text(final_path)
    state = _load_json(state_path)

    live_status = _kv_value(live_text, "loop_status")
    final_status = _kv_value(final_text, "status")
    selected_parent_run_id = _kv_value(live_text, "selected_parent_run_id")
    selected_parent_source = _kv_value(live_text, "selected_parent_source")
    parent_valid_raw = _kv_value(live_text, "parent_valid").lower()
    parent_valid = parent_valid_raw in {"true", "1", "yes"}

    requested_windows_raw = _kv_value(final_text, "windows")
    requested_windows = _split_windows(requested_windows_raw)

    effective_windows = state.get("windows", [])
    if not isinstance(effective_windows, list):
        effective_windows = []

    try:
        effective_windows_int = [int(x) for x in effective_windows]
    except Exception:
        effective_windows_int = []

    current_parent_run_id = str(state.get("current_parent_run_id", "") or "").strip()

    if final_status == "FAIL" and live_status == "running":
        return _fail("live_summary loop_status=running while final_summary status=FAIL")

    if selected_parent_run_id and not parent_valid:
        return _fail("selected_parent_run_id exists while parent_valid=false")

    if requested_windows == [4, 8, 24, 52] and 156 in effective_windows_int:
        return _fail("effective_windows contains 156 in 4/8/24/52 mode")

    if selected_parent_source == "current_baseline" and not parent_valid:
        return _fail("current_baseline selected as parent but parent_valid=false")

    if current_parent_run_id and current_parent_run_id not in {"BASELINE_CLEAN"}:
        if _run_is_invalid(repo, current_parent_run_id):
            return _fail("current_parent_run_id points to rejected/no-parent/invalid run")

    if selected_parent_run_id and selected_parent_run_id not in {"BASELINE_CLEAN"}:
        if _run_is_invalid(repo, selected_parent_run_id):
            return _fail("selected_parent_run_id points to rejected/no-parent/invalid run")

    print("OK: loop supervisor state is consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
