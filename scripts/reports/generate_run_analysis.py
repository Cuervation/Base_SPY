from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def normalize_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    s = str(value).strip()
    if not s:
        return ""
    low = s.lower()
    if low in {"true", "false"}:
        return low
    n = to_float(s)
    if n is not None:
        if float(n).is_integer():
            return str(int(round(n)))
        return f"{float(n):.12g}"
    return s


def parse_run_num(run_id: str) -> Optional[int]:
    m = re.match(r"^EXP_(\d+)$", (run_id or "").strip())
    if not m:
        return None
    return int(m.group(1))


def fmt(value: Optional[float], digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_paths_config(repo: Path) -> Dict[str, Any]:
    cfg_path = (repo / "config" / "paths_config.json").resolve()
    data = read_json(cfg_path, {})
    return data if isinstance(data, dict) else {}


def cfg_get_str(cfg: Dict[str, Any], keys: List[str], default: str) -> str:
    cur: Any = cfg
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if isinstance(cur, str) and cur.strip() else default


def norm_anchor(anchor: Any) -> Dict[str, Any]:
    if not isinstance(anchor, dict):
        return {
            "active": False,
            "parameter": "",
            "value": None,
            "remaining_iterations": 0,
            "locked_by_duplicate_throttling": False,
        }
    return {
        "active": bool(anchor.get("active", False)),
        "parameter": str(anchor.get("parameter", "") or "").strip(),
        "value": anchor.get("value"),
        "remaining_iterations": int(to_float(anchor.get("remaining_iterations")) or 0),
        "locked_by_duplicate_throttling": bool(anchor.get("locked_by_duplicate_throttling", False)),
    }


def load_rows(experiment_log: Path) -> List[Dict[str, Any]]:
    if not experiment_log.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with experiment_log.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            row["_run_num"] = parse_run_num(row.get("run_id", ""))
            row["_w52_spy"] = to_float(row.get("w52_spy_compare"))
            row["_w52_pnl"] = to_float(row.get("w52_pnl"))
            rows.append(row)
    rows.sort(key=lambda r: (r["_run_num"] is None, r["_run_num"] or 0))
    return rows


def detect_exhausted_subspaces(
    rows: List[Dict[str, Any]],
    lookback: int = 15,
    min_repeats: int = 3,
    min_reject_ratio: float = 0.75,
) -> List[Dict[str, Any]]:
    recent = rows[-max(1, int(lookback)) :] if rows else []
    stats: Dict[tuple, Dict[str, Any]] = {}
    for r in recent:
        status = str(r.get("status", "") or "").strip()
        if status not in {"run_ok", "run_partial_valid"}:
            continue
        p = str(r.get("main_parameter", "") or "").strip()
        if not p:
            continue
        f = normalize_scalar(r.get("main_from"))
        t = normalize_scalar(r.get("main_to"))
        key = (p, f, t)
        if key not in stats:
            stats[key] = {
                "parameter": p,
                "from": f,
                "to": t,
                "count": 0,
                "accepted": 0,
                "rejected": 0,
                "run_ids": [],
            }
        e = stats[key]
        e["count"] += 1
        if str(r.get("accepted_or_rejected", "") or "").strip().lower() == "accepted":
            e["accepted"] += 1
        else:
            e["rejected"] += 1
        rid = str(r.get("run_id", "") or "").strip()
        if rid:
            e["run_ids"].append(rid)
    exhausted: List[Dict[str, Any]] = []
    for e in stats.values():
        cnt = int(e.get("count", 0))
        if cnt < int(min_repeats):
            continue
        rej = int(e.get("rejected", 0))
        ratio = (rej / cnt) if cnt > 0 else 0.0
        if ratio >= float(min_reject_ratio):
            exhausted.append(
                {
                    **e,
                    "reject_ratio": round(ratio, 4),
                }
            )
    exhausted.sort(key=lambda x: (-x.get("count", 0), -x.get("reject_ratio", 0.0), x.get("parameter", "")))
    return exhausted


def get_recent_no_useful_streak(rows: List[Dict[str, Any]], lookback: int = 10) -> int:
    recent = rows[-max(1, int(lookback)) :] if rows else []
    if not recent:
        return 0
    streak = 0
    for r in reversed(recent):
        if str(r.get("accepted_or_rejected", "") or "").strip().lower() == "accepted":
            break
        streak += 1
    return streak


def strong_rejected_runs(rows: List[Dict[str, Any]], lookback: int = 40, min_w52_spy: float = 2.0) -> List[Dict[str, Any]]:
    recent = rows[-max(1, int(lookback)) :] if rows else []
    out: List[Dict[str, Any]] = []
    for r in recent:
        status = str(r.get("status", "") or "").strip()
        if status not in {"run_ok", "run_partial_valid"}:
            continue
        if str(r.get("accepted_or_rejected", "") or "").strip().lower() != "rejected":
            continue
        spy = r.get("_w52_spy")
        if spy is None:
            continue
        if float(spy) >= float(min_w52_spy):
            out.append(r)
    out.sort(key=lambda x: (x.get("_w52_spy") is None, -(x.get("_w52_spy") or -9999)))
    return out[:10]


def acceptance_rate(rows: List[Dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    accepted = sum(1 for r in rows if str(r.get("accepted_or_rejected", "") or "").strip().lower() == "accepted")
    return accepted / len(rows) * 100.0


def avg_w52_spy(rows: List[Dict[str, Any]]) -> Optional[float]:
    vals = [r.get("_w52_spy") for r in rows if r.get("_w52_spy") is not None]
    return mean(vals) if vals else None


def top_parameter_effects(
    transitions: List[Dict[str, Any]],
    *,
    positive: bool,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    usable = [t for t in transitions if isinstance(t, dict)]
    if positive:
        classes = {"strong_positive", "mild_positive"}
        usable = [t for t in usable if str(t.get("current_effect_class", "") or "") in classes]
        usable.sort(
            key=lambda t: (
                to_float(t.get("avg_delta_w52_spy_compare")) is None,
                -(to_float(t.get("avg_delta_w52_spy_compare")) or -9999),
                -(to_float(t.get("accepted_count")) or 0),
            )
        )
    else:
        classes = {"harmful", "exhausted", "exhausted_no_effect"}
        usable = [t for t in usable if str(t.get("current_effect_class", "") or "") in classes]
        usable.sort(
            key=lambda t: (
                to_float(t.get("avg_delta_w52_spy_compare")) is None,
                (to_float(t.get("avg_delta_w52_spy_compare")) or 9999),
                -(to_float(t.get("rejected_count")) or 0),
            )
        )
    return usable[:limit]


def render_transition(t: Dict[str, Any]) -> str:
    return (
        f"`{t.get('parameter', '')}: {t.get('from_value', '')} -> {t.get('to_value', '')}` "
        f"class={t.get('current_effect_class', '-')} "
        f"attempts={int(to_float(t.get('total_attempts')) or 0)} "
        f"accepted={int(to_float(t.get('accepted_count')) or 0)} "
        f"rejected={int(to_float(t.get('rejected_count')) or 0)} "
        f"avg_delta_w52_spy={fmt(to_float(t.get('avg_delta_w52_spy_compare')))} "
        f"best={t.get('best_run_id', '-') or '-'}"
    )


def write_csv_snapshot(path: Path, rows: List[Dict[str, Any]]) -> None:
    fields = [
        "run_id",
        "date",
        "status",
        "accepted_or_rejected",
        "parent_run_id",
        "main_parameter",
        "main_from",
        "main_to",
        "w8_trades",
        "w24_trades",
        "w52_trades",
        "w8_pnl",
        "w24_pnl",
        "w52_pnl",
        "w8_spy_compare",
        "w24_spy_compare",
        "w52_spy_compare",
        "notes",
        "run_dir",
    ]
    last30 = rows[-30:]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        writer.writeheader()
        for row in last30:
            writer.writerow({k: row.get(k, "") for k in fields})


def write_markdown_report(
    path: Path,
    rows: List[Dict[str, Any]],
    baseline: Dict[str, Any],
    research: Dict[str, Any],
    watchdog: Dict[str, Any],
    champion_runs: Dict[str, Any],
    parameter_effect_memory: Dict[str, Any],
    subspace_cooldowns: Dict[str, Any],
) -> None:
    status_counts = Counter(r.get("status", "") for r in rows)
    decision_counts = Counter(r.get("accepted_or_rejected", "") for r in rows)
    valid_perf = [r for r in rows if r.get("status") in {"run_ok", "run_partial_valid"} and r.get("_w52_spy") is not None]
    best_spy = max(valid_perf, key=lambda r: r["_w52_spy"]) if valid_perf else None
    worst_spy = min(valid_perf, key=lambda r: r["_w52_spy"]) if valid_perf else None
    valid_pnl = [r for r in rows if r.get("_w52_pnl") is not None]
    best_pnl = max(valid_pnl, key=lambda r: r["_w52_pnl"]) if valid_pnl else None

    last15 = rows[-15:]
    last15_valid = [r for r in last15 if r.get("status") in {"run_ok", "run_partial_valid"} and r.get("_w52_spy") is not None]
    last15_avg_spy = mean([r["_w52_spy"] for r in last15_valid]) if last15_valid else None
    last15_accept_rate = (sum(1 for r in last15 if r.get("accepted_or_rejected") == "accepted") / len(last15) * 100.0) if last15 else 0.0
    no_useful_streak = get_recent_no_useful_streak(rows, lookback=10)

    state_tracking = baseline.get("state_tracking", {}) if isinstance(baseline.get("state_tracking"), dict) else {}
    branch_state = research.get("branch_state", {}) if isinstance(research.get("branch_state"), dict) else {}
    champions = champion_runs.get("champions", {}) if isinstance(champion_runs.get("champions"), dict) else {}
    champion_metadata = champion_runs.get("metadata", {}) if isinstance(champion_runs.get("metadata"), dict) else {}
    memory_transitions = parameter_effect_memory.get("transitions", []) if isinstance(parameter_effect_memory.get("transitions"), list) else []
    cooldown_entries = subspace_cooldowns.get("cooldowns", []) if isinstance(subspace_cooldowns.get("cooldowns"), list) else []
    active_cooldowns = [c for c in cooldown_entries if bool(c.get("cooldown_active", False))]
    mem_effect_counts = Counter(str((m.get("current_effect_class") or "neutral")).strip() for m in memory_transitions if isinstance(m, dict))
    top_positive = top_parameter_effects(memory_transitions, positive=True, limit=8)
    top_negative = top_parameter_effects(memory_transitions, positive=False, limit=8)

    watchdog_last_restart_reason = str(
        watchdog.get("last_restart_reason", watchdog.get("last_reason", "-")) or "-"
    ).strip() or "-"
    watchdog_restart_count_24h = int(to_float(watchdog.get("restart_count_last_24h")) or 0)
    watchdog_hard_stuck = bool(watchdog.get("hard_stuck_detected", False))
    watchdog_safe_mode = bool(watchdog.get("safe_mode_active", False))
    watchdog_last_success_at = str(watchdog.get("last_successful_iteration_at", "-") or "-")
    watchdog_health_class = str(watchdog.get("health_class", watchdog.get("last_decision", "-")) or "-")
    baseline_anchor = norm_anchor(baseline.get("branch_anchor"))
    research_anchor = norm_anchor(research.get("branch_anchor"))
    anchor_sync_ok = baseline_anchor == research_anchor
    baseline_updated = baseline.get("updated_at", "-")
    research_updated = research.get("updated_at", "-")
    last_promoted = str(state_tracking.get("last_promoted_baseline_run_id", "") or "").strip()
    exhausted_recent = detect_exhausted_subspaces(rows, lookback=15, min_repeats=3, min_reject_ratio=0.75)
    strong_rejected = strong_rejected_runs(rows, lookback=40, min_w52_spy=2.0)
    strong_not_promoted = [
        r for r in strong_rejected
        if str(r.get("run_id", "") or "").strip() != last_promoted
    ]
    previous15 = rows[-30:-15] if len(rows) > 15 else []
    previous15_accept_rate = acceptance_rate(previous15)
    previous15_avg_spy = avg_w52_spy(previous15)

    lines: List[str] = []
    lines.append("# Run Analysis (Current Snapshot)")
    lines.append("")
    lines.append(f"- Generated at: **{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}**")
    lines.append("")
    lines.append("## 1. General State")
    lines.append(f"- Total runs logged: **{len(rows)}**")
    lines.append(f"- Validation phase: **{baseline.get('validation_phase', '-')}**")
    lines.append(f"- Last useful run: **{state_tracking.get('last_useful_run_id', '-')}**")
    lines.append(f"- Last followup run: **{state_tracking.get('last_followup_run_id', '-') or '-'}**")
    lines.append(f"- Last promoted baseline: **{state_tracking.get('last_promoted_baseline_run_id', '-')}**")
    lines.append(f"- Branch health: **{branch_state.get('branch_health', '-')}**")
    lines.append(f"- Main friction: **{branch_state.get('main_friction', '-')}**")
    lines.append(f"- Recommended next action: **{branch_state.get('recommended_next_action', '-')}**")
    lines.append(f"- Current mode: **{branch_state.get('current_mode', '-') or '-'}**")
    lines.append(f"- Mode reason: **{branch_state.get('mode_reason', '-') or '-'}**")
    lines.append(f"- Previous mode: **{branch_state.get('previous_mode', '-') or '-'}**")
    lines.append(f"- Mode stability counter: **{int(to_float(branch_state.get('mode_stability_counter')) or 0)}**")
    lines.append(
        f"- Last mode change: **{branch_state.get('last_mode_change_at', '-') or '-'}** "
        f"(run_id={branch_state.get('last_mode_change_run_id', '-') or '-'})"
    )
    lines.append(f"- Baseline updated_at: **{baseline_updated}**")
    lines.append(f"- Research updated_at: **{research_updated}**")
    lines.append(f"- Watchdog health class: **{watchdog_health_class}**")
    lines.append(f"- Watchdog last restart reason: **{watchdog_last_restart_reason}**")
    lines.append(f"- Watchdog restart count (24h): **{watchdog_restart_count_24h}**")
    lines.append(f"- Watchdog hard_stuck_detected: **{int(watchdog_hard_stuck)}**")
    lines.append(f"- Watchdog safe_mode_active: **{int(watchdog_safe_mode)}**")
    lines.append(f"- Last successful iteration at: **{watchdog_last_success_at}**")
    lines.append(f"- Recent no-useful streak (max 10): **{no_useful_streak}**")
    lines.append(
        "- Branch anchor (persisted): "
        f"baseline=`{baseline_anchor.get('parameter','')}`/{baseline_anchor.get('value')} "
        f"(active={int(bool(baseline_anchor.get('active', False)))}, rem={baseline_anchor.get('remaining_iterations', 0)}) ; "
        f"research=`{research_anchor.get('parameter','')}`/{research_anchor.get('value')} "
        f"(active={int(bool(research_anchor.get('active', False)))}, rem={research_anchor.get('remaining_iterations', 0)}) ; "
        f"sync_ok={int(anchor_sync_ok)}"
    )
    lines.append("")
    lines.append("## 2. Champions / Memory")
    lines.append(f"- Champion best_w52_spy_compare: **{champions.get('best_w52_spy_compare_run_id', '-') or '-'}**")
    lines.append(f"- Champion balance_quality_frequency: **{champions.get('best_balance_quality_frequency_run_id', '-') or '-'}**")
    lines.append(f"- Champion multi_year_real: **{champions.get('best_multi_year_real_run_id', '-') or '-'}**")
    lines.append(f"- Champion orthogonal_exploration: **{champions.get('best_orthogonal_exploration_run_id', '-') or '-'}**")
    lines.append(f"- Champion recent_followup: **{champions.get('best_recent_followup_run_id', '-') or '-'}**")
    lines.append(f"- Parameter effect transitions tracked: **{len(memory_transitions)}**")
    lines.append(
        f"- Effect classes: strong_positive={mem_effect_counts.get('strong_positive', 0)}, "
        f"mild_positive={mem_effect_counts.get('mild_positive', 0)}, "
        f"neutral={mem_effect_counts.get('neutral', 0)}, "
        f"unstable={mem_effect_counts.get('unstable', 0)}, "
        f"exhausted={mem_effect_counts.get('exhausted', 0)}, "
        f"harmful={mem_effect_counts.get('harmful', 0)}"
    )
    lines.append(f"- Active cooldowns: **{len(active_cooldowns)}** / total cooldown entries: **{len(cooldown_entries)}**")
    lines.append(f"- Acceptance trend: last15=**{fmt(last15_accept_rate, 1)}%**, previous15=**{fmt(previous15_accept_rate, 1)}%**")
    lines.append(f"- Learning trend avg w52_spy: last15=**{fmt(last15_avg_spy)}**, previous15=**{fmt(previous15_avg_spy)}**")
    lines.append("")
    lines.append("### Active champions")
    for slot in [
        "best_w52_spy_compare_run_id",
        "best_balance_quality_frequency_run_id",
        "best_multi_year_real_run_id",
        "best_recent_followup_run_id",
        "best_orthogonal_exploration_run_id",
    ]:
        rid = champions.get(slot, "") or "-"
        meta = champion_metadata.get(slot, {}) if isinstance(champion_metadata.get(slot), dict) else {}
        why = meta.get("why_it_is_a_champion", meta.get("reason", "")) or "-"
        main = meta.get("main_change", "") or "-"
        reusable = int(bool(meta.get("reusable_parent", False)))
        lines.append(f"- `{slot}`: **{rid}** | reusable_parent={reusable} | {main} | {why}")
    lines.append("")
    lines.append("### Top positive parameter impacts")
    if top_positive:
        for t in top_positive:
            lines.append(f"- {render_transition(t)}")
    else:
        lines.append("- No hay parametros positivos persistidos con el criterio actual.")
    lines.append("")
    lines.append("### Top negative / exhausted parameter impacts")
    if top_negative:
        for t in top_negative:
            lines.append(f"- {render_transition(t)}")
    else:
        lines.append("- No hay parametros negativos persistidos con el criterio actual.")
    lines.append("")
    lines.append("### Subspaces in cooldown")
    if active_cooldowns:
        for c in active_cooldowns[:12]:
            lines.append(
                "- "
                f"`{c.get('parameter', '')}: {c.get('from_value', '')} -> {c.get('to_value', '')}` "
                f"until={c.get('cooldown_until_iteration', '-')} "
                f"reason={c.get('reason', '-') or '-'} "
                f"override_only_if={c.get('override_only_if', '-') or '-'}"
            )
    else:
        lines.append("- No hay subespacios en cooldown activo.")
    lines.append("")
    lines.append("## 3. Status Count")
    for key, val in sorted(status_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- `{key}`: **{val}**")
    lines.append("")
    lines.append("## 4. Acceptance")
    lines.append(f"- `accepted`: **{decision_counts.get('accepted', 0)}**")
    lines.append(f"- `rejected`: **{decision_counts.get('rejected', 0)}**")
    lines.append(f"- Acceptance rate (last 15): **{fmt(last15_accept_rate, 1)}%**")
    lines.append("")
    lines.append("## 5. 52w Performance")
    if best_spy:
        lines.append(f"- Best `w52_spy_compare`: **{fmt(best_spy.get('_w52_spy'))}** ({best_spy.get('run_id')})")
    if best_pnl:
        lines.append(f"- Best `w52_pnl`: **{fmt(best_pnl.get('_w52_pnl'), 1)}** ({best_pnl.get('run_id')})")
    if worst_spy:
        lines.append(f"- Worst `w52_spy_compare`: **{fmt(worst_spy.get('_w52_spy'))}** ({worst_spy.get('run_id')})")
    lines.append(f"- Avg `w52_spy_compare` (last 15 valid): **{fmt(last15_avg_spy)}**")
    lines.append("")
    lines.append("## 6. Last 15 Runs")
    lines.append("")
    lines.append("| run_id | status | accepted/rejected | main change | w52_trades | w52_pnl | w52_spy_compare |")
    lines.append("|---|---|---|---|---:|---:|---:|")
    for r in last15:
        if r.get("main_parameter"):
            main_change = f"{r.get('main_parameter')}: {r.get('main_from')} -> {r.get('main_to')}"
        else:
            main_change = "-"
        lines.append(
            f"| {r.get('run_id', '')} | {r.get('status', '')} | {r.get('accepted_or_rejected', '')} | {main_change} | "
            f"{r.get('w52_trades', '') or '-'} | {r.get('w52_pnl', '') or '-'} | {r.get('w52_spy_compare', '') or '-'} |"
        )

    lines.append("")
    lines.append("## 7. Subespacios agotados recientes (last 15)")
    if exhausted_recent:
        for e in exhausted_recent[:8]:
            lines.append(
                "- "
                f"`{e.get('parameter')}: {e.get('from')} -> {e.get('to')}` "
                f"repeticiones={e.get('count')} rechazadas={e.get('rejected')} "
                f"accept={e.get('accepted')} reject_ratio={fmt(to_float(e.get('reject_ratio')), 2)}"
            )
    else:
        lines.append("- No se detectaron subespacios agotados con criterio actual.")

    lines.append("")
    lines.append("## 8. Rechazos fuertes (w52_spy_compare alto)")
    if strong_rejected:
        lines.append("| run_id | status | main change | w52_spy_compare | w52_pnl |")
        lines.append("|---|---|---|---:|---:|")
        for r in strong_rejected[:8]:
            main_change = "-"
            if r.get("main_parameter"):
                main_change = f"{r.get('main_parameter')}: {r.get('main_from')} -> {r.get('main_to')}"
            lines.append(
                f"| {r.get('run_id','')} | {r.get('status','')} | {main_change} | "
                f"{r.get('w52_spy_compare','-')} | {r.get('w52_pnl','-')} |"
            )
    else:
        lines.append("- No hay rechazos recientes con w52_spy_compare alto.")

    lines.append("")
    lines.append("## 9. Corridas fuertes no convertidas a baseline")
    if strong_not_promoted:
        lines.append(
            f"- Ultimo baseline promovido: **{last_promoted or 'n/a'}**. "
            "Las siguientes corridas muestran senal 52w alta pero quedaron fuera de promocion:"
        )
        for r in strong_not_promoted[:6]:
            lines.append(
                f"- `{r.get('run_id','')}`: w52_spy_compare={r.get('w52_spy_compare','-')} "
                f"status={r.get('status','-')} accepted={r.get('accepted_or_rejected','-')}"
            )
    else:
        lines.append("- No se detectaron corridas fuertes pendientes de conversion en el rango analizado.")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compute_auditor_scores(last_runs: List[Dict[str, Any]]) -> Dict[str, float]:
    if not last_runs:
        return {
            "process_reliability_score": 0.0,
            "analyst_quality_score": 0.0,
            "coordinator_quality_score": 0.0,
            "research_effectiveness_score": 0.0,
            "overall_agent_score": 0.0,
        }

    total = len(last_runs)
    status_counts = Counter(r.get("status", "") for r in last_runs)
    accepted = sum(1 for r in last_runs if (r.get("accepted_or_rejected") or "").strip().lower() == "accepted")
    valid_52 = [r for r in last_runs if r.get("_w52_spy") is not None]
    improving_52 = [r for r in valid_52 if (r.get("_w52_spy") or -999) > 0]
    param_changes = sum(1 for r in last_runs if (r.get("main_parameter") or "").strip())
    duplicate_or_zigzag = status_counts.get("blocked_duplicate", 0) + status_counts.get("blocked_zigzag", 0)
    hard_errors = status_counts.get("run_error", 0)

    process = max(
        0.0,
        min(
            100.0,
            100.0
            - (hard_errors * 9.0)
            - (duplicate_or_zigzag * 3.0)
            - (status_counts.get("blocked_no_material_candidate", 0) * 2.5),
        ),
    )
    analyst = max(
        0.0,
        min(
            100.0,
            45.0
            + (param_changes / max(1, total) * 25.0)
            + (accepted / max(1, total) * 20.0)
            + (len(improving_52) / max(1, len(valid_52)) * 10.0 if valid_52 else 0.0),
        ),
    )
    coordinator = max(
        0.0,
        min(
            100.0,
            55.0
            + (accepted / max(1, total) * 20.0)
            - (duplicate_or_zigzag / max(1, total) * 30.0)
            - (hard_errors / max(1, total) * 20.0),
        ),
    )
    research = max(
        0.0,
        min(
            100.0,
            40.0
            + (accepted / max(1, total) * 20.0)
            + (len(improving_52) / max(1, len(valid_52)) * 40.0 if valid_52 else 0.0),
        ),
    )
    overall = round((process + analyst + coordinator + research) / 4.0, 2)

    return {
        "process_reliability_score": round(process, 2),
        "analyst_quality_score": round(analyst, 2),
        "coordinator_quality_score": round(coordinator, 2),
        "research_effectiveness_score": round(research, 2),
        "overall_agent_score": overall,
    }


def write_iteration_review(
    path: Path,
    rows: List[Dict[str, Any]],
    baseline: Dict[str, Any],
    research_state: Dict[str, Any],
    watchdog: Dict[str, Any],
) -> None:
    last15 = rows[-15:]
    status_counts = Counter(r.get("status", "") for r in last15)
    decision_counts = Counter(r.get("accepted_or_rejected", "") for r in last15)
    valid_52 = [r for r in last15 if r.get("_w52_spy") is not None]
    best_by_spy = sorted(valid_52, key=lambda r: r.get("_w52_spy") or -9999, reverse=True)[:5]
    worst_by_spy = sorted(valid_52, key=lambda r: r.get("_w52_spy") or 9999)[:5]
    accepted = [r for r in last15 if (r.get("accepted_or_rejected") or "").strip().lower() == "accepted"]
    blocked = [
        r for r in last15
        if (r.get("status") or "").startswith("blocked_")
    ]
    scores = compute_auditor_scores(last15)
    exhausted_recent = detect_exhausted_subspaces(last15, lookback=15, min_repeats=3, min_reject_ratio=0.75)
    strong_rejected_recent = strong_rejected_runs(last15, lookback=15, min_w52_spy=2.0)

    branch_state = research_state.get("branch_state", {}) if isinstance(research_state.get("branch_state"), dict) else {}
    baseline_state = baseline.get("state_tracking", {}) if isinstance(baseline.get("state_tracking"), dict) else {}
    baseline_anchor = norm_anchor(baseline.get("branch_anchor"))
    research_anchor = norm_anchor(research_state.get("branch_anchor"))
    anchor_sync_ok = baseline_anchor == research_anchor

    # Diagnostics for section 9
    next_changes: List[str] = []
    if status_counts.get("blocked_duplicate", 0) >= 2:
        next_changes.append("Reducir duplicados en proposal pool (throttle de propuestas repetidas).")
    if status_counts.get("blocked_no_material_candidate", 0) >= 2:
        next_changes.append("Forzar fallback de segunda capa antes de no_material_candidate_found.")
    if valid_52 and (sum(1 for r in valid_52 if (r.get("_w52_spy") or -9999) > 0) / len(valid_52) < 0.5):
        next_changes.append("Priorizar calidad de basket/rank sobre frecuencia para subir spy_compare en 52w.")
    if len(next_changes) < 3:
        next_changes.append("Extender validacion a 156 solo cuando 52w sea fuerte para ahorrar tiempo y ruido.")
    if len(next_changes) < 3:
        next_changes.append("Mantener anchor de parametro dominante 2-3 iteraciones para evitar whipsaw.")
    next_changes = next_changes[:3]

    # Section 6 and 7
    learned: List[str] = []
    not_working: List[str] = []
    if accepted:
        learned.append("Hubo corridas aceptadas para follow-up, el loop siguio generando evidencia util.")
    if valid_52:
        avg_spy = mean([(r.get("_w52_spy") or 0.0) for r in valid_52])
        learned.append(f"Promedio de w52_spy_compare en ultimas {len(valid_52)} validas: {avg_spy:.3f}.")
    if status_counts.get("run_partial_valid", 0) > 0:
        learned.append("Se preservo evidencia parcial cuando hubo validacion larga no completa.")

    if status_counts.get("blocked_duplicate", 0) > 0:
        not_working.append("Persisten bloqueos por duplicado que consumen iteraciones sin nueva evidencia.")
    if status_counts.get("blocked_zigzag", 0) > 0:
        not_working.append("Aparecen bloqueos zig-zag; revisar clasificacion para no frenar refinamientos validos.")
    if status_counts.get("blocked_no_material_candidate", 0) > 0:
        not_working.append("Hay estancamiento ocasional por falta de candidato material.")
    if exhausted_recent:
        tags = ", ".join([f"{e.get('parameter')}:{e.get('from')}->{e.get('to')}" for e in exhausted_recent[:3]])
        not_working.append(f"Subespacios agotados repetidos en bloque reciente: {tags}.")
    if strong_rejected_recent:
        not_working.append("Hay rechazos con w52_spy_compare alto: posible conversion suboptima de evidencia a follow-up/baseline.")
    if not valid_52:
        not_working.append("Falta senal suficiente en 52w dentro del bloque auditado.")

    if not learned:
        learned.append("No hay evidencia suficiente para afirmar aprendizaje solido en este bloque.")
    if not not_working:
        not_working.append("No se detectaron fricciones criticas de proceso en este bloque.")

    lines: List[str] = []
    lines.append("# iteration_review_last_15")
    lines.append("")
    lines.append("## 1. Executive summary")
    lines.append(f"- Corridas auditadas: **{len(last15)}**")
    lines.append(f"- Aceptadas: **{decision_counts.get('accepted', 0)}** | Rechazadas: **{decision_counts.get('rejected', 0)}**")
    lines.append(f"- Branch health (estado): **{branch_state.get('branch_health', 'n/a')}**")
    lines.append(f"- Main friction (estado): **{branch_state.get('main_friction', 'n/a')}**")
    lines.append(f"- Current mode (estado): **{branch_state.get('current_mode', 'n/a') or 'n/a'}**")
    lines.append(f"- Mode reason (estado): **{branch_state.get('mode_reason', 'n/a') or 'n/a'}**")
    lines.append(f"- Mode stability counter (estado): **{int(to_float(branch_state.get('mode_stability_counter')) or 0)}**")
    lines.append(f"- Watchdog health class: **{watchdog.get('health_class', watchdog.get('last_decision', 'n/a')) or 'n/a'}**")
    lines.append(f"- Watchdog safe_mode_active: **{int(bool(watchdog.get('safe_mode_active', False)))}**")
    lines.append(f"- Watchdog restart_count_last_24h: **{int(to_float(watchdog.get('restart_count_last_24h')) or 0)}**")
    lines.append(
        "- Branch anchor: "
        f"baseline=`{baseline_anchor.get('parameter','')}`/{baseline_anchor.get('value')} rem={baseline_anchor.get('remaining_iterations', 0)} ; "
        f"research=`{research_anchor.get('parameter','')}`/{research_anchor.get('value')} rem={research_anchor.get('remaining_iterations', 0)} ; "
        f"sync_ok={int(anchor_sync_ok)}"
    )
    lines.append("")
    lines.append("## 2. Que cambio en estas iteraciones")
    lines.append(f"- Ultimo baseline promovido: **{baseline_state.get('last_promoted_baseline_run_id', 'n/a')}**")
    lines.append(f"- Ultima corrida util: **{baseline_state.get('last_useful_run_id', 'n/a')}**")
    lines.append(f"- Distribucion de status: `{dict(status_counts)}`")
    lines.append("")
    lines.append("## 3. Tabla de corridas")
    lines.append("")
    lines.append("| run_id | parent_run_id | cambio principal | decision | followup | baseline | w24_spy | w52_spy | 156_status |")
    lines.append("|---|---|---|---|---|---|---:|---:|---|")
    for r in last15:
        main = "-"
        if r.get("main_parameter"):
            main = f"{r.get('main_parameter')}: {r.get('main_from')} -> {r.get('main_to')}"
        lines.append(
            f"| {r.get('run_id','n/a')} | {r.get('parent_run_id','n/a')} | {main} | {r.get('status','n/a')} | "
            f"{'yes' if (r.get('accepted_or_rejected') or '').strip().lower() == 'accepted' else 'no'} | "
            f"{'yes' if (r.get('accepted_or_rejected') or '').strip().lower() == 'accepted' and (r.get('run_id') == baseline_state.get('last_promoted_baseline_run_id')) else 'no'} | "
            f"{r.get('w24_spy_compare','n/a')} | {r.get('w52_spy_compare','n/a')} | {r.get('w156_status','n/a')} |"
        )
    lines.append("")
    lines.append("## 4. Mejores corridas")
    for r in best_by_spy[:3]:
        lines.append(f"- `{r.get('run_id')}`: w52_spy_compare={r.get('w52_spy_compare','n/a')}, status={r.get('status','n/a')}")
    if not best_by_spy:
        lines.append("- n/a")
    lines.append("")
    lines.append("## 5. Peores corridas")
    peores = [r for r in last15 if (r.get("status") in {"run_error", "blocked_duplicate", "blocked_zigzag", "blocked_no_material_candidate"})]
    peores = peores[:3] if peores else worst_by_spy[:3]
    for r in peores:
        lines.append(f"- `{r.get('run_id')}`: status={r.get('status','n/a')}, w52_spy_compare={r.get('w52_spy_compare','n/a')}")
    if not peores:
        lines.append("- n/a")
    lines.append("")
    lines.append("## 6. Que aprendio el sistema")
    for item in learned:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 7. Que no esta funcionando")
    for item in not_working:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 8. Evaluacion tipo auditor v2")
    lines.append(f"- process_reliability_score: **{scores['process_reliability_score']:.2f}**")
    lines.append(f"- analyst_quality_score: **{scores['analyst_quality_score']:.2f}**")
    lines.append(f"- coordinator_quality_score: **{scores['coordinator_quality_score']:.2f}**")
    lines.append(f"- research_effectiveness_score: **{scores['research_effectiveness_score']:.2f}**")
    lines.append(f"- overall_agent_score: **{scores['overall_agent_score']:.2f}**")
    lines.append("")
    lines.append("## 9. Proximos 3 cambios recomendados")
    for idx, rec in enumerate(next_changes, 1):
        lines.append(f"{idx}. {rec}")
    lines.append("")
    lines.append("## 10. Riesgos de seguir como esta")
    lines.append("- Riesgo de consumo de iteraciones por bloqueos administrativos (duplicate/zigzag/no_material).")
    lines.append("- Riesgo de sobreajuste corto si no se privilegia senal en 52w.")
    lines.append("- Riesgo de estancamiento de rama si no se alterna refine con exploracion ortogonal controlada.")
    if exhausted_recent:
        lines.append("- Riesgo de whipsaw parametrico por insistencia en subespacios agotados.")
    if strong_rejected_recent:
        lines.append("- Riesgo de perder aprendizaje util al rechazar corridas con senal 52w fuerte sin follow-up claro.")
    lines.append("")
    lines.append("> Nota: reporte generado automaticamente; los scores auditor v2 son estimados por heuristica sobre artefactos disponibles.")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate current run analysis report files.")
    ap.add_argument("--repo", default=".", help="Repository root path")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    cfg = load_paths_config(repo)

    experiment_log = repo / cfg_get_str(cfg, ["trackers", "experiment_log"], "trackers/experiment_log.csv")
    baseline_json = repo / cfg_get_str(cfg, ["state", "current_baseline"], "state/current_baseline.json")
    research_json = repo / cfg_get_str(cfg, ["state", "research_state"], "state/research_state.json")

    watchdog_dir = cfg_get_str(cfg, ["logs", "watchdog"], "logs/watchdog/multi_agent_watchdog_logs")
    watchdog_json = repo / watchdog_dir / "watchdog_health_state.json"

    legacy_champion_runs_json = cfg_get_str(
        cfg, ["runs", "champion_runs_json"], "runs/champion_runs/champion_runs.json"
    )
    champion_runs_json = repo / cfg_get_str(
        cfg, ["state", "champion_runs"], legacy_champion_runs_json
    )
    parameter_effect_memory_json = repo / cfg_get_str(
        cfg, ["state", "parameter_effect_memory"], "state/parameter_effect_memory.json"
    )
    subspace_cooldowns_json = repo / cfg_get_str(
        cfg, ["state", "subspace_cooldowns"], "state/subspace_cooldowns.json"
    )
    out_md = repo / "run_analysis_current.md"
    out_csv = repo / "run_analysis_current.csv"
    out_iteration_review = repo / "iteration_review_last_15.md"

    rows = load_rows(experiment_log)
    baseline = read_json(baseline_json, {})
    research = read_json(research_json, {})
    watchdog = read_json(watchdog_json, {})
    champion_runs = read_json(champion_runs_json, {})
    parameter_effect_memory = read_json(parameter_effect_memory_json, {})
    subspace_cooldowns = read_json(subspace_cooldowns_json, {})

    write_markdown_report(
        out_md,
        rows,
        baseline,
        research,
        watchdog,
        champion_runs,
        parameter_effect_memory,
        subspace_cooldowns,
    )
    write_csv_snapshot(out_csv, rows)
    write_iteration_review(out_iteration_review, rows, baseline, research, watchdog)

    print(f"WROTE_MD={out_md}")
    print(f"WROTE_CSV={out_csv}")
    print(f"WROTE_ITERATION_REVIEW={out_iteration_review}")
    print(f"ROWS={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
