import csv
import json
import os
import re
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
last_n = int(sys.argv[2])
out_dir = Path(sys.argv[3]).resolve()
proc_file = Path(sys.argv[4]).resolve()
deep_artifacts = sys.argv[5].lower() == "true"

RUN_RE = re.compile(r"\bEXP_\d+\b", re.I)

SKIP_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache",
    "node_modules", ".venv", "venv", "env",
    "backups", "backup", "dist", "build",
    "sp500_data", "data_raw", "raw_data"
}

JSON_ARTIFACT_NAMES = [
    "coordinator_output.json",
    "analyst_output.json",
    "executor_output.json",
    "executor_output.partial.json",
    "experiment_manifest.json",
    "run_status.json",
    "candidate.json",
    "next_change.json",
    "metrics_summary.json",
    "summary.json",
]

METRIC_KEYS_HINTS = [
    "avg_net_return_pct",
    "spy_compare",
    "pnl",
    "trades",
    "win_rate",
    "winner",
    "loser",
    "net_return",
]

def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            return Path(path).read_text(encoding="latin-1", errors="replace")
        except Exception:
            return ""

def read_json(path):
    try:
        txt = read_text(path)
        if not txt.strip():
            return None
        return json.loads(txt)
    except Exception:
        return None

def parse_dt(v):
    if v is None:
        return None
    s = str(v).strip().replace("Z", "")
    if not s:
        return None
    for fmt in [
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ]:
        try:
            return datetime.strptime(s[:26], fmt)
        except Exception:
            pass
    return None

def run_num(run_id):
    m = RUN_RE.search(str(run_id))
    return int(m.group(0).split("_")[1]) if m else -1

def stringify(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        try:
            return json.dumps(v, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(v)
    return str(v)

def boolish(v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in {"1", "true", "yes", "y", "si", "sí", "accepted", "promoted"}

def flatten_find(obj, keys):
    wanted = {k.lower() for k in keys}
    if obj is None:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in wanted:
                return v
        for v in obj.values():
            r = flatten_find(v, keys)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for x in obj:
            r = flatten_find(x, keys)
            if r is not None:
                return r
    return None

def flatten_all(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(flatten_all(v, key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            key = f"{prefix}.{i}" if prefix else str(i)
            out.update(flatten_all(v, key))
    else:
        out[prefix] = obj
    return out

def classify_text(*parts):
    txt = " ".join(stringify(p) for p in parts if p is not None).lower()

    if "candidate_generation_exhausted" in txt:
        return "candidate_generation_exhausted"
    if "candidate_generation_failure" in txt or "cgf_" in txt:
        return "candidate_generation_failure"
    if "blocked_no_material_candidate" in txt or "no_material" in txt or "no material" in txt:
        return "blocked_no_material_candidate"
    if "metric_no_effect" in txt or "no effect" in txt:
        return "metric_no_effect"
    if "blocked_no_op" in txt or "no-op" in txt or "noop" in txt:
        return "blocked_no_op"
    if "zigzag" in txt or "zig-zag" in txt:
        return "blocked_zigzag"
    if "timeout" in txt or "timed out" in txt:
        return "timeout"
    if "permission denied" in txt or "access is denied" in txt:
        return "permission_denied"
    if "parent_invalid" in txt or "parent invalid" in txt:
        return "parent_invalid"
    if "coordinator_output_invalid" in txt or "coordinator output invalid" in txt:
        return "coordinator_output_invalid"
    if "fix_process_before_more_research" in txt:
        return "fix_process_before_more_research"
    if "baseline_changed" in txt or "baseline changed" in txt:
        return "baseline_changed"
    if "promoted_to_baseline" in txt:
        return "promoted_to_baseline"
    if "accepted_for_followup" in txt:
        return "accepted_for_followup"
    if "run_partial_valid" in txt:
        return "run_partial_valid"
    if "run_ok" in txt:
        return "run_ok"
    if "rejected" in txt:
        return "rejected"
    if "traceback" in txt or "exception" in txt or "error" in txt:
        return "error_or_exception"
    return "unknown"

def discover_paths():
    paths = {}
    candidates = [
        repo / "trackers" / "experiment_log.csv",
        repo / "experiment_log.csv",
        repo / "reports" / "experiment_log.csv",
    ]
    paths["experiment_log"] = next((p for p in candidates if p.exists()), None)

    candidates = [
        repo / "logs" / "autonomous_loop" / "loop_trace.jsonl",
        repo / "loop_trace.jsonl",
        repo / "reports" / "loop_trace.jsonl",
    ]
    paths["loop_trace"] = next((p for p in candidates if p.exists()), None)

    paths["state"] = repo / "state" / "autonomous_loop_state.json"
    if not paths["state"].exists():
        paths["state"] = None

    paths["live_summary"] = repo / "reports" / "autonomous_loop_live_summary.md"
    if not paths["live_summary"].exists():
        paths["live_summary"] = None

    paths["cgf_csv"] = repo / "state" / "candidate_generation_failures.csv"
    if not paths["cgf_csv"].exists():
        paths["cgf_csv"] = None

    paths["exhaustion_md"] = repo / "reports" / "candidate_generation_exhaustion_diagnostic.md"
    if not paths["exhaustion_md"].exists():
        paths["exhaustion_md"] = None

    paths["exhaustion_json"] = repo / "reports" / "candidate_generation_exhaustion_diagnostic.json"
    if not paths["exhaustion_json"].exists():
        paths["exhaustion_json"] = None

    return paths

def read_experiment_log(path):
    rows = []
    if not path:
        return rows
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            for line, row in enumerate(reader, 2):
                row = {str(k).strip(): v for k, v in row.items() if k is not None}
                raw = " ".join(stringify(v) for v in row.values())
                run_id = ""
                for key in ["run_id", "experiment_id", "id", "Run", "run"]:
                    if key in row and RUN_RE.search(str(row[key])):
                        run_id = RUN_RE.search(str(row[key])).group(0).upper()
                        break
                if not run_id:
                    m = RUN_RE.search(raw)
                    run_id = m.group(0).upper() if m else ""
                if not run_id:
                    continue

                ts = None
                for k in ["created_at", "started_at", "updated_at", "finished_at", "timestamp", "time", "datetime", "date"]:
                    ts = parse_dt(row.get(k))
                    if ts:
                        break

                rows.append({
                    "source": "experiment_log",
                    "line": line,
                    "run_id": run_id,
                    "timestamp": ts,
                    "row": row,
                    "raw": raw,
                })
    except Exception as e:
        rows.append({
            "source": "experiment_log_error",
            "line": 0,
            "run_id": "",
            "timestamp": None,
            "row": {},
            "raw": f"{type(e).__name__}: {e}",
        })
    return rows

def read_loop_trace(path):
    rows = []
    if not path:
        return rows
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line, raw in enumerate(f, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    obj = {"raw": raw}

                rid = ""
                v = flatten_find(obj, ["run_id", "experiment_id", "id"])
                if v and RUN_RE.search(str(v)):
                    rid = RUN_RE.search(str(v)).group(0).upper()
                if not rid:
                    m = RUN_RE.search(raw)
                    rid = m.group(0).upper() if m else ""
                if not rid:
                    continue

                ts = None
                for k in ["timestamp", "ts", "time", "created_at", "updated_at", "started_at", "finished_at"]:
                    ts = parse_dt(flatten_find(obj, [k]))
                    if ts:
                        break

                rows.append({
                    "source": "loop_trace",
                    "line": line,
                    "run_id": rid,
                    "timestamp": ts,
                    "obj": obj,
                    "raw": raw,
                })
    except Exception as e:
        rows.append({
            "source": "loop_trace_error",
            "line": 0,
            "run_id": "",
            "timestamp": None,
            "obj": {},
            "raw": f"{type(e).__name__}: {e}",
        })
    return rows

def read_cgf(path):
    rows = []
    if not path:
        return rows
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            for line, row in enumerate(reader, 2):
                row = {str(k).strip(): v for k, v in row.items() if k is not None}
                rows.append(row)
    except Exception:
        pass
    return rows

def select_last_runs(exp_rows, trace_rows):
    events = []
    for e in exp_rows:
        if e.get("run_id"):
            events.append((e.get("timestamp") or datetime.min, run_num(e["run_id"]), e["source"], e["line"], e["run_id"]))
    for e in trace_rows:
        if e.get("run_id"):
            events.append((e.get("timestamp") or datetime.min, run_num(e["run_id"]), e["source"], e["line"], e["run_id"]))

    events = sorted(events)
    selected = []
    seen = set()
    for _, _, _, _, rid in reversed(events):
        if rid not in seen:
            selected.append(rid)
            seen.add(rid)
        if len(selected) >= last_n:
            break
    return list(reversed(selected))

def find_run_dirs(selected):
    if not deep_artifacts:
        return defaultdict(list)

    idx = defaultdict(list)
    roots = [
        repo / "runs",
        repo / "reports",
        repo / "logs",
        repo / "experiments",
        repo / "outputs",
        repo,
    ]
    roots = [r for r in roots if r.exists() and r.is_dir()]
    selected_set = set(selected)

    visited = 0
    for root in roots:
        for cur, dirs, files in os.walk(root):
            visited += 1
            if visited > 80000:
                break
            curp = Path(cur)
            parts_lower = {p.lower() for p in curp.parts}
            if parts_lower & SKIP_DIRS:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".git")]

            text = str(curp)
            for m in RUN_RE.finditer(text):
                rid = m.group(0).upper()
                if rid in selected_set:
                    idx[rid].append(curp)
    return idx

def read_artifacts_for_run(rid, dir_index):
    objs = []
    texts = []
    dirs = sorted(set(dir_index.get(rid, [])), key=lambda p: len(str(p)))[:8]
    for d in dirs:
        for name in JSON_ARTIFACT_NAMES:
            p = d / name
            if p.exists():
                obj = read_json(p)
                if obj is not None:
                    objs.append(obj)
                texts.append(f"\n--- {p} ---\n{read_text(p)[:30000]}")
    return objs, "\n".join(texts), dirs

def extract_metric_value(flat, keys):
    for target in keys:
        target_l = target.lower()
        for k, v in flat.items():
            if k.lower().endswith(target_l) or target_l in k.lower():
                try:
                    if v is None or v == "":
                        continue
                    return float(str(v).replace(",", "."))
                except Exception:
                    pass
    return None

def summarize_run(rid, exp_by_run, trace_by_run, artifacts_objs, artifacts_text, artifact_dirs):
    raw_parts = []
    json_objs = []

    for e in exp_by_run.get(rid, []):
        raw_parts.append(e.get("raw", ""))
        json_objs.append(e.get("row", {}))
    for e in trace_by_run.get(rid, []):
        raw_parts.append(e.get("raw", ""))
        json_objs.append(e.get("obj", {}))

    raw_parts.append(artifacts_text)
    json_objs.extend(artifacts_objs)

    all_text = "\n".join(raw_parts)

    timestamps = []
    for e in exp_by_run.get(rid, []) + trace_by_run.get(rid, []):
        if e.get("timestamp"):
            timestamps.append(e["timestamp"])

    def first(keys):
        for obj in json_objs:
            v = flatten_find(obj, keys)
            if v not in [None, ""]:
                return v
        return None

    status = first(["status", "loop_status", "run_status", "final_status"])
    decision = first(["decision", "coordinator_decision", "final_decision", "decision_type"])
    reason = first(["reason", "stop_reason", "blocked_reason", "rejection_reason", "decision_reason", "recommended_next_action", "message", "error_type"])
    parent = first(["parent_run_id", "current_parent_run_id", "selected_parent_run_id", "baseline_parent_run_id"])
    family = first(["candidate_family", "family", "change_family", "proposal_family"])
    axis = first(["candidate_axis", "axis", "changed_key", "param_name", "parameter"])

    accepted = first(["accepted_for_followup"])
    promoted = first(["promoted_to_baseline"])
    baseline_changed = first(["baseline_changed"])
    do_not_use = first(["do_not_use_as_parent", "do_not_use_parent"])

    windows = set()
    for obj in json_objs:
        flat = flatten_all(obj)
        for k, v in flat.items():
            kl = k.lower()
            if any(x in kl for x in ["executed_windows", "evaluation_windows", ".windows", "windows"]):
                if isinstance(v, list):
                    for x in v:
                        if str(x).isdigit():
                            windows.add(int(x))
                else:
                    for x in re.findall(r"\b\d+\b", str(v)):
                        if x in {"4", "8", "24", "52", "156"}:
                            windows.add(int(x))
    if not windows:
        for m in re.finditer(r"(executed_windows|evaluation_windows|windows|ventanas)[^\n\r]{0,100}", all_text, re.I):
            for x in re.findall(r"\b\d+\b", m.group(0)):
                if x in {"4", "8", "24", "52", "156"}:
                    windows.add(int(x))

    flat_all = {}
    for obj in json_objs:
        flat_all.update(flatten_all(obj))

    metrics = {
        "w52_avg_net_return_pct": extract_metric_value(flat_all, ["w52_avg_net_return_pct", "52_avg_net_return_pct", "avg_net_return_pct_52"]),
        "w52_spy_compare": extract_metric_value(flat_all, ["w52_spy_compare", "52_spy_compare", "spy_compare_52"]),
        "w52_pnl": extract_metric_value(flat_all, ["w52_pnl", "52_pnl", "pnl_52"]),
        "w52_trades": extract_metric_value(flat_all, ["w52_trades", "52_trades", "trades_52"]),
        "w24_avg_net_return_pct": extract_metric_value(flat_all, ["w24_avg_net_return_pct", "24_avg_net_return_pct", "avg_net_return_pct_24"]),
        "w24_spy_compare": extract_metric_value(flat_all, ["w24_spy_compare", "24_spy_compare", "spy_compare_24"]),
        "w8_avg_net_return_pct": extract_metric_value(flat_all, ["w8_avg_net_return_pct", "8_avg_net_return_pct", "avg_net_return_pct_8"]),
        "w8_spy_compare": extract_metric_value(flat_all, ["w8_spy_compare", "8_spy_compare", "spy_compare_8"]),
    }

    classification = classify_text(status, decision, reason, all_text[:12000])
    real_run = bool(windows & {4, 8, 24, 52, 156}) or classification in {"run_ok", "run_partial_valid"}
    operational_error = classification in {"timeout", "permission_denied", "parent_invalid", "coordinator_output_invalid", "error_or_exception"}

    return {
        "run_id": rid,
        "run_num": run_num(rid),
        "first_seen": min(timestamps).isoformat(sep=" ") if timestamps else "",
        "last_seen": max(timestamps).isoformat(sep=" ") if timestamps else "",
        "classification": classification,
        "status": stringify(status),
        "decision": stringify(decision),
        "reason": stringify(reason)[:700],
        "parent_run_id": stringify(parent),
        "candidate_family": stringify(family),
        "candidate_axis": stringify(axis),
        "accepted_for_followup": stringify(accepted),
        "accepted_bool": boolish(accepted),
        "promoted_to_baseline": stringify(promoted),
        "promoted_bool": boolish(promoted),
        "baseline_changed": stringify(baseline_changed),
        "baseline_changed_bool": boolish(baseline_changed),
        "do_not_use_as_parent": stringify(do_not_use),
        "do_not_use_bool": boolish(do_not_use),
        "executed_windows": ",".join(map(str, sorted(windows))),
        "real_run": real_run,
        "operational_error": operational_error,
        "artifact_dirs_found": len(artifact_dirs),
        "sample_artifact_dir": str(artifact_dirs[0]) if artifact_dirs else "",
        **metrics,
    }

def check_v4_markers():
    files = {
        "run_multi_agent_iteration.py": repo / "run_multi_agent_iteration.py",
        "run_infinite_research_loop.py": repo / "scripts" / "loop" / "run_infinite_research_loop.py",
        "safe_io.py": repo / "scripts" / "safe_io.py",
        "autonomy_contract.json": repo / "config" / "autonomy_contract.json",
        "verify_autonomy_patch.ps1": repo / "verify_autonomy_patch.ps1",
        "reconcile_loop_state.py": repo / "scripts" / "loop" / "reconcile_loop_state.py",
        "autonomy_batch_audit.py": repo / "scripts" / "loop" / "autonomy_batch_audit.py",
    }

    combined = ""
    result = {}
    for name, p in files.items():
        exists = p.exists()
        result[f"exists:{name}"] = exists
        if exists and p.suffix.lower() in {".py", ".json", ".ps1", ".md"}:
            combined += "\n" + read_text(p)[:250000]

    markers = [
        "candidate_generation_exhausted",
        "candidate_generation_failures",
        "CGF_",
        "quarantine",
        "candidate_generation_exhaustion_diagnostic",
        "single_instance_lock_enabled",
        "iteration_timeout_seconds",
        "timeout=",
        "safe_io",
        "stop_on_baseline_change",
    ]
    for m in markers:
        result[f"marker:{m}"] = m in combined

    return result

def write_csv(path, rows):
    keys = []
    seen = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                keys.append(k)
                seen.add(k)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def md_table(rows, headers, max_rows=40):
    if not rows:
        return "_Sin datos._\n"
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for r in rows[:max_rows]:
        vals = []
        for h in headers:
            v = stringify(r.get(h, ""))
            v = v.replace("\n", " ").replace("|", "\\|")
            if len(v) > 130:
                v = v[:127] + "..."
            vals.append(v)
        out.append("| " + " | ".join(vals) + " |")
    if len(rows) > max_rows:
        out.append(f"\n_Mostrando {max_rows} de {len(rows)} filas._")
    return "\n".join(out) + "\n"

def pct(a, b):
    if b == 0:
        return 0.0
    return round((a / b) * 100.0, 2)

def main():
    paths = discover_paths()
    state = read_json(paths["state"]) if paths["state"] else {}
    exp_rows = read_experiment_log(paths["experiment_log"])
    trace_rows = read_loop_trace(paths["loop_trace"])
    cgf_rows = read_cgf(paths["cgf_csv"])
    selected = select_last_runs(exp_rows, trace_rows)

    exp_by_run = defaultdict(list)
    for r in exp_rows:
        exp_by_run[r["run_id"]].append(r)

    trace_by_run = defaultdict(list)
    for r in trace_rows:
        trace_by_run[r["run_id"]].append(r)

    dir_index = find_run_dirs(selected)

    summaries = []
    for rid in selected:
        objs, txt, dirs = read_artifacts_for_run(rid, dir_index)
        summaries.append(summarize_run(rid, exp_by_run, trace_by_run, objs, txt, dirs))
    summaries = sorted(summaries, key=lambda r: r["run_num"])

    v4 = check_v4_markers()

    loop_status = stringify(flatten_find(state, ["loop_status", "status"]))
    stop_reason = stringify(flatten_find(state, ["stop_reason"]))
    last_run_id = stringify(flatten_find(state, ["last_run_id"]))
    last_run_status = stringify(flatten_find(state, ["last_run_status"]))
    current_parent = stringify(flatten_find(state, ["current_parent_run_id", "selected_parent_run_id"]))
    iterations_completed = stringify(flatten_find(state, ["iterations_completed"]))
    updated_at = stringify(flatten_find(state, ["updated_at"]))
    escape_active = flatten_find(state, ["candidate_generation_escape_active"])
    escape_event = flatten_find(state, ["candidate_generation_escape_event"])
    branch_exhausted_event = flatten_find(state, ["branch_exhausted_event"])
    consecutive_no_material = stringify(flatten_find(state, ["consecutive_no_material_candidate"]))
    force_next_mode = stringify(flatten_find(state, ["force_next_candidate_generation_mode"]))

    class_counts = Counter(r["classification"] for r in summaries)
    parent_counts = Counter(r["parent_run_id"] or "(vacío)" for r in summaries)
    windows_counts = Counter(r["executed_windows"] or "(sin ventanas)" for r in summaries)

    real_runs = [r for r in summaries if r["real_run"]]
    empty_runs = [r for r in summaries if not r["real_run"]]
    accepted = [r for r in summaries if r["accepted_bool"]]
    promoted = [r for r in summaries if r["promoted_bool"]]
    op_errors = [r for r in summaries if r["operational_error"]]
    no_material = [r for r in summaries if r["classification"] in {"blocked_no_material_candidate", "candidate_generation_failure"}]
    exhausted = [r for r in summaries if r["classification"] == "candidate_generation_exhausted"]

    # streak no-material
    best_streak = []
    cur = []
    for r in summaries:
        if r["classification"] in {"blocked_no_material_candidate", "candidate_generation_failure"}:
            cur.append(r)
            if len(cur) > len(best_streak):
                best_streak = cur[:]
        else:
            cur = []

    # últimos tests reales con métricas
    real_with_metrics = []
    for r in real_runs:
        if any(r.get(k) is not None for k in ["w52_avg_net_return_pct", "w52_spy_compare", "w52_pnl", "w52_trades"]):
            real_with_metrics.append(r)

    # diagnóstico de aprendizaje
    total = len(summaries)
    no_material_ratio = pct(len(no_material), total)
    real_ratio = pct(len(real_runs), total)
    accepted_ratio = pct(len(accepted), total)

    v4_required_markers = [
        "exists:autonomy_contract.json",
        "marker:candidate_generation_exhausted",
        "marker:candidate_generation_failures",
        "marker:CGF_",
        "marker:candidate_generation_exhaustion_diagnostic",
    ]
    v4_ok = all(v4.get(k) for k in v4_required_markers)

    stopped = loop_status.lower() in {"stopped", "stopped_for_fail", "fail", "failed", "stopped_for_review"} or bool(stop_reason)
    running = loop_status.lower() == "running"
    completed = loop_status.lower() == "completed"

    recommendation = []
    continue_score = 0

    if stopped:
        recommendation.append(f"NO seguir todavía: el loop figura frenado. stop_reason=`{stop_reason}`.")
        continue_score -= 5
    elif running:
        recommendation.append("El loop figura running. Antes de tocar nada, revisar procesos vivos para evitar doble writer.")
        continue_score += 0
    elif completed:
        recommendation.append("El lote terminó como completed. Se puede decidir con métricas del lote.")
        continue_score += 1

    if not v4_ok and no_material_ratio >= 50:
        recommendation.append("NO correr lotes largos: v4 candidate_generation_exhaustion no parece aplicado completo y hay mucho no_material.")
        continue_score -= 5
    elif v4_ok:
        recommendation.append("v4 parece aplicado por marcadores principales.")
        continue_score += 2

    if len(real_runs) == 0:
        recommendation.append("NO tiene sentido seguir igual: no hubo corridas reales con ventanas; no hay aprendizaje de performance.")
        continue_score -= 5
    elif real_ratio < 20:
        recommendation.append("Seguir solo con lote chico: pocas corridas reales; el generador está trabado.")
        continue_score -= 2
    else:
        recommendation.append("Hay suficientes corridas reales para evaluar aprendizaje.")
        continue_score += 2

    if len(accepted) == 0:
        recommendation.append("No hubo accepted_for_followup en el rango: no hay mejora validada reciente.")
        continue_score -= 2
    else:
        recommendation.append(f"Hubo {len(accepted)} accepted_for_followup: hay alguna señal de aprendizaje.")
        continue_score += 3

    if len(promoted) > 0:
        recommendation.append(f"Hubo {len(promoted)} promoted_to_baseline: revisar manualmente antes de seguir.")
        continue_score += 1

    if len(best_streak) >= 25:
        recommendation.append(f"ALERTA: streak no_material de {len(best_streak)}. Debería cortar con candidate_generation_exhausted, no seguir.")
        continue_score -= 4
    elif len(best_streak) >= 5:
        recommendation.append(f"Atención: streak no_material de {len(best_streak)}. Debería activar escape.")
        continue_score -= 1

    if len(op_errors) > 0:
        recommendation.append(f"Hay {len(op_errors)} errores operativos o similares en el rango. Revisar antes de seguir.")
        continue_score -= 2

    unique_parents = {r["parent_run_id"] for r in summaries if r["parent_run_id"]}
    if len(unique_parents) == 1 and total >= 20:
        p = next(iter(unique_parents))
        recommendation.append(f"Parent congelado en `{p}`. Si se combina con no_material alto, el branch está agotado.")
        continue_score -= 2

    if len(cgf_rows) > 0:
        recommendation.append(f"Hay {len(cgf_rows)} filas en candidate_generation_failures.csv: v4/CGF está registrando fallas.")
        continue_score += 1

    if exhausted or paths["exhaustion_md"] or paths["exhaustion_json"]:
        recommendation.append("Existe diagnóstico candidate_generation_exhaustion. Conviene leerlo antes de seguir.")
        continue_score -= 1

    if continue_score >= 3:
        verdict = "SEÑAL ACEPTABLE: tiene sentido seguir con lote chico controlado."
    elif continue_score >= -1:
        verdict = "MIXTO: seguir solo con pocas iteraciones y monitoreo."
    else:
        verdict = "NO CONVIENE SEGUIR IGUAL: corregir generación/aplicación de v4 antes de más corridas."

    # CSVs
    write_csv(out_dir / "latest_runs_learning_summary.csv", summaries)
    write_csv(out_dir / "latest_real_runs.csv", real_runs)
    write_csv(out_dir / "latest_accepted_runs.csv", accepted)
    write_csv(out_dir / "latest_operational_errors.csv", op_errors)
    write_csv(out_dir / "latest_no_material_runs.csv", no_material)

    with (out_dir / "selected_run_ids.txt").open("w", encoding="utf-8") as f:
        for rid in selected:
            f.write(rid + "\n")

    # report
    lines = []
    lines.append(f"# Auditoría de aprendizaje y continuidad\n")
    lines.append(f"- Repo: `{repo}`")
    lines.append(f"- Generado: `{datetime.now().isoformat(sep=' ', timespec='seconds')}`")
    lines.append(f"- Últimas corridas analizadas: **{len(summaries)}**")
    if summaries:
        lines.append(f"- Rango: **{summaries[0]['run_id']} → {summaries[-1]['run_id']}**")
    lines.append("")

    lines.append("## Veredicto\n")
    lines.append(f"**{verdict}**\n")
    for r in recommendation:
        lines.append(f"- {r}")
    lines.append("")

    lines.append("## Estado del loop\n")
    lines.append(f"- loop_status: `{loop_status}`")
    lines.append(f"- stop_reason: `{stop_reason}`")
    lines.append(f"- last_run_id: `{last_run_id}`")
    lines.append(f"- last_run_status: `{last_run_status}`")
    lines.append(f"- current_parent_run_id: `{current_parent}`")
    lines.append(f"- iterations_completed: `{iterations_completed}`")
    lines.append(f"- updated_at: `{updated_at}`")
    lines.append(f"- consecutive_no_material_candidate: `{consecutive_no_material}`")
    lines.append(f"- force_next_candidate_generation_mode: `{force_next_mode}`")
    lines.append(f"- candidate_generation_escape_active: `{escape_active}`")
    lines.append(f"- candidate_generation_escape_event: `{stringify(escape_event)[:1000]}`")
    lines.append(f"- branch_exhausted_event: `{stringify(branch_exhausted_event)[:1000]}`")
    lines.append("")

    lines.append("## Procesos vivos relacionados\n")
    lines.append("```txt")
    lines.append(read_text(proc_file)[:4000])
    lines.append("```")
    lines.append("")

    lines.append("## ¿Está aplicado v4?\n")
    marker_rows = [{"check": k, "ok": v} for k, v in sorted(v4.items())]
    lines.append(md_table(marker_rows, ["check", "ok"], 80))
    lines.append(f"\n**v4_aplicado_completo_por_marcadores:** `{v4_ok}`\n")

    lines.append("## Resumen numérico\n")
    lines.append(f"- Total runs analizadas: **{total}**")
    lines.append(f"- Corridas reales con ventanas/status real: **{len(real_runs)}** ({real_ratio}%)")
    lines.append(f"- Corridas vacías/sin ventanas reales: **{len(empty_runs)}** ({pct(len(empty_runs), total)}%)")
    lines.append(f"- No material / CGF: **{len(no_material)}** ({no_material_ratio}%)")
    lines.append(f"- Accepted for follow-up: **{len(accepted)}** ({accepted_ratio}%)")
    lines.append(f"- Promoted to baseline: **{len(promoted)}**")
    lines.append(f"- Errores operativos: **{len(op_errors)}**")
    lines.append(f"- Candidate generation failures CSV: **{len(cgf_rows)}**")
    lines.append(f"- Longest no_material streak: **{len(best_streak)}**")
    if best_streak:
        lines.append(f"  - Desde **{best_streak[0]['run_id']}** hasta **{best_streak[-1]['run_id']}**")
    lines.append("")

    lines.append("## Distribución por clasificación\n")
    lines.append(md_table([{"classification": k, "count": v} for k, v in class_counts.most_common()], ["classification", "count"], 50))

    lines.append("## Distribución por parent\n")
    lines.append(md_table([{"parent_run_id": k, "count": v} for k, v in parent_counts.most_common()], ["parent_run_id", "count"], 50))

    lines.append("## Distribución por ventanas\n")
    lines.append(md_table([{"executed_windows": k, "count": v} for k, v in windows_counts.most_common()], ["executed_windows", "count"], 50))

    lines.append("## Últimas corridas reales con métricas encontradas\n")
    lines.append(md_table(real_with_metrics[-30:], [
        "run_id", "classification", "parent_run_id", "executed_windows",
        "accepted_for_followup", "w52_avg_net_return_pct", "w52_spy_compare", "w52_pnl", "w52_trades",
        "candidate_family", "candidate_axis", "reason"
    ], 30))

    lines.append("## Accepted recientes\n")
    lines.append(md_table(accepted[-30:], [
        "run_id", "classification", "parent_run_id", "executed_windows",
        "w52_avg_net_return_pct", "w52_spy_compare", "w52_pnl", "w52_trades",
        "reason"
    ], 30))

    lines.append("## Últimas 60 corridas\n")
    lines.append(md_table(summaries[-60:], [
        "run_id", "classification", "status", "parent_run_id",
        "executed_windows", "accepted_for_followup", "promoted_to_baseline", "reason"
    ], 60))

    lines.append("## Diagnósticos v4 / agotamiento\n")
    if paths["cgf_csv"]:
        lines.append(f"- candidate_generation_failures.csv: `{paths['cgf_csv']}`")
    else:
        lines.append("- candidate_generation_failures.csv: `NO ENCONTRADO`")
    if paths["exhaustion_md"]:
        lines.append(f"- exhaustion diagnostic MD: `{paths['exhaustion_md']}`")
        lines.append("\n### Preview diagnostic MD\n")
        lines.append("```md")
        lines.append(read_text(paths["exhaustion_md"])[:5000])
        lines.append("```")
    else:
        lines.append("- exhaustion diagnostic MD: `NO ENCONTRADO`")
    if paths["exhaustion_json"]:
        lines.append(f"- exhaustion diagnostic JSON: `{paths['exhaustion_json']}`")
    else:
        lines.append("- exhaustion diagnostic JSON: `NO ENCONTRADO`")
    lines.append("")

    lines.append("## Archivos generados\n")
    lines.append("- `learning_status_report.md`")
    lines.append("- `latest_runs_learning_summary.csv`")
    lines.append("- `latest_real_runs.csv`")
    lines.append("- `latest_accepted_runs.csv`")
    lines.append("- `latest_operational_errors.csv`")
    lines.append("- `latest_no_material_runs.csv`")
    lines.append("- `selected_run_ids.txt`")
    lines.append("- `active_loop_processes.txt`")
    lines.append("")

    report = "\n".join(lines)
    (out_dir / "learning_status_report.md").write_text(report, encoding="utf-8")

    print("")
    print("OK - Auditoría generada")
    print(f"Veredicto: {verdict}")
    print(f"Reporte: {out_dir / 'learning_status_report.md'}")
    print(f"CSV principal: {out_dir / 'latest_runs_learning_summary.csv'}")
    print("")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        (out_dir / "audit_learning_status_error.txt").write_text(err, encoding="utf-8")
        print(err)
        sys.exit(1)
