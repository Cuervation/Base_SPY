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
out_dir.mkdir(parents=True, exist_ok=True)

RUN_RE = re.compile(r"\bEXP_\d+\b", re.IGNORECASE)

SKIP_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache",
    "node_modules", ".venv", "venv", "env",
    "backups", "backup", "dist", "build"
}

COMMON_JSON_FILES = [
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

def safe_read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            return Path(path).read_text(encoding="latin-1", errors="replace")
        except Exception:
            return ""

def safe_json(path):
    try:
        txt = safe_read_text(path)
        if not txt.strip():
            return None
        return json.loads(txt)
    except Exception:
        return None

def parse_dt(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("Z", "")
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
    m = re.search(r"EXP_(\d+)", str(run_id), re.I)
    return int(m.group(1)) if m else -1

def flatten_find(obj, keys):
    """
    Busca recursivamente el primer valor para alguna key.
    """
    if obj is None:
        return None
    wanted = {k.lower() for k in keys}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in wanted:
                return v
        for v in obj.values():
            found = flatten_find(v, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = flatten_find(item, keys)
            if found is not None:
                return found
    return None

def flatten_find_all(obj, keys):
    values = []
    wanted = {k.lower() for k in keys}
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if str(k).lower() in wanted:
                    values.append(v)
                walk(v)
        elif isinstance(x, list):
            for item in x:
                walk(item)
    walk(obj)
    return values

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
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in {"1", "true", "yes", "y", "si", "sí", "accepted", "promoted"}

def extract_run_id_from_obj(obj):
    v = flatten_find(obj, ["run_id", "experiment_id", "id"])
    if v:
        m = RUN_RE.search(str(v))
        if m:
            return m.group(0).upper()
    txt = stringify(obj)
    m = RUN_RE.search(txt)
    return m.group(0).upper() if m else ""

def classify_reason(*parts):
    text = " ".join(stringify(p) for p in parts if p is not None).lower()

    if "no_material" in text or "no material" in text:
        return "blocked_no_material_candidate"
    if "metric_no_effect" in text or "no effect" in text:
        return "metric_no_effect"
    if "blocked_no_op" in text or "no-op" in text or "noop" in text:
        return "blocked_no_op"
    if "zigzag" in text or "zig-zag" in text:
        return "blocked_zigzag"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "permission denied" in text or "access is denied" in text:
        return "permission_denied"
    if "coordinator_output_invalid" in text or "coordinator output invalid" in text:
        return "coordinator_output_invalid"
    if "parent_invalid" in text or "parent invalid" in text:
        return "parent_invalid"
    if "fix_process_before_more_research" in text:
        return "fix_process_before_more_research"
    if "pending_promotion" in text or "pending promotion" in text:
        return "pending_promotion_review"
    if "baseline_changed" in text or "baseline changed" in text:
        return "baseline_changed"
    if "run_partial_valid" in text:
        return "run_partial_valid"
    if "run_ok" in text:
        return "run_ok"
    if "rejected" in text:
        return "rejected"
    if "accepted_for_followup" in text:
        return "accepted_for_followup"
    if "promoted_to_baseline" in text:
        return "promoted_to_baseline"
    if "error" in text or "exception" in text or "traceback" in text:
        return "error_or_exception"

    return "unknown"

def discover_files():
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

    candidates = [
        repo / "state" / "autonomous_loop_state.json",
        repo / "autonomous_loop_state.json",
    ]
    paths["state"] = next((p for p in candidates if p.exists()), None)

    candidates = [
        repo / "reports" / "autonomous_loop_live_summary.md",
        repo / "autonomous_loop_live_summary.md",
    ]
    paths["live_summary"] = next((p for p in candidates if p.exists()), None)

    return paths

def read_experiment_log(path):
    rows = []
    if not path or not path.exists():
        return rows
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, 1):
                row = {str(k).strip(): v for k, v in row.items() if k is not None}
                txt = " ".join(stringify(v) for v in row.values())
                m = RUN_RE.search(txt)
                run_id = ""
                for key in ["run_id", "experiment_id", "id", "Run", "run"]:
                    if key in row and RUN_RE.search(str(row[key])):
                        run_id = RUN_RE.search(str(row[key])).group(0).upper()
                        break
                if not run_id and m:
                    run_id = m.group(0).upper()
                if not run_id:
                    continue

                ts = None
                for key in [
                    "created_at", "started_at", "updated_at", "finished_at",
                    "timestamp", "time", "datetime", "date"
                ]:
                    if key in row:
                        ts = parse_dt(row.get(key))
                        if ts:
                            break

                rows.append({
                    "source": "experiment_log",
                    "line": i,
                    "run_id": run_id,
                    "timestamp": ts,
                    "row": row,
                    "raw_text": txt,
                })
    except Exception as e:
        rows.append({
            "source": "experiment_log_error",
            "line": 0,
            "run_id": "",
            "timestamp": None,
            "row": {},
            "raw_text": f"{type(e).__name__}: {e}",
        })
    return rows

def read_loop_trace(path):
    rows = []
    if not path or not path.exists():
        return rows
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                raw = line.strip()
                if not raw:
                    continue
                obj = None
                try:
                    obj = json.loads(raw)
                except Exception:
                    obj = {"raw": raw}

                run_id = extract_run_id_from_obj(obj)
                if not run_id:
                    m = RUN_RE.search(raw)
                    run_id = m.group(0).upper() if m else ""
                if not run_id:
                    continue

                ts = None
                for key in ["timestamp", "ts", "time", "created_at", "updated_at", "started_at", "finished_at"]:
                    v = flatten_find(obj, [key])
                    ts = parse_dt(v)
                    if ts:
                        break

                rows.append({
                    "source": "loop_trace",
                    "line": i,
                    "run_id": run_id,
                    "timestamp": ts,
                    "obj": obj,
                    "raw_text": raw,
                })
    except Exception as e:
        rows.append({
            "source": "loop_trace_error",
            "line": 0,
            "run_id": "",
            "timestamp": None,
            "obj": {},
            "raw_text": f"{type(e).__name__}: {e}",
        })
    return rows

def index_run_dirs():
    """
    Indexa carpetas que contengan EXP_### en el nombre.
    """
    idx = defaultdict(list)

    roots_to_scan = [
        repo / "runs",
        repo / "reports",
        repo / "logs",
        repo / "experiments",
        repo / "outputs",
        repo / "state",
        repo,
    ]

    seen_roots = []
    for r in roots_to_scan:
        if r.exists() and r.is_dir() and r not in seen_roots:
            seen_roots.append(r)

    for root in seen_roots:
        for cur, dirs, files in os.walk(root):
            cur_path = Path(cur)

            parts_lower = {p.lower() for p in cur_path.parts}
            if parts_lower & SKIP_DIRS:
                dirs[:] = []
                continue

            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".git")]

            name = cur_path.name
            for m in RUN_RE.finditer(name):
                idx[m.group(0).upper()].append(cur_path)

            # También indexa si el path completo contiene EXP.
            full = str(cur_path)
            for m in RUN_RE.finditer(full):
                rid = m.group(0).upper()
                if cur_path not in idx[rid]:
                    idx[rid].append(cur_path)

    return idx

def read_run_artifacts(run_id, dir_index):
    result = {
        "run_id": run_id,
        "run_dirs": [],
        "json_files": {},
        "text_hits": {},
        "combined_text": "",
    }

    dirs = dir_index.get(run_id, [])
    # Priorizo carpetas más específicas.
    dirs = sorted(set(dirs), key=lambda p: (len(str(p)), str(p)))
    result["run_dirs"] = [str(p) for p in dirs[:10]]

    json_data = {}
    combined = []

    for d in dirs[:10]:
        if not d.exists() or not d.is_dir():
            continue

        for fname in COMMON_JSON_FILES:
            p = d / fname
            if p.exists():
                obj = safe_json(p)
                json_data[str(p.relative_to(repo))] = obj
                combined.append(f"\n\n--- {p.relative_to(repo)} ---\n{safe_read_text(p)[:20000]}")

        # logs chicos dentro de la carpeta
        for pattern in ["*.log", "*.txt", "*.md"]:
            for p in list(d.glob(pattern))[:20]:
                try:
                    size = p.stat().st_size
                    if size <= 2_000_000:
                        combined.append(f"\n\n--- {p.relative_to(repo)} ---\n{safe_read_text(p)[:20000]}")
                except Exception:
                    pass

    result["json_files"] = json_data
    result["combined_text"] = "\n".join(combined)
    return result

def summarize_run(run_id, log_entries, trace_entries, artifacts):
    raw_parts = []
    for e in log_entries:
        raw_parts.append(e.get("raw_text", ""))
        raw_parts.append(stringify(e.get("row", {})))
    for e in trace_entries:
        raw_parts.append(e.get("raw_text", ""))
        raw_parts.append(stringify(e.get("obj", {})))
    raw_parts.append(artifacts.get("combined_text", ""))

    all_text = "\n".join(raw_parts)

    json_objs = []
    for obj in artifacts.get("json_files", {}).values():
        if obj is not None:
            json_objs.append(obj)
    for e in trace_entries:
        obj = e.get("obj")
        if obj is not None:
            json_objs.append(obj)
    for e in log_entries:
        row = e.get("row")
        if row:
            json_objs.append(row)

    def first(keys):
        for obj in json_objs:
            v = flatten_find(obj, keys)
            if v not in [None, ""]:
                return v
        return None

    def all_values(keys):
        vals = []
        for obj in json_objs:
            vals.extend(flatten_find_all(obj, keys))
        return vals

    timestamps = []
    for e in log_entries + trace_entries:
        if e.get("timestamp"):
            timestamps.append(e["timestamp"])

    status = first(["status", "loop_status", "run_status", "final_status"])
    decision = first(["decision", "coordinator_decision", "final_decision"])
    reason = first([
        "reason", "stop_reason", "blocked_reason", "rejection_reason",
        "decision_reason", "recommended_next_action", "message", "error_type"
    ])

    parent = first(["parent_run_id", "current_parent_run_id", "baseline_parent_run_id"])
    candidate_family = first(["candidate_family", "family", "change_family", "proposal_family"])
    candidate_axis = first(["candidate_axis", "axis", "changed_key", "param_name", "parameter"])

    accepted = first(["accepted_for_followup"])
    promoted = first(["promoted_to_baseline"])
    baseline_changed = first(["baseline_changed"])
    do_not_use = first(["do_not_use_as_parent", "do_not_use_parent"])

    windows_vals = all_values(["executed_windows", "windows", "evaluation_windows"])
    windows = []
    for w in windows_vals:
        if isinstance(w, list):
            for x in w:
                if str(x).strip().isdigit():
                    windows.append(int(x))
        elif isinstance(w, str):
            for x in re.findall(r"\b\d+\b", w):
                windows.append(int(x))
    windows = sorted(set(windows))

    # fallback por texto
    if not windows:
        for m in re.finditer(r"\b(?:window|windows|ventanas|executed_windows)[^\n\r]{0,80}", all_text, re.I):
            for x in re.findall(r"\b\d+\b", m.group(0)):
                try:
                    windows.append(int(x))
                except Exception:
                    pass
        windows = sorted(set(windows))

    classification = classify_reason(status, decision, reason, all_text[:5000])

    has_error = any(x in all_text.lower() for x in ["traceback", "exception", "error", "permission denied", "timed out", "timeout"])
    has_timeout = any(x in all_text.lower() for x in ["timed out", "timeout"])
    has_permission = any(x in all_text.lower() for x in ["permission denied", "access is denied"])
    has_no_material = classification == "blocked_no_material_candidate" or "no_material" in all_text.lower() or "no material" in all_text.lower()

    run_dirs = artifacts.get("run_dirs", [])
    json_file_count = len([v for v in artifacts.get("json_files", {}).values() if v is not None])

    return {
        "run_id": run_id,
        "run_num": run_num(run_id),
        "first_seen": min(timestamps).isoformat(sep=" ") if timestamps else "",
        "last_seen": max(timestamps).isoformat(sep=" ") if timestamps else "",
        "status": stringify(status),
        "decision": stringify(decision),
        "reason": stringify(reason)[:500],
        "classification": classification,
        "parent_run_id": stringify(parent),
        "candidate_family": stringify(candidate_family),
        "candidate_axis": stringify(candidate_axis),
        "accepted_for_followup": stringify(accepted),
        "accepted_bool": boolish(accepted),
        "promoted_to_baseline": stringify(promoted),
        "promoted_bool": boolish(promoted),
        "baseline_changed": stringify(baseline_changed),
        "baseline_changed_bool": boolish(baseline_changed),
        "do_not_use_as_parent": stringify(do_not_use),
        "do_not_use_bool": boolish(do_not_use),
        "executed_windows": ",".join(map(str, windows)),
        "has_4w": 4 in windows,
        "has_8w": 8 in windows,
        "has_24w": 24 in windows,
        "has_52w": 52 in windows,
        "has_156w": 156 in windows,
        "has_error_text": has_error,
        "has_timeout_text": has_timeout,
        "has_permission_text": has_permission,
        "has_no_material_text": has_no_material,
        "run_dirs_found": len(run_dirs),
        "json_files_found": json_file_count,
        "sample_run_dir": run_dirs[0] if run_dirs else "",
    }

def longest_streak(rows, predicate):
    best = []
    cur = []
    for r in sorted(rows, key=lambda x: x["run_num"]):
        if predicate(r):
            cur.append(r)
            if len(cur) > len(best):
                best = cur[:]
        else:
            cur = []
    return best

def write_csv(path, rows, fieldnames=None):
    if not fieldnames:
        keys = []
        seen = set()
        for r in rows:
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        fieldnames = keys
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

def md_table(rows, headers, max_rows=30):
    if not rows:
        return "_Sin datos._\n"
    out = []
    out.append("| " + " | ".join(headers) + " |")
    out.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for r in rows[:max_rows]:
        vals = []
        for h in headers:
            v = stringify(r.get(h, ""))
            v = v.replace("\n", " ").replace("|", "\\|")
            if len(v) > 120:
                v = v[:117] + "..."
            vals.append(v)
        out.append("| " + " | ".join(vals) + " |")
    if len(rows) > max_rows:
        out.append(f"\n_Mostrando {max_rows} de {len(rows)} filas._")
    return "\n".join(out) + "\n"

def main():
    paths = discover_files()

    exp_rows = read_experiment_log(paths["experiment_log"])
    trace_rows = read_loop_trace(paths["loop_trace"])

    # Construyo timeline combinado.
    timeline = []
    for e in exp_rows:
        if e.get("run_id"):
            timeline.append({
                "run_id": e["run_id"],
                "timestamp": e.get("timestamp"),
                "source": "experiment_log",
                "line": e.get("line"),
                "raw_text": e.get("raw_text", ""),
            })
    for e in trace_rows:
        if e.get("run_id"):
            timeline.append({
                "run_id": e["run_id"],
                "timestamp": e.get("timestamp"),
                "source": "loop_trace",
                "line": e.get("line"),
                "raw_text": e.get("raw_text", ""),
            })

    # Orden: timestamp si hay, luego número de EXP, luego línea.
    timeline = sorted(
        timeline,
        key=lambda x: (
            x["timestamp"] or datetime.min,
            run_num(x["run_id"]),
            stringify(x.get("source")),
            int(x.get("line") or 0),
        )
    )

    # Últimos N run_id únicos según timeline.
    unique_order = []
    seen = set()
    for e in reversed(timeline):
        rid = e["run_id"]
        if rid not in seen:
            unique_order.append(rid)
            seen.add(rid)
        if len(unique_order) >= last_n:
            break
    selected_run_ids = list(reversed(unique_order))

    # Si faltan por timeline, uso números más altos del log.
    if len(selected_run_ids) < last_n:
        all_ids = sorted({e["run_id"] for e in timeline}, key=run_num)
        selected_run_ids = all_ids[-last_n:]

    exp_by_run = defaultdict(list)
    for e in exp_rows:
        if e.get("run_id"):
            exp_by_run[e["run_id"]].append(e)

    trace_by_run = defaultdict(list)
    for e in trace_rows:
        if e.get("run_id"):
            trace_by_run[e["run_id"]].append(e)

    print("Indexando carpetas de corridas...")
    dir_index = index_run_dirs()

    summaries = []
    for rid in selected_run_ids:
        artifacts = read_run_artifacts(rid, dir_index)
        summaries.append(summarize_run(rid, exp_by_run.get(rid, []), trace_by_run.get(rid, []), artifacts))

    summaries = sorted(summaries, key=lambda x: x["run_num"])

    # Duplicados.
    exp_counts = Counter(e["run_id"] for e in exp_rows if e.get("run_id"))
    trace_counts = Counter(e["run_id"] for e in trace_rows if e.get("run_id"))
    duplicate_rows = []
    for rid in sorted(set(exp_counts) | set(trace_counts), key=run_num):
        if exp_counts[rid] > 1 or trace_counts[rid] > 1:
            duplicate_rows.append({
                "run_id": rid,
                "experiment_log_count": exp_counts[rid],
                "loop_trace_count": trace_counts[rid],
            })

    # Streaks.
    no_material_streak = longest_streak(summaries, lambda r: r["classification"] == "blocked_no_material_candidate" or r["has_no_material_text"])
    no_run_dirs = [r for r in summaries if int(r["run_dirs_found"]) == 0]
    no_json = [r for r in summaries if int(r["json_files_found"]) == 0]
    real_runs = [r for r in summaries if r["has_4w"] or r["has_8w"] or r["has_24w"] or r["has_52w"]]
    empty_runs = [r for r in summaries if not (r["has_4w"] or r["has_8w"] or r["has_24w"] or r["has_52w"])]

    # Counters.
    c_class = Counter(r["classification"] for r in summaries)
    c_parent = Counter(r["parent_run_id"] or "(vacío)" for r in summaries)
    c_status = Counter(r["status"] or "(vacío)" for r in summaries)
    c_decision = Counter(r["decision"] or "(vacío)" for r in summaries)
    c_family = Counter(r["candidate_family"] or "(vacío)" for r in summaries)
    c_axis = Counter(r["candidate_axis"] or "(vacío)" for r in summaries)
    c_windows = Counter(r["executed_windows"] or "(sin ventanas)" for r in summaries)

    accepted = [r for r in summaries if r["accepted_bool"]]
    promoted = [r for r in summaries if r["promoted_bool"]]
    baseline_changed = [r for r in summaries if r["baseline_changed_bool"]]
    timeouts = [r for r in summaries if r["has_timeout_text"] or r["classification"] == "timeout"]
    permissions = [r for r in summaries if r["has_permission_text"] or r["classification"] == "permission_denied"]
    errors = [r for r in summaries if r["has_error_text"] or r["classification"] in {"error_or_exception", "permission_denied", "timeout"}]
    do_not_use = [r for r in summaries if r["do_not_use_bool"]]

    # Estado oficial.
    state_obj = safe_json(paths["state"]) if paths["state"] else None
    state_text = json.dumps(state_obj, ensure_ascii=False, indent=2) if state_obj is not None else ""
    state_last_run = stringify(flatten_find(state_obj, ["last_run_id"])) if state_obj else ""
    state_parent = stringify(flatten_find(state_obj, ["current_parent_run_id"])) if state_obj else ""
    state_status = stringify(flatten_find(state_obj, ["loop_status", "status"])) if state_obj else ""
    state_updated = stringify(flatten_find(state_obj, ["updated_at", "timestamp"])) if state_obj else ""

    last_selected = summaries[-1]["run_id"] if summaries else ""
    state_desync = bool(state_last_run and last_selected and state_last_run != last_selected)

    # CSVs.
    write_csv(out_dir / "last_runs_summary.csv", summaries)
    write_csv(out_dir / "duplicate_run_ids.csv", duplicate_rows)
    write_csv(out_dir / "runs_errors_or_timeouts.csv", errors)
    write_csv(out_dir / "runs_no_artifacts.csv", no_run_dirs)

    # Raw selected.
    with (out_dir / "selected_run_ids.txt").open("w", encoding="utf-8") as f:
        for rid in selected_run_ids:
            f.write(rid + "\n")

    # Report.
    report = []
    report.append(f"# Auditoría profunda últimas {last_n} corridas\n")
    report.append(f"- Repo: `{repo}`")
    report.append(f"- Generado: `{datetime.now().isoformat(sep=' ', timespec='seconds')}`")
    report.append(f"- Output: `{out_dir}`\n")

    report.append("## 1. Archivos leídos\n")
    for k, p in paths.items():
        report.append(f"- {k}: `{p if p else 'NO ENCONTRADO'}`")
    report.append("")

    report.append("## 2. Resumen ejecutivo\n")
    report.append(f"- Runs seleccionadas: **{len(summaries)}**")
    report.append(f"- Rango seleccionado: **{summaries[0]['run_id'] if summaries else ''} → {summaries[-1]['run_id'] if summaries else ''}**")
    report.append(f"- Corridas con ventanas reales detectadas: **{len(real_runs)}**")
    report.append(f"- Corridas sin ventanas reales detectadas: **{len(empty_runs)}**")
    report.append(f"- Accepted for follow-up: **{len(accepted)}**")
    report.append(f"- Promoted to baseline: **{len(promoted)}**")
    report.append(f"- Baseline changed: **{len(baseline_changed)}**")
    report.append(f"- Do not use as parent: **{len(do_not_use)}**")
    report.append(f"- Timeouts detectados: **{len(timeouts)}**")
    report.append(f"- Permission denied detectados: **{len(permissions)}**")
    report.append(f"- Errores/exception text detectados: **{len(errors)}**")
    report.append(f"- Duplicados globales en logs/trace: **{len(duplicate_rows)}**")
    report.append(f"- Longest streak no_material: **{len(no_material_streak)}**")
    if no_material_streak:
        report.append(f"  - Desde **{no_material_streak[0]['run_id']}** hasta **{no_material_streak[-1]['run_id']}**")
    report.append("")

    report.append("## 3. Estado oficial vs última corrida encontrada\n")
    report.append(f"- `autonomous_loop_state.last_run_id`: `{state_last_run}`")
    report.append(f"- Última corrida seleccionada: `{last_selected}`")
    report.append(f"- `current_parent_run_id`: `{state_parent}`")
    report.append(f"- `loop_status/status`: `{state_status}`")
    report.append(f"- `updated_at`: `{state_updated}`")
    report.append(f"- Desincronización estado/trace: **{'SÍ' if state_desync else 'NO'}**")
    report.append("")

    report.append("## 4. Distribución por clasificación\n")
    class_rows = [{"classification": k, "count": v} for k, v in c_class.most_common()]
    report.append(md_table(class_rows, ["classification", "count"], 50))

    report.append("## 5. Distribución por parent\n")
    parent_rows = [{"parent_run_id": k, "count": v} for k, v in c_parent.most_common()]
    report.append(md_table(parent_rows, ["parent_run_id", "count"], 50))

    report.append("## 6. Distribución por ventanas ejecutadas\n")
    win_rows = [{"executed_windows": k, "count": v} for k, v in c_windows.most_common()]
    report.append(md_table(win_rows, ["executed_windows", "count"], 50))

    report.append("## 7. Distribución por status\n")
    status_rows = [{"status": k, "count": v} for k, v in c_status.most_common()]
    report.append(md_table(status_rows, ["status", "count"], 50))

    report.append("## 8. Distribución por decision\n")
    decision_rows = [{"decision": k, "count": v} for k, v in c_decision.most_common()]
    report.append(md_table(decision_rows, ["decision", "count"], 50))

    report.append("## 9. Candidate family / axis\n")
    family_rows = [{"candidate_family": k, "count": v} for k, v in c_family.most_common()]
    axis_rows = [{"candidate_axis": k, "count": v} for k, v in c_axis.most_common()]
    report.append("### Family\n")
    report.append(md_table(family_rows, ["candidate_family", "count"], 50))
    report.append("### Axis\n")
    report.append(md_table(axis_rows, ["candidate_axis", "count"], 50))

    report.append("## 10. Corridas accepted/promoted/baseline_changed\n")
    report.append("### Accepted for follow-up\n")
    report.append(md_table(accepted, ["run_id", "classification", "parent_run_id", "executed_windows", "reason"], 50))
    report.append("### Promoted to baseline\n")
    report.append(md_table(promoted, ["run_id", "classification", "parent_run_id", "executed_windows", "reason"], 50))
    report.append("### Baseline changed\n")
    report.append(md_table(baseline_changed, ["run_id", "classification", "parent_run_id", "executed_windows", "reason"], 50))

    report.append("## 11. Errores, timeouts y permission denied\n")
    report.append(md_table(errors, ["run_id", "classification", "status", "decision", "reason", "sample_run_dir"], 80))

    report.append("## 12. Runs sin artifacts detectados\n")
    report.append(md_table(no_run_dirs, ["run_id", "classification", "status", "decision", "reason"], 80))

    report.append("## 13. Duplicados globales detectados\n")
    report.append(md_table(duplicate_rows, ["run_id", "experiment_log_count", "loop_trace_count"], 100))

    report.append("## 14. Últimas corridas auditadas\n")
    report.append(md_table(summaries[-50:], [
        "run_id", "classification", "parent_run_id", "executed_windows",
        "accepted_for_followup", "promoted_to_baseline", "reason"
    ], 50))

    report.append("## 15. Diagnóstico automático\n")
    if state_desync:
        report.append("- **ALERTA:** el estado oficial parece desincronizado contra la última corrida encontrada. Conviene correr `reconcile_loop_state.py --write` antes de seguir.")
    if len(no_material_streak) >= 25:
        report.append(f"- **ALERTA:** hay un streak muy largo de `blocked_no_material_candidate`: {len(no_material_streak)} corridas. El escape no está actuando o no alcanza.")
    elif len(no_material_streak) >= 5:
        report.append(f"- **Atención:** hay {len(no_material_streak)} `blocked_no_material_candidate` consecutivos. Debería activarse escape.")
    if len(accepted) == 0:
        report.append("- **ALERTA:** no hubo ninguna corrida accepted_for_followup en el rango auditado.")
    if len(real_runs) == 0:
        report.append("- **ALERTA:** no detecté ninguna corrida con ventanas reales. Puede estar generando EXP vacías.")
    if len(empty_runs) > len(summaries) * 0.7:
        report.append(f"- **ALERTA:** más del 70% de las corridas no tienen ventanas reales detectadas: {len(empty_runs)}/{len(summaries)}.")
    if len(permissions) > 0:
        report.append("- **ALERTA:** hay `Permission denied`; revisar safe_io/locks/procesos duplicados.")
    if len(timeouts) > 0:
        report.append("- Hay timeouts detectados; verificar que sean recuperables y no estén moviendo parent.")
    if len(duplicate_rows) > 0:
        report.append("- Hay run_id duplicados en logs/trace; revisar single-writer lock y procesos duplicados.")
    if len(set(r["parent_run_id"] for r in summaries if r["parent_run_id"])) == 1 and len(summaries) >= 20:
        only_parent = next(iter(set(r["parent_run_id"] for r in summaries if r["parent_run_id"])))
        report.append(f"- Parent congelado: todas las corridas con parent detectado usan `{only_parent}`.")
    report.append("")

    report.append("## 16. Archivos generados\n")
    report.append("- `last_runs_summary.csv`: tabla principal por corrida.")
    report.append("- `duplicate_run_ids.csv`: duplicados detectados.")
    report.append("- `runs_errors_or_timeouts.csv`: errores/timeouts/permission denied.")
    report.append("- `runs_no_artifacts.csv`: corridas sin carpeta/artifacts detectados.")
    report.append("- `selected_run_ids.txt`: run ids auditados.")
    report.append("")

    report_text = "\n".join(report)
    (out_dir / "deep_audit_report.md").write_text(report_text, encoding="utf-8")

    # También guardo estado oficial completo si existe.
    if state_text:
        (out_dir / "autonomous_loop_state_snapshot.json").write_text(state_text, encoding="utf-8")

    print("")
    print("OK - Auditoría generada")
    print(f"Reporte MD: {out_dir / 'deep_audit_report.md'}")
    print(f"CSV principal: {out_dir / 'last_runs_summary.csv'}")
    print(f"Duplicados: {out_dir / 'duplicate_run_ids.csv'}")
    print(f"Errores: {out_dir / 'runs_errors_or_timeouts.csv'}")
    print("")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        (out_dir / "deep_audit_error.txt").write_text(err, encoding="utf-8")
        print(err)
        sys.exit(1)
