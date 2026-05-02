import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd


def to_num(v):
    try:
        if v is None:
            return math.nan
        return float(v)
    except Exception:
        return math.nan


def as_int(v, default=0):
    n = to_num(v)
    if math.isnan(n):
        return int(default)
    return int(round(n))


def clean_float(v, default=math.nan):
    n = to_num(v)
    if math.isnan(n):
        return float(default)
    return float(n)


def load_sheet(path: Path, name: str) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=name)
    except Exception:
        return pd.DataFrame()


STEM_USECOLS = {
    "09_summary_total": [
        "regime_weeks_run",
        "weeks_allowed_to_trade",
        "weeks_skipped_by_gates",
        "real_trades_total",
        "avg_net_return_pct_total",
        "total_net_pnl_dollars",
        "wins_total",
        "losses_total",
        "none_total",
    ],
    "08_summary_by_regime_week": [
        "target_regime_signal_date",
        "current_entry_week_signal_date",
        "should_trade_week",
        "avg_net_return_pct",
        "spy_channel_r2_gate_pass",
        "avg_profile_distance_gate_pass",
    ],
    "07_next_week_real_trades": [
        "target_regime_signal_date",
        "net_return_pct",
        "net_pnl_dollars",
    ],
}


def _safe_read_csv(path: Path, usecols=None) -> pd.DataFrame:
    try:
        if usecols:
            try:
                header = pd.read_csv(path, sep=";", decimal=",", nrows=0).columns.tolist()
                existing = [c for c in usecols if c in header]
                if existing:
                    return pd.read_csv(path, sep=";", decimal=",", usecols=existing)
            except Exception:
                pass
        return pd.read_csv(path, sep=";", decimal=",")
    except Exception:
        return pd.DataFrame()


def load_latest_stem_csv(base_dir: Path, stem: str) -> pd.DataFrame:
    if base_dir is None or (not base_dir.exists()):
        return pd.DataFrame()
    try:
        files = sorted(base_dir.rglob(f"*_{stem}_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return pd.DataFrame()
        return _safe_read_csv(files[0], usecols=STEM_USECOLS.get(stem))
    except Exception:
        return pd.DataFrame()


_SPY_RETURNS_MEMORY_CACHE = {}


def _spy_returns_cache_path(weekly_csv: Path) -> Path:
    try:
        st = weekly_csv.stat()
        key_raw = f"{weekly_csv.resolve()}|{st.st_mtime_ns}|{st.st_size}"
    except Exception:
        key_raw = str(weekly_csv)
    key = hashlib.sha256(key_raw.encode("utf-8", errors="ignore")).hexdigest()[:16]
    cache_dir = Path.cwd() / "_dataset_cache" / "metrics"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"spy_weekly_returns_{key}.csv"


def load_spy_weekly_returns(weekly_csv: Path) -> pd.DataFrame:
    """Load SPY signal_date/ret_1w_pct from weekly master with disk cache.

    The extractor is launched as a separate process per window, so in-memory cache
    alone does not help. A tiny SPY-only cache avoids rescanning the large weekly
    master for every 4/8/24/52 metric extraction.
    """
    if not weekly_csv.exists():
        return pd.DataFrame()

    cache_path = _spy_returns_cache_path(weekly_csv)
    mem_key = str(cache_path.resolve())
    if mem_key in _SPY_RETURNS_MEMORY_CACHE:
        return _SPY_RETURNS_MEMORY_CACHE[mem_key].copy()

    if cache_path.exists():
        df = _safe_read_csv(cache_path, usecols=["signal_date", "ret_1w_pct"])
        if not df.empty:
            _SPY_RETURNS_MEMORY_CACHE[mem_key] = df
            return df.copy()

    cols = ["ticker", "signal_date", "ret_1w_pct"]
    parts = []
    try:
        for chunk in pd.read_csv(weekly_csv, usecols=cols, chunksize=200000):
            c = chunk[chunk["ticker"] == "SPY"].copy()
            if c.empty:
                continue
            c["signal_date"] = pd.to_datetime(c["signal_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            c["ret_1w_pct"] = pd.to_numeric(c["ret_1w_pct"], errors="coerce")
            c = c.dropna(subset=["signal_date"])[["signal_date", "ret_1w_pct"]]
            if not c.empty:
                parts.append(c)
    except Exception:
        return pd.DataFrame()

    if not parts:
        return pd.DataFrame()

    df = pd.concat(parts, ignore_index=True).drop_duplicates(subset=["signal_date"], keep="last")
    try:
        df.to_csv(cache_path, sep=";", decimal=",", index=False)
    except Exception:
        pass
    _SPY_RETURNS_MEMORY_CACHE[mem_key] = df
    return df.copy()


def compute_spy_compare(weekly_df: pd.DataFrame, weekly_csv: Path):
    if weekly_df.empty:
        return {"spy_avg_ret_1w_pct": math.nan, "spy_compare": math.nan, "spy_yearly_breakdown": []}
    if "current_entry_week_signal_date" not in weekly_df.columns:
        return {"spy_avg_ret_1w_pct": math.nan, "spy_compare": math.nan, "spy_yearly_breakdown": []}

    w = weekly_df.copy()
    if "should_trade_week" in w.columns:
        w["should_trade_week"] = pd.to_numeric(w["should_trade_week"], errors="coerce")
        w = w[w["should_trade_week"] == 1].copy()
    if w.empty:
        return {"spy_avg_ret_1w_pct": math.nan, "spy_compare": math.nan, "spy_yearly_breakdown": []}

    w["entry_date"] = pd.to_datetime(w["current_entry_week_signal_date"], errors="coerce")
    w = w.dropna(subset=["entry_date"]).copy()
    if w.empty:
        return {"spy_avg_ret_1w_pct": math.nan, "spy_compare": math.nan, "spy_yearly_breakdown": []}
    w["entry_key"] = w["entry_date"].dt.strftime("%Y-%m-%d")
    date_keys = set(w["entry_key"].tolist())

    spy_df = load_spy_weekly_returns(weekly_csv)
    if spy_df.empty:
        return {"spy_avg_ret_1w_pct": math.nan, "spy_compare": math.nan, "spy_yearly_breakdown": []}
    spy_df = spy_df[spy_df["signal_date"].isin(date_keys)].copy()
    if spy_df.empty:
        return {"spy_avg_ret_1w_pct": math.nan, "spy_compare": math.nan, "spy_yearly_breakdown": []}

    merged = w.merge(spy_df, left_on="entry_key", right_on="signal_date", how="left")
    merged["ret_1w_pct"] = pd.to_numeric(merged["ret_1w_pct"], errors="coerce")

    strategy_col = "avg_net_return_pct"
    if strategy_col in merged.columns:
        merged[strategy_col] = pd.to_numeric(merged[strategy_col], errors="coerce")
    else:
        merged[strategy_col] = math.nan

    spy_avg = clean_float(merged["ret_1w_pct"].mean(), math.nan)
    strat_avg = clean_float(merged[strategy_col].mean(), math.nan)
    spy_cmp = strat_avg - spy_avg if (math.isfinite(strat_avg) and math.isfinite(spy_avg)) else math.nan

    merged["year"] = merged["entry_date"].dt.year
    yearly = []
    for y, g in merged.groupby("year"):
        s_avg = clean_float(g[strategy_col].mean(), math.nan)
        b_avg = clean_float(g["ret_1w_pct"].mean(), math.nan)
        diff = s_avg - b_avg if (math.isfinite(s_avg) and math.isfinite(b_avg)) else math.nan
        yearly.append(
            {
                "year": int(y),
                "strategy_avg_net_return_pct": s_avg,
                "spy_avg_ret_1w_pct": b_avg,
                "diff_pct": diff,
            }
        )
    yearly = sorted(yearly, key=lambda x: x["year"])

    return {
        "spy_avg_ret_1w_pct": spy_avg,
        "spy_compare": spy_cmp,
        "spy_yearly_breakdown": yearly,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=False, default="")
    ap.add_argument("--base-dir", required=False, default="")
    ap.add_argument("--weekly-csv", required=True)
    ap.add_argument("--tie-low", type=float, default=0.0)
    ap.add_argument("--tie-high", type=float, default=1.0)
    ap.add_argument("--max-regime-weeks", type=int, default=0)
    args = ap.parse_args()

    xlsx = Path(args.xlsx) if str(args.xlsx).strip() else None
    base_dir = Path(args.base_dir) if str(args.base_dir).strip() else None
    weekly_csv = Path(args.weekly_csv)

    summary = pd.DataFrame()
    weekly = pd.DataFrame()
    trades = pd.DataFrame()
    if xlsx is not None and xlsx.exists():
        summary = load_sheet(xlsx, "09_summary_total")
        weekly = load_sheet(xlsx, "08_summary_by_regime_week")
        trades = load_sheet(xlsx, "07_next_week_real_trades")
    if summary.empty:
        summary = load_latest_stem_csv(base_dir, "09_summary_total")
    if weekly.empty:
        weekly = load_latest_stem_csv(base_dir, "08_summary_by_regime_week")
    if trades.empty:
        trades = load_latest_stem_csv(base_dir, "07_next_week_real_trades")

    max_weeks = int(args.max_regime_weeks or 0)
    use_prefix = max_weeks > 0 and (not weekly.empty)

    if use_prefix:
        w = weekly.copy()
        sort_col = "target_regime_signal_date" if "target_regime_signal_date" in w.columns else (
            "current_entry_week_signal_date" if "current_entry_week_signal_date" in w.columns else None
        )
        if sort_col:
            w["_sort_dt"] = pd.to_datetime(w[sort_col], errors="coerce")
            w = w.sort_values(["_sort_dt"], na_position="last").drop(columns=["_sort_dt"], errors="ignore")
        w = w.head(max_weeks).copy()

        weeks_run = int(len(w))
        if "should_trade_week" in w.columns:
            w["should_trade_week"] = pd.to_numeric(w["should_trade_week"], errors="coerce")
            weeks_traded = int((w["should_trade_week"] == 1).sum())
        else:
            weeks_traded = 0
        weeks_skipped = max(0, weeks_run - weeks_traded)

        allowed_dates = set()
        if "target_regime_signal_date" in w.columns:
            allowed_dates = set(pd.to_datetime(w["target_regime_signal_date"], errors="coerce").dt.strftime("%Y-%m-%d").dropna().tolist())

        t = trades.copy()
        if allowed_dates and "target_regime_signal_date" in t.columns:
            t_key = pd.to_datetime(t["target_regime_signal_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            t = t[t_key.isin(allowed_dates)].copy()

        trades_total = int(len(t))
        if "net_return_pct" in t.columns and not t.empty:
            ret = pd.to_numeric(t["net_return_pct"], errors="coerce")
            wins = int((ret > args.tie_high).fillna(False).sum())
            losses = int((ret < args.tie_low).fillna(False).sum())
            ties = int(((ret >= args.tie_low) & (ret <= args.tie_high)).fillna(False).sum())
            avg_net = clean_float(ret.mean(), math.nan)
            total_pnl = clean_float(pd.to_numeric(t.get("net_pnl_dollars"), errors="coerce").sum(), math.nan)
        else:
            wins = losses = ties = 0
            avg_net = math.nan
            total_pnl = math.nan
        weekly_for_spy = w
    else:
        row = summary.iloc[0].to_dict() if not summary.empty else {}

        weeks_run = as_int(row.get("regime_weeks_run"), 0)
        weeks_traded = as_int(row.get("weeks_allowed_to_trade"), 0)
        weeks_skipped = as_int(row.get("weeks_skipped_by_gates"), max(0, weeks_run - weeks_traded))
        trades_total = as_int(row.get("real_trades_total"), len(trades))
        avg_net = clean_float(row.get("avg_net_return_pct_total"), math.nan)
        total_pnl = clean_float(row.get("total_net_pnl_dollars"), math.nan)

        wins = as_int(row.get("wins_total"), 0)
        losses = as_int(row.get("losses_total"), 0)
        ties = as_int(row.get("none_total"), 0)
        if not trades.empty and "net_return_pct" in trades.columns:
            ret = pd.to_numeric(trades["net_return_pct"], errors="coerce")
            wins = int((ret > args.tie_high).fillna(False).sum())
            losses = int((ret < args.tie_low).fillna(False).sum())
            ties = int(((ret >= args.tie_low) & (ret <= args.tie_high)).fillna(False).sum())
        weekly_for_spy = weekly

    blocked_r2 = blocked_dist = blocked_both = blocked_r2_only = blocked_dist_only = 0
    if not weekly_for_spy.empty:
        weekly = weekly_for_spy
        if "spy_channel_r2_gate_pass" in weekly.columns:
            weekly["spy_channel_r2_gate_pass"] = pd.to_numeric(weekly["spy_channel_r2_gate_pass"], errors="coerce")
        if "avg_profile_distance_gate_pass" in weekly.columns:
            weekly["avg_profile_distance_gate_pass"] = pd.to_numeric(weekly["avg_profile_distance_gate_pass"], errors="coerce")
        if "spy_channel_r2_gate_pass" in weekly.columns:
            r2_fail = (weekly["spy_channel_r2_gate_pass"] != 1).fillna(True)
            blocked_r2 = int(r2_fail.sum())
        else:
            r2_fail = pd.Series([False] * len(weekly))
        if "avg_profile_distance_gate_pass" in weekly.columns:
            dist_fail = (weekly["avg_profile_distance_gate_pass"] != 1).fillna(True)
            blocked_dist = int(dist_fail.sum())
        else:
            dist_fail = pd.Series([False] * len(weekly))

        if len(r2_fail) == len(dist_fail) and len(r2_fail) > 0:
            blocked_both = int((r2_fail & dist_fail).sum())
            blocked_r2_only = int((r2_fail & (~dist_fail)).sum())
            blocked_dist_only = int((dist_fail & (~r2_fail)).sum())

    spy = compute_spy_compare(weekly_for_spy, weekly_csv)
    spy_compare = clean_float(spy.get("spy_compare"), math.nan)

    out = {
        "weeks_run": weeks_run,
        "weeks_traded": weeks_traded,
        "weeks_skipped_by_gates": weeks_skipped,
        "weeks_blocked_by_spy_channel_r2_gate": blocked_r2,
        "weeks_blocked_by_avg_profile_distance_gate": blocked_dist,
        "weeks_blocked_by_both_gates": blocked_both,
        "weeks_blocked_by_spy_channel_r2_only": blocked_r2_only,
        "weeks_blocked_by_avg_profile_distance_only": blocked_dist_only,
        "trades": trades_total,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "avg_net_return_pct": avg_net,
        "total_net_pnl_dollars": total_pnl,
        "spy_avg_ret_1w_pct": clean_float(spy.get("spy_avg_ret_1w_pct"), math.nan),
        "spy_compare": spy_compare,
        "spy_yearly_breakdown": spy.get("spy_yearly_breakdown", []),
    }
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
