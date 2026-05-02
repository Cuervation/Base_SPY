#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import cProfile
import hashlib
import json
import os
import pstats
import re
import threading
import time
import warnings

import numpy as np
import pandas as pd
from openpyxl import load_workbook

warnings.simplefilter("ignore", category=FutureWarning)

# =============================================================================
# CONFIG
# =============================================================================

WEEKLY_MASTER_FILE = r"C:\Pythons\ML-Trading\Base_Archivos_SPY\sp500_feature_store_weekly_master_all_260330223625.csv"
DAILY_MASTER_GLOB = r"C:\Pythons\ML-Trading\Base_Archivos_SPY\sp500_feature_store_daily_master_*.csv"

OUTPUT_DIR = r"C:\Pythons\ML-Trading\Base_Archivos_SPY"
OUTPUT_PREFIX = "spy_context_asset_profile_first_week_global_profile_v2"
OUTPUT_IN_TIMESTAMP_SUBDIR = True

# Se testea SOLO la primera semana de régimen SPY dentro de este rango
TEST_START = "2025-01-01"
TEST_END = "2025-12-31"
# Cantidad de semanas de régimen SPY a correr.
# 1 = solo la primera, 2 = primeras dos, etc.
# None = correr todas las semanas válidas del rango.
REGIME_WEEKS_TO_RUN = 52
ENABLE_SPY_CHANNEL_R2_GATE = True
MIN_SPY_CHANNEL_R2 = 0.55
ENABLE_AVG_PROFILE_DISTANCE_GATE = True
MAX_AVG_PROFILE_DISTANCE = 0.20

HIST_START = "2020-01-01"
HIST_END = "2024-12-31"

REQUIRE_NEXT_WEEK_WITHIN_TEST_RANGE = False
PARALLEL_REGIME_WORKERS = 2

ENTRY_MODE = "signal_close"   # signal_close | next_open
EXITS_START_NEXT_BAR = True

# Ladder / trailing stop:
# inicio: TP +5% y SL -5%
# al tocar +5% => nuevo SL +1% y nuevo TP +10%
# al tocar +10% => nuevo SL +5% y nuevo TP +15%
# al tocar +15% => nuevo SL +10% y nuevo TP +20%
# y así sucesivamente en pasos de 5 puntos porcentuales.
INITIAL_TP_PCT = 0.05
INITIAL_SL_PCT = 0.05
FIRST_LOCKED_SL_PCT = 0.01
TRAIL_STEP_PCT = 0.05

INTRADAY_PRIORITY = "stop"
MAX_HOLD_TRADING_DAYS = 100
COMMISSION_PCT_PER_SIDE = 0.24
CAPITAL_PER_TRADE = 500.0

TOP_SIMILAR_SPY_WEEKS = 20
MIN_SIMILAR_WEEKS_REQUIRED = 5

# Excluir estos tickers del universo de candidatos actuales
EXCLUDED_CURRENT_TICKERS = {"SPY"}

# Filtro adicional del candidato individual
ENABLE_CLOSE_VS_SMA50_FILTER = False
MAX_CLOSE_VS_SMA50_PCT = 1.5

# Tomar solo los 5 más cercanos al perfil global
TOP_CANDIDATES_NEXT_WEEK = 5

# Familia de estrategia para seleccion de basket:
# - profile_match: perfil global historico de ganadores (default)
# - momentum_rank: ranking cross-sectional de momentum en semana de entrada
STRATEGY_FAMILY = "profile_match"

# Parametros de la familia momentum_rank
MOMENTUM_MIN_RET_4W_PCT = -5.0
MOMENTUM_MAX_CLOSE_VS_SMA20W_PCT = 25.0
MOMENTUM_W_RET_4W = 0.45
MOMENTUM_W_RET_8W = 0.35
MOMENTUM_W_TREND = 0.20

SPY_VARS = [
    "spy_channel_r2",
    "spy_channel_slope_pct",
    "spy_close_vs_sma50_pct",
    "spy_close_sma_50_slope_5d_pct",
]

# Variables del perfil activables por flag (el analista puede sumar/quitar sin reescribir la arquitectura).
ENABLE_VAR_CHANNEL_R2 = True
ENABLE_VAR_CHANNEL_SLOPE_PCT = True
ENABLE_VAR_CLOSE_VS_SMA50_PCT = True
ENABLE_VAR_CLOSE_SMA_50_SLOPE_5D_PCT = True
ENABLE_VAR_WEEKLY_RANGE_PCT = True
ENABLE_VAR_RET_2W_PCT = True
ENABLE_VAR_CLOSE_VS_SMA4W_PCT = True

# Variables nuevas opcionales para exploracion adaptativa:
ENABLE_VAR_RET_4W_PCT = False
ENABLE_VAR_CLOSE_VS_SMA8W_PCT = False
ENABLE_VAR_CLOSE_VS_SMA20W_PCT = False
ENABLE_VAR_ATR_14W_PCT = False
ENABLE_VAR_VOLUME_RATIO_VS_SMA13W = False
ENABLE_VAR_DIST_TO_HIGH_26W_PCT = False

PROFILE_VAR_SWITCHES = [
    ("channel_r2", ENABLE_VAR_CHANNEL_R2),
    ("channel_slope_pct", ENABLE_VAR_CHANNEL_SLOPE_PCT),
    ("close_vs_sma50_pct", ENABLE_VAR_CLOSE_VS_SMA50_PCT),
    ("close_sma_50_slope_5d_pct", ENABLE_VAR_CLOSE_SMA_50_SLOPE_5D_PCT),
    ("weekly_range_pct", ENABLE_VAR_WEEKLY_RANGE_PCT),
    ("ret_2w_pct", ENABLE_VAR_RET_2W_PCT),
    ("close_vs_sma4w_pct", ENABLE_VAR_CLOSE_VS_SMA4W_PCT),
    ("ret_4w_pct", ENABLE_VAR_RET_4W_PCT),
    ("close_vs_sma8w_pct", ENABLE_VAR_CLOSE_VS_SMA8W_PCT),
    ("close_vs_sma20w_pct", ENABLE_VAR_CLOSE_VS_SMA20W_PCT),
    ("atr_14w_pct", ENABLE_VAR_ATR_14W_PCT),
    ("volume_ratio_vs_sma13w", ENABLE_VAR_VOLUME_RATIO_VS_SMA13W),
    ("dist_to_high_26w_pct", ENABLE_VAR_DIST_TO_HIGH_26W_PCT),
]
PROFILE_VARS = [name for name, enabled in PROFILE_VAR_SWITCHES if bool(enabled)]
if len(PROFILE_VARS) == 0:
    # Guardrail: evitar perfil vacio por desactivar todo accidentalmente.
    PROFILE_VARS = ["channel_r2", "channel_slope_pct", "close_vs_sma50_pct", "close_sma_50_slope_5d_pct"]

# Cómo validar si el activo actual se parece al perfil global ganador
PROFILE_MODE = "p25_p75"      # p25_p75 | zscore_distance
PROFILE_EXPANSION_FACTOR = 0.10
MAX_PROFILE_ZDIST = 1.8

EXPORT_SUMMARY_XLSX = True
EXPORT_SHEETS_INFO_TXT = True
EXPORT_CSVS_INCLUDED_IN_XLSX = False
SEPARATE_STEM_IN_CSV = "03_hist_trades"
FORCE_DECIMAL_COMMA_IN_XLSX = False
SUMMARY_XLSX_BASENAME = "spy_context_asset_profile_resumen"
SHEETS_INFO_TXT_BASENAME = "spy_context_asset_profile_solapas_info"

# Cache persistente de trades historicos (solo performance, sin cambiar logica).
TRADE_CACHE_DIRNAME = "_trade_cache"
TRADE_CACHE_FILE_PREFIX = "hist_trade_cache"
TRADE_CACHE_ROOT_DIR = ""

# Cache de datasets para evitar parseo CSV repetido.
DATASET_CACHE_DIRNAME = "_dataset_cache"
ENABLE_DATASET_PARQUET_CACHE = True

# Precompute incremental de trades historicos faltantes.
ENABLE_PRECOMPUTE_HIST_TRADES = True
PRECOMPUTE_WORKERS = 4

# Ajuste dinamico de workers.
AUTO_PARALLEL_WORKERS = True
MAX_PARALLEL_WORKERS_CAP = 8

# Profiling opcional (solo performance/diagnostico, sin cambiar logica).
ENABLE_RUNTIME_PROFILING = str(os.getenv("SPY_ENABLE_PROFILE", "0")).strip().lower() in {"1", "true", "yes"}
PROFILE_TOP_N = int(str(os.getenv("SPY_PROFILE_TOP_N", "20")).strip() or "20")

# =============================================================================
# HELPERS
# =============================================================================

def ts_now() -> str:
    return datetime.now().strftime("%y%m%d%H%M%S")


def folder_ts_now() -> str:
    return datetime.now().strftime("%y%m%d%H%M")


def clean_float(x) -> float:
    try:
        if x is None or (isinstance(x, str) and x.strip() == ""):
            return float("nan")
        return float(x)
    except Exception:
        return float("nan")


def safe_to_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def normalize_signal_date_key(value: Any) -> Optional[str]:
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return None
    return str(pd.Timestamp(dt).normalize().date())


def get_trade_engine_signature() -> Dict[str, Any]:
    # Solo parametros que afectan resultado del trade simulado.
    return {
        "ENTRY_MODE": ENTRY_MODE,
        "EXITS_START_NEXT_BAR": bool(EXITS_START_NEXT_BAR),
        "INITIAL_TP_PCT": float(INITIAL_TP_PCT),
        "INITIAL_SL_PCT": float(INITIAL_SL_PCT),
        "FIRST_LOCKED_SL_PCT": float(FIRST_LOCKED_SL_PCT),
        "TRAIL_STEP_PCT": float(TRAIL_STEP_PCT),
        "INTRADAY_PRIORITY": INTRADAY_PRIORITY,
        "MAX_HOLD_TRADING_DAYS": int(MAX_HOLD_TRADING_DAYS),
        "COMMISSION_PCT_PER_SIDE": float(COMMISSION_PCT_PER_SIDE),
        "CAPITAL_PER_TRADE": float(CAPITAL_PER_TRADE),
    }


def compute_trade_engine_hash() -> str:
    payload = json.dumps(get_trade_engine_signature(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def required_weekly_columns() -> List[str]:
    cols = {
        "signal_date",
        "ticker",
        "close",
        "open",
        "high",
        "low",
        "close_vs_sma50_pct",
        "ret_4w_pct",
        "ret_8w_pct",
        "close_vs_sma20w_pct",
        "spy_channel_r2_gate_pass",
        "avg_profile_distance_gate_pass",
    }
    cols.update(SPY_VARS)
    cols.update(PROFILE_VARS)
    return sorted(list(cols))


def required_daily_columns() -> List[str]:
    return ["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]


def compute_dataset_fingerprint(weekly_path: str, daily_glob: str) -> str:
    parts: List[str] = []
    try:
        wp = Path(weekly_path)
        if wp.exists():
            st = wp.stat()
            parts.append(f"w:{wp.name}:{int(st.st_mtime)}:{int(st.st_size)}")
    except Exception:
        pass
    try:
        daily_paths = sorted(Path(daily_glob).parent.glob(Path(daily_glob).name))
        for p in daily_paths:
            try:
                st = p.stat()
                parts.append(f"d:{p.name}:{int(st.st_mtime)}:{int(st.st_size)}")
            except Exception:
                continue
    except Exception:
        pass
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest() if payload else "nofingerprint"


def resolve_global_trade_cache_dir() -> Path:
    if str(TRADE_CACHE_ROOT_DIR).strip():
        return ensure_dir(TRADE_CACHE_ROOT_DIR)
    base = Path(WEEKLY_MASTER_FILE).resolve().parent
    return ensure_dir(base / TRADE_CACHE_DIRNAME)


def resolve_dataset_cache_dir() -> Path:
    base = Path(WEEKLY_MASTER_FILE).resolve().parent
    return ensure_dir(base / DATASET_CACHE_DIRNAME)


class HistoricalTradeCache:
    def __init__(self, cache_dir: Path, trade_engine_hash: str, data_fingerprint: str) -> None:
        self.cache_dir = ensure_dir(cache_dir)
        self.trade_engine_hash = trade_engine_hash
        self.data_fingerprint = str(data_fingerprint)
        self.cache_file = self.cache_dir / f"{TRADE_CACHE_FILE_PREFIX}_{trade_engine_hash[:12]}_{self.data_fingerprint[:12]}.parquet"

        self._cache: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self._disk_keys: set[Tuple[str, str, str]] = set()
        self._new_rows: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

        self.cache_loaded_rows = 0
        self.cache_hits_memory = 0
        self.cache_hits_disk = 0
        self.cache_misses = 0
        self.cache_new_rows_written = 0

    def _make_key(self, ticker: str, entry_signal_date: str) -> Tuple[str, str, str]:
        return (f"{self.trade_engine_hash}:{self.data_fingerprint}", str(ticker), str(entry_signal_date))

    def has(self, ticker: str, entry_signal_date: Any) -> bool:
        entry_key = normalize_signal_date_key(entry_signal_date)
        if entry_key is None:
            return False
        key = self._make_key(str(ticker), entry_key)
        with self._lock:
            return key in self._cache

    def load(self) -> None:
        if not self.cache_file.exists():
            return
        try:
            df = pd.read_parquet(self.cache_file)
        except Exception as e:
            print(f"[CACHE] warning: no pude cargar parquet ({self.cache_file.name}): {e}", flush=True)
            return
        if df is None or df.empty:
            return

        required = {"trade_engine_hash", "data_fingerprint", "ticker", "entry_signal_date", "payload_json"}
        if not required.issubset(set(df.columns)):
            print(f"[CACHE] warning: estructura invalida en {self.cache_file.name}; ignorando cache", flush=True)
            return

        df = df[df["trade_engine_hash"].astype(str) == str(self.trade_engine_hash)].copy()
        df = df[df["data_fingerprint"].astype(str) == str(self.data_fingerprint)].copy()
        loaded = 0
        for row in df.itertuples(index=False):
            ticker = str(getattr(row, "ticker", "")).strip()
            entry_signal_date = str(getattr(row, "entry_signal_date", "")).strip()
            payload_json = getattr(row, "payload_json", "")
            if not ticker or not entry_signal_date:
                continue
            try:
                payload = json.loads(payload_json) if isinstance(payload_json, str) else {}
            except Exception:
                continue
            key = self._make_key(ticker, entry_signal_date)
            self._cache[key] = payload
            self._disk_keys.add(key)
            loaded += 1

        self.cache_loaded_rows = int(loaded)

    def get(self, ticker: str, entry_signal_date: Any) -> Optional[Dict[str, Any]]:
        entry_key = normalize_signal_date_key(entry_signal_date)
        if entry_key is None:
            return None
        key = self._make_key(str(ticker), entry_key)
        with self._lock:
            payload = self._cache.get(key)
            if payload is None:
                self.cache_misses += 1
                return None
            if key in self._disk_keys:
                self.cache_hits_disk += 1
            else:
                self.cache_hits_memory += 1
            return dict(payload)

    def put(self, ticker: str, entry_signal_date: Any, payload: Dict[str, Any]) -> None:
        entry_key = normalize_signal_date_key(entry_signal_date)
        if entry_key is None:
            return
        key = self._make_key(str(ticker), entry_key)
        payload_copy = dict(payload)
        try:
            payload_json = json.dumps(payload_copy, ensure_ascii=False, sort_keys=True, allow_nan=True)
        except Exception:
            return

        with self._lock:
            if key in self._cache:
                return
            self._cache[key] = payload_copy
            self._new_rows.append(
                {
                    "trade_engine_hash": self.trade_engine_hash,
                    "data_fingerprint": self.data_fingerprint,
                    "ticker": str(ticker),
                    "entry_signal_date": entry_key,
                    "payload_json": payload_json,
                }
            )

    def persist(self) -> int:
        with self._lock:
            pending = list(self._new_rows)
            self._new_rows = []

        if not pending:
            self.cache_new_rows_written = 0
            return 0

        cols = ["trade_engine_hash", "data_fingerprint", "ticker", "entry_signal_date", "payload_json"]
        new_df = pd.DataFrame(pending)
        for c in cols:
            if c not in new_df.columns:
                new_df[c] = ""
        new_df = new_df[cols]

        if self.cache_file.exists():
            try:
                old_df = pd.read_parquet(self.cache_file)
            except Exception:
                old_df = pd.DataFrame(columns=cols)
        else:
            old_df = pd.DataFrame(columns=cols)

        for c in cols:
            if c not in old_df.columns:
                old_df[c] = ""
        old_df = old_df[cols]

        subset = ["trade_engine_hash", "data_fingerprint", "ticker", "entry_signal_date"]
        before = int(len(old_df.drop_duplicates(subset=subset)))
        merged = pd.concat([old_df, new_df], ignore_index=True)
        merged = merged.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)

        try:
            merged.to_parquet(self.cache_file, index=False)
        except Exception as e:
            with self._lock:
                self._new_rows = pending + self._new_rows
            print(f"[CACHE] warning: no pude persistir parquet ({self.cache_file.name}): {e}", flush=True)
            self.cache_new_rows_written = 0
            return 0

        written = max(int(len(merged)) - before, 0)
        self.cache_new_rows_written = written
        return written


def weighted_zdistance(row: pd.Series, target: pd.Series, stds: pd.Series) -> float:
    vals = []
    for col in SPY_VARS:
        r = clean_float(row.get(col, np.nan))
        t = clean_float(target.get(col, np.nan))
        sd = clean_float(stds.get(col, np.nan))
        if not np.isfinite(r) or not np.isfinite(t):
            return float("inf")
        if not np.isfinite(sd) or sd == 0:
            sd = 1.0
        vals.append(abs((r - t) / sd))
    return float(np.mean(vals))


def excel_safe_sheet_name(name: str, used: set[str], max_len: int = 31) -> str:
    safe = re.sub(r'[:\\/?*\[\]]', "_", str(name))
    safe = safe[:max_len].strip() or "sheet"
    candidate = safe
    i = 2
    while candidate in used:
        suffix = f"_{i}"
        candidate = (safe[: max_len - len(suffix)] + suffix).strip()
        i += 1
    used.add(candidate)
    return candidate


def format_df_for_excel_decimal_comma(df: pd.DataFrame) -> pd.DataFrame:
    # Si FORCE_DECIMAL_COMMA_IN_XLSX = False, se exportan números reales a Excel.
    # Así desaparece el "piquito verde" de números almacenados como texto.
    # El separador decimal visible lo decidirá Excel/Windows según la configuración regional.
    if not FORCE_DECIMAL_COMMA_IN_XLSX:
        return df.copy()
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_numeric_dtype(out[col]):
            out[col] = out[col].map(lambda x: "" if pd.isna(x) else str(x).replace(".", ","))
    return out


def autosize_excel_columns(xlsx_path: Path) -> None:
    wb = load_workbook(xlsx_path)
    for ws in wb.worksheets:
        for col_cells in ws.columns:
            max_len = 0
            col_letter = col_cells[0].column_letter
            for cell in col_cells[:200]:
                try:
                    val = "" if cell.value is None else str(cell.value)
                except Exception:
                    val = ""
                max_len = max(max_len, len(val))
            ws.column_dimensions[col_letter].width = min(max_len + 2, 70)
    wb.save(xlsx_path)


def build_sheet_description_map() -> Dict[str, str]:
    return {
        "01_target_regime_weeks": "Semanas de régimen SPY que se procesaron y sus semanas siguientes de entrada.",
        "02_similar_spy_weeks": "Semanas históricas con SPY parecido a cada régimen objetivo.",
        "03_hist_trades": "Trades históricos simulados en la semana siguiente a esos regímenes históricos parecidos. Queda separado.",
        "04_hist_ticker_stats": "Resumen histórico por ticker solo como referencia. Ya no decide la selección actual.",
        "05_hist_winner_profile_overall": "Perfil global de las 7 variables de todos los ganadores históricos, por cada semana de régimen.",
        "06_next_week_candidates": "Activos de la semana siguiente actual que se parecen al perfil global de ganadores históricos.",
        "07_next_week_real_trades": "Resultado real simulado de esos candidatos usando ladder.",
        "08_summary_by_regime_week": "Resumen por cada semana de régimen procesada.",
        "09_summary_total": "Resumen total agregado de todas las semanas corridas.",
    }


def export_csv(df: pd.DataFrame, out_dir: Path, stem: str, ts: str) -> str:
    path = out_dir / f"{OUTPUT_PREFIX}_{stem}_{ts}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig", sep=";", decimal=",")
    return str(path)

# =============================================================================
# LOADERS
# =============================================================================

def load_weekly_master(path: str) -> pd.DataFrame:
    usecols = set(required_weekly_columns())
    cache_dir = resolve_dataset_cache_dir()
    fp = compute_dataset_fingerprint(path, DAILY_MASTER_GLOB)
    cache_file = cache_dir / f"weekly_master_{fp[:16]}.parquet"
    if ENABLE_DATASET_PARQUET_CACHE and cache_file.exists():
        try:
            df = pd.read_parquet(cache_file)
        except Exception:
            df = pd.read_csv(path, usecols=lambda c: c in usecols)
    else:
        df = pd.read_csv(path, usecols=lambda c: c in usecols)
        if ENABLE_DATASET_PARQUET_CACHE:
            try:
                df.to_parquet(cache_file, index=False)
            except Exception:
                pass
    if "signal_date" not in df.columns:
        raise ValueError("El weekly master no tiene columna signal_date")
    df["signal_date"] = safe_to_datetime(df["signal_date"])
    return df.dropna(subset=["signal_date"]).copy()


def load_daily_masters(glob_pattern: str) -> pd.DataFrame:
    paths = sorted(Path(glob_pattern).parent.glob(Path(glob_pattern).name))
    if not paths:
        raise FileNotFoundError(f"No encontré daily masters válidos con pattern {glob_pattern}")
    fp = compute_dataset_fingerprint(WEEKLY_MASTER_FILE, glob_pattern)
    cache_dir = resolve_dataset_cache_dir()
    cache_file = cache_dir / f"daily_master_{fp[:16]}.parquet"
    usecols = set(required_daily_columns())
    if ENABLE_DATASET_PARQUET_CACHE and cache_file.exists():
        try:
            df = pd.read_parquet(cache_file)
            if "date" in df.columns:
                df["date"] = safe_to_datetime(df["date"])
            return df.dropna(subset=["date"]).copy()
        except Exception:
            pass

    parts = []
    for p in paths:
        part = pd.read_csv(p, usecols=lambda c: c in usecols)
        if "date" in part.columns:
            part["date"] = safe_to_datetime(part["date"])
            parts.append(part)
    if not parts:
        raise FileNotFoundError(f"No encontré daily masters válidos con pattern {glob_pattern}")
    df = pd.concat(parts, ignore_index=True)
    df = df.dropna(subset=["date"]).copy()
    if ENABLE_DATASET_PARQUET_CACHE:
        try:
            df.to_parquet(cache_file, index=False)
        except Exception:
            pass
    return df


def build_daily_map(daily_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    out = {}
    required_rename = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "adj_close": "Adj Close", "volume": "Volume"}
    for ticker, g in daily_df.groupby("ticker", sort=False):
        # Pre-sorted once here so trade simulation can reuse without re-sorting.
        d = g.copy().sort_values("date").set_index("date")
        for src, dst in required_rename.items():
            if src in d.columns and dst not in d.columns:
                d[dst] = pd.to_numeric(d[src], errors="coerce")
        out[str(ticker)] = d
    return out


def build_weekly_signal_index(weekly_df: pd.DataFrame) -> Dict[pd.Timestamp, pd.DataFrame]:
    out: Dict[pd.Timestamp, pd.DataFrame] = {}
    if weekly_df is None or weekly_df.empty:
        return out
    for dt, g in weekly_df.groupby("signal_date", sort=False):
        if pd.isna(dt):
            continue
        out[pd.Timestamp(dt).normalize()] = g
    return out

# =============================================================================
# TRADE ENGINE
# =============================================================================

@dataclass
class TradeResult:
    ticker: str
    regime_signal_date: Optional[str]
    entry_signal_date: Optional[str]
    entry_date: Optional[str]
    entry_price: float
    exit_date: Optional[str]
    exit_price: float
    exit_reason: Optional[str]
    first_touch_result: str
    gross_return_pct: float
    net_return_pct: float
    net_pnl_dollars: float
    days_held: float
    bars_held: int
    target_price: float
    stop_price: float
    active_target_price_at_exit: float
    active_stop_price_at_exit: float
    ladder_steps_hit: int
    max_target_hit_pct: float
    max_locked_stop_pct: float

def get_entry_from_signal(row: pd.Series, daily: pd.DataFrame) -> Tuple[pd.Timestamp, float, str]:
    signal_date = pd.to_datetime(row.get("signal_date"), errors="coerce")
    if pd.isna(signal_date):
        return pd.NaT, np.nan, "bad_signal_date"
    if ENTRY_MODE == "next_open":
        next_dt = daily.index[daily.index > signal_date]
        if len(next_dt) == 0:
            return pd.NaT, np.nan, "missing_next_open"
        entry_date = pd.Timestamp(next_dt[0])
        return entry_date, clean_float(daily.loc[entry_date, "Open"]), "ok"
    entry_date = signal_date
    entry_price = clean_float(row.get("close", np.nan))
    if (not np.isfinite(entry_price) or entry_price <= 0) and signal_date in daily.index:
        entry_price = clean_float(daily.loc[signal_date, "Close"])
    return entry_date, entry_price, "ok"


def simulate_trade_direct(daily: pd.DataFrame, ticker: str, regime_signal_date: pd.Timestamp, entry_signal_date: pd.Timestamp, entry_date: pd.Timestamp, entry_price: float) -> TradeResult:
    empty = TradeResult(
        ticker=ticker,
        regime_signal_date=str(pd.Timestamp(regime_signal_date).date()) if pd.notna(regime_signal_date) else None,
        entry_signal_date=str(pd.Timestamp(entry_signal_date).date()) if pd.notna(entry_signal_date) else None,
        entry_date=None,
        entry_price=np.nan,
        exit_date=None,
        exit_price=np.nan,
        exit_reason=None,
        first_touch_result="none",
        gross_return_pct=np.nan,
        net_return_pct=np.nan,
        net_pnl_dollars=np.nan,
        days_held=np.nan,
        bars_held=0,
        target_price=np.nan,
        stop_price=np.nan,
        active_target_price_at_exit=np.nan,
        active_stop_price_at_exit=np.nan,
        ladder_steps_hit=0,
        max_target_hit_pct=np.nan,
        max_locked_stop_pct=np.nan,
    )
    if daily is None or daily.empty or pd.isna(entry_date) or not np.isfinite(entry_price) or entry_price <= 0:
        return empty

    # daily already comes pre-sorted from build_daily_map.
    work = daily
    path = work.loc[work.index > entry_date] if EXITS_START_NEXT_BAR else work.loc[work.index >= entry_date]
    if path.empty:
        return empty
    path = path.head(MAX_HOLD_TRADING_DAYS)

    current_target_pct = INITIAL_TP_PCT
    current_stop_pct = -INITIAL_SL_PCT
    current_target_price = entry_price * (1.0 + current_target_pct)
    current_stop_price = entry_price * (1.0 + current_stop_pct)

    exit_date = None
    exit_price = np.nan
    exit_reason = "time"
    first_touch_result = "none"
    bars_held = 0
    ladder_steps_hit = 0
    max_target_hit_pct = 0.0
    max_locked_stop_pct = current_stop_pct * 100.0

    for i, (dt, r) in enumerate(path.iterrows(), start=1):
        bars_held = i
        h = clean_float(r.get("High", np.nan))
        l = clean_float(r.get("Low", np.nan))

        stop_before_bar = current_stop_price
        target_before_bar = current_target_price
        target_pct_before_bar = current_target_pct
        stop_pct_before_bar = current_stop_pct

        hit_target = np.isfinite(h) and h >= target_before_bar
        hit_stop = np.isfinite(l) and l <= stop_before_bar

        if hit_target and hit_stop:
            if INTRADAY_PRIORITY == "target":
                # Se considera que primero tocó el target actual.
                first_touch_result = "target"
                while np.isfinite(h) and h >= current_target_price:
                    ladder_steps_hit += 1
                    max_target_hit_pct = max(max_target_hit_pct, current_target_pct * 100.0)
                    if ladder_steps_hit == 1:
                        current_stop_pct = FIRST_LOCKED_SL_PCT
                    else:
                        current_stop_pct = current_target_pct - TRAIL_STEP_PCT
                    current_target_pct = current_target_pct + TRAIL_STEP_PCT
                    current_stop_price = entry_price * (1.0 + current_stop_pct)
                    current_target_price = entry_price * (1.0 + current_target_pct)
                    max_locked_stop_pct = max(max_locked_stop_pct, current_stop_pct * 100.0)
                # Después del avance del ladder, si la barra también perforó el stop viejo no lo usamos;
                # el nuevo stop aplica desde barras siguientes.
                continue
            else:
                exit_date, exit_price, exit_reason, first_touch_result = dt, stop_before_bar, "stop", "stop"
                break

        if hit_target:
            first_touch_result = "target" if first_touch_result == "none" else first_touch_result
            while np.isfinite(h) and h >= current_target_price:
                ladder_steps_hit += 1
                max_target_hit_pct = max(max_target_hit_pct, current_target_pct * 100.0)
                if ladder_steps_hit == 1:
                    current_stop_pct = FIRST_LOCKED_SL_PCT
                else:
                    current_stop_pct = current_target_pct - TRAIL_STEP_PCT
                current_target_pct = current_target_pct + TRAIL_STEP_PCT
                current_stop_price = entry_price * (1.0 + current_stop_pct)
                current_target_price = entry_price * (1.0 + current_target_pct)
                max_locked_stop_pct = max(max_locked_stop_pct, current_stop_pct * 100.0)
            continue

        if hit_stop:
            exit_date, exit_price, exit_reason = dt, stop_before_bar, "stop"
            if first_touch_result == "none":
                first_touch_result = "stop"
            break

    if exit_date is None:
        exit_date = path.index[-1]
        exit_price = clean_float(path.iloc[-1].get("Close", np.nan))

    gross_return_pct = (exit_price / entry_price - 1.0) * 100.0 if np.isfinite(exit_price) else np.nan
    net_return_pct = gross_return_pct - (2.0 * COMMISSION_PCT_PER_SIDE) if np.isfinite(gross_return_pct) else np.nan
    net_pnl_dollars = CAPITAL_PER_TRADE * net_return_pct / 100.0 if np.isfinite(net_return_pct) else np.nan
    days_held = (pd.Timestamp(exit_date) - pd.Timestamp(entry_date)).days if pd.notna(exit_date) else np.nan

    return TradeResult(
        ticker=ticker,
        regime_signal_date=str(pd.Timestamp(regime_signal_date).date()),
        entry_signal_date=str(pd.Timestamp(entry_signal_date).date()),
        entry_date=str(pd.Timestamp(entry_date).date()),
        entry_price=round(entry_price, 4),
        exit_date=str(pd.Timestamp(exit_date).date()),
        exit_price=round(exit_price, 4) if np.isfinite(exit_price) else np.nan,
        exit_reason=exit_reason,
        first_touch_result=first_touch_result,
        gross_return_pct=round(gross_return_pct, 4) if np.isfinite(gross_return_pct) else np.nan,
        net_return_pct=round(net_return_pct, 4) if np.isfinite(net_return_pct) else np.nan,
        net_pnl_dollars=round(net_pnl_dollars, 4) if np.isfinite(net_pnl_dollars) else np.nan,
        days_held=float(days_held) if np.isfinite(days_held) else np.nan,
        bars_held=int(bars_held),
        target_price=round(current_target_price, 4),
        stop_price=round(current_stop_price, 4),
        active_target_price_at_exit=round(current_target_price, 4),
        active_stop_price_at_exit=round(current_stop_price, 4),
        ladder_steps_hit=int(ladder_steps_hit),
        max_target_hit_pct=round(max_target_hit_pct, 4) if np.isfinite(max_target_hit_pct) else np.nan,
        max_locked_stop_pct=round(max_locked_stop_pct, 4) if np.isfinite(max_locked_stop_pct) else np.nan,
    )


# =============================================================================
# CORE ANALYSIS
# =============================================================================

def get_unique_spy_weeks(weekly_df: pd.DataFrame) -> pd.DataFrame:
    out = weekly_df[["signal_date"] + SPY_VARS].drop_duplicates(subset=["signal_date"]).copy()
    out = out.sort_values("signal_date").reset_index(drop=True)
    out["next_signal_date"] = out["signal_date"].shift(-1)
    return out


def find_similar_spy_weeks(target_week: pd.Series, hist_spy_weeks: pd.DataFrame) -> pd.DataFrame:
    usable = hist_spy_weeks.dropna(subset=SPY_VARS + ["next_signal_date"]).copy()
    if usable.empty:
        return usable
    target_vals = pd.to_numeric(target_week[SPY_VARS], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(target_vals).all():
        return pd.DataFrame(columns=list(usable.columns) + ["spy_distance", "spy_similarity_rank"])

    mat = usable[SPY_VARS].to_numpy(dtype=float)
    stds = np.nanstd(mat, axis=0, ddof=0)
    stds[~np.isfinite(stds) | (stds == 0)] = 1.0
    dists = np.mean(np.abs((mat - target_vals) / stds), axis=1)
    usable["spy_distance"] = dists
    usable = usable.sort_values(["spy_distance", "signal_date"]).reset_index(drop=True)
    usable["spy_similarity_rank"] = np.arange(1, len(usable) + 1)
    return usable.head(TOP_SIMILAR_SPY_WEEKS).copy()


def build_hist_trades_for_similar_spy(
    target_week: pd.Series,
    similar_spy_weeks: pd.DataFrame,
    weekly_by_signal: Dict[pd.Timestamp, pd.DataFrame],
    daily_map: Dict[str, pd.DataFrame],
    trade_cache: Optional[Any] = None,
) -> pd.DataFrame:
    use_global_cache = isinstance(trade_cache, HistoricalTradeCache)
    if (trade_cache is None) or (not use_global_cache):
        local_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
    else:
        local_cache = {}
    trades = []
    for _, sim in similar_spy_weeks.iterrows():
        hist_regime_date = pd.Timestamp(sim["signal_date"]).normalize()
        hist_entry_week_date = pd.Timestamp(sim["next_signal_date"]).normalize()
        hist_entry_rows = weekly_by_signal.get(hist_entry_week_date)
        if hist_entry_rows is None or hist_entry_rows.empty:
            continue

        for row in hist_entry_rows.itertuples(index=False):
            row_dict = row._asdict()
            ticker = str(row_dict.get("ticker", ""))
            if not ticker:
                continue
            daily = daily_map.get(ticker)
            if daily is None or daily.empty:
                continue
            entry_date, entry_price, entry_status = get_entry_from_signal(row_dict, daily)
            if entry_status != "ok" or pd.isna(entry_date) or not np.isfinite(entry_price) or entry_price <= 0:
                continue

            entry_signal_key = str(hist_entry_week_date.date())
            if use_global_cache:
                tr_payload = trade_cache.get(ticker, entry_signal_key)
                if tr_payload is None:
                    tr = simulate_trade_direct(daily, ticker, hist_regime_date, hist_entry_week_date, entry_date, entry_price)
                    tr_payload = dict(tr.__dict__)
                    trade_cache.put(ticker, entry_signal_key, tr_payload)
            else:
                cache_key = (ticker, entry_signal_key)
                tr_payload = local_cache.get(cache_key)
                if tr_payload is None:
                    tr = simulate_trade_direct(daily, ticker, hist_regime_date, hist_entry_week_date, entry_date, entry_price)
                    tr_payload = dict(tr.__dict__)
                    local_cache[cache_key] = tr_payload

            out = dict(row_dict)
            out.update(tr_payload)
            out["regime_signal_date"] = str(hist_regime_date.date())
            out["entry_signal_date"] = str(hist_entry_week_date.date())
            out["target_regime_signal_date"] = str(pd.Timestamp(target_week["signal_date"]).date())
            out["hist_regime_signal_date"] = str(hist_regime_date.date())
            out["hist_entry_week_signal_date"] = str(hist_entry_week_date.date())
            out["spy_distance"] = clean_float(sim.get("spy_distance", np.nan))
            out["spy_similarity_rank"] = clean_float(sim.get("spy_similarity_rank", np.nan))
            ft = str(out.get("first_touch_result", "none")).lower()
            out["is_win"] = int(ft == "target")
            out["is_loss"] = int(ft == "stop")
            out["is_none"] = int(ft == "none")
            trades.append(out)
    return pd.DataFrame(trades)


def build_hist_ticker_stats(hist_trades: pd.DataFrame) -> pd.DataFrame:
    if hist_trades.empty:
        return pd.DataFrame()
    stats = (
        hist_trades.groupby("ticker", dropna=True)
        .agg(
            trades=("ticker", "count"),
            wins=("is_win", "sum"),
            losses=("is_loss", "sum"),
            none=("is_none", "sum"),
            win_rate=("is_win", "mean"),
            avg_net_return_pct=("net_return_pct", "mean"),
            median_net_return_pct=("net_return_pct", "median"),
            avg_net_pnl_dollars=("net_pnl_dollars", "mean"),
            avg_spy_distance=("spy_distance", "mean"),
        )
        .reset_index()
        .sort_values(["win_rate", "trades", "avg_net_return_pct", "ticker"], ascending=[False, False, False, True])
        .reset_index(drop=True)
    )
    stats["hist_rank"] = np.arange(1, len(stats) + 1)
    return stats


def build_winner_profile_overall(hist_trades: pd.DataFrame) -> pd.DataFrame:
    winners = hist_trades[hist_trades["is_win"] == 1].copy() if not hist_trades.empty else pd.DataFrame()
    if winners.empty:
        return pd.DataFrame()
    rows = []
    for var in PROFILE_VARS:
        s = pd.to_numeric(winners[var], errors="coerce")
        rows.append({
            "var_name": var,
            "count": int(s.notna().sum()),
            "mean": s.mean(skipna=True),
            "std": s.std(skipna=True, ddof=0),
            "min": s.min(skipna=True),
            "p25": s.quantile(0.25),
            "p50": s.quantile(0.50),
            "p75": s.quantile(0.75),
            "max": s.max(skipna=True),
        })
    return pd.DataFrame(rows)


def row_matches_overall_profile(current_row: pd.Series, overall_profile: pd.DataFrame) -> Tuple[bool, float]:
    if overall_profile.empty:
        return False, float("inf")

    if PROFILE_MODE == "zscore_distance":
        dists = []
        for var in PROFILE_VARS:
            prof = overall_profile[overall_profile["var_name"] == var]
            mean = clean_float(prof.iloc[0]["mean"])
            std = clean_float(prof.iloc[0]["std"])
            val = clean_float(current_row.get(var, np.nan))
            if not np.isfinite(val) or not np.isfinite(mean):
                return False, float("inf")
            if not np.isfinite(std) or std == 0:
                std = 1.0
            dists.append(abs((val - mean) / std))
        dist = float(np.mean(dists))
        return dist <= MAX_PROFILE_ZDIST, dist

    dists = []
    for var in PROFILE_VARS:
        prof = overall_profile[overall_profile["var_name"] == var]
        val = clean_float(current_row.get(var, np.nan))
        p25 = clean_float(prof.iloc[0]["p25"])
        p75 = clean_float(prof.iloc[0]["p75"])
        if not np.isfinite(val) or not np.isfinite(p25) or not np.isfinite(p75):
            return False, float("inf")
        band = p75 - p25
        extra = band * PROFILE_EXPANSION_FACTOR
        lo = p25 - extra
        hi = p75 + extra
        if val < lo or val > hi:
            return False, float("inf")
        center = (p25 + p75) / 2.0
        scale = band if np.isfinite(band) and band > 0 else 1.0
        dists.append(abs((val - center) / scale))
    return True, float(np.mean(dists))


def select_next_week_candidates(target_week: pd.Series, current_entry_week_rows: pd.DataFrame, overall_profile: pd.DataFrame) -> pd.DataFrame:
    if current_entry_week_rows.empty:
        return pd.DataFrame()

    current = current_entry_week_rows.copy()
    current = current[~current["ticker"].astype(str).isin(EXCLUDED_CURRENT_TICKERS)].copy()
    if current.empty:
        return pd.DataFrame()

    if ENABLE_CLOSE_VS_SMA50_FILTER:
        current["close_vs_sma50_pct"] = pd.to_numeric(current["close_vs_sma50_pct"], errors="coerce")
        current = current[current["close_vs_sma50_pct"].notna()].copy()
        current = current[current["close_vs_sma50_pct"] <= MAX_CLOSE_VS_SMA50_PCT].copy()
        if current.empty:
            return pd.DataFrame()

    if STRATEGY_FAMILY == "momentum_rank":
        needed = ["ret_4w_pct", "ret_8w_pct", "close_vs_sma20w_pct"]
        for col in needed:
            if col not in current.columns:
                return pd.DataFrame()
            current[col] = pd.to_numeric(current[col], errors="coerce")

        current = current[
            current["ret_4w_pct"].notna()
            & current["ret_8w_pct"].notna()
            & current["close_vs_sma20w_pct"].notna()
            & (current["ret_4w_pct"] >= MOMENTUM_MIN_RET_4W_PCT)
            & (current["close_vs_sma20w_pct"] <= MOMENTUM_MAX_CLOSE_VS_SMA20W_PCT)
        ].copy()
        if current.empty:
            return pd.DataFrame()

        def _z(s: pd.Series) -> pd.Series:
            sd = float(pd.to_numeric(s, errors="coerce").std(ddof=0))
            if not np.isfinite(sd) or sd == 0:
                sd = 1.0
            return (s - s.mean()) / sd

        ret4_z = _z(current["ret_4w_pct"])
        ret8_z = _z(current["ret_8w_pct"])
        trend_z = _z(current["close_vs_sma20w_pct"])
        current["momentum_score"] = (MOMENTUM_W_RET_4W * ret4_z) + (MOMENTUM_W_RET_8W * ret8_z) + (MOMENTUM_W_TREND * trend_z)

        out = current.sort_values(["momentum_score", "ticker"], ascending=[False, True]).reset_index(drop=True)
        out["target_regime_signal_date"] = str(pd.Timestamp(target_week["signal_date"]).date())
        out["current_entry_week_signal_date"] = pd.to_datetime(out["signal_date"], errors="coerce").dt.date.astype(str)
        # Compatibilidad de columnas con el flujo existente:
        # mas score => mejor candidato, por eso usamos distancia negativa.
        out["profile_distance"] = -pd.to_numeric(out["momentum_score"], errors="coerce")
        out["current_candidate_rank"] = np.arange(1, len(out) + 1)
        return out.head(TOP_CANDIDATES_NEXT_WEEK).copy()

    if overall_profile.empty:
        return pd.DataFrame()

    for var in PROFILE_VARS:
        if var not in current.columns:
            return pd.DataFrame()

    prof = overall_profile.set_index("var_name")
    if any(v not in prof.index for v in PROFILE_VARS):
        return pd.DataFrame()

    vals = current[PROFILE_VARS].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    finite_mask = np.isfinite(vals).all(axis=1)

    if PROFILE_MODE == "zscore_distance":
        means = pd.to_numeric(prof.loc[PROFILE_VARS, "mean"], errors="coerce").to_numpy(dtype=float)
        stds = pd.to_numeric(prof.loc[PROFILE_VARS, "std"], errors="coerce").to_numpy(dtype=float)
        stds[~np.isfinite(stds) | (stds == 0)] = 1.0
        dists = np.mean(np.abs((vals - means) / stds), axis=1)
        valid_mask = finite_mask & np.isfinite(dists) & (dists <= MAX_PROFILE_ZDIST)
    else:
        p25 = pd.to_numeric(prof.loc[PROFILE_VARS, "p25"], errors="coerce").to_numpy(dtype=float)
        p75 = pd.to_numeric(prof.loc[PROFILE_VARS, "p75"], errors="coerce").to_numpy(dtype=float)
        band = p75 - p25
        extra = band * PROFILE_EXPANSION_FACTOR
        lo = p25 - extra
        hi = p75 + extra
        within = ((vals >= lo) & (vals <= hi)).all(axis=1)
        center = (p25 + p75) / 2.0
        scale = np.where(np.isfinite(band) & (band > 0), band, 1.0)
        dists = np.mean(np.abs((vals - center) / scale), axis=1)
        valid_mask = finite_mask & np.isfinite(dists) & within

    if not np.any(valid_mask):
        return pd.DataFrame()

    out = current.loc[valid_mask].copy()
    out["target_regime_signal_date"] = str(pd.Timestamp(target_week["signal_date"]).date())
    out["current_entry_week_signal_date"] = pd.to_datetime(out["signal_date"], errors="coerce").dt.date.astype(str)
    out["profile_distance"] = dists[valid_mask]
    out = out.sort_values(["profile_distance", "ticker"], ascending=[True, True]).reset_index(drop=True)
    out["current_candidate_rank"] = np.arange(1, len(out) + 1)
    return out.head(TOP_CANDIDATES_NEXT_WEEK).copy()



def compute_avg_profile_distance(current_candidates: pd.DataFrame) -> float:
    if current_candidates is None or current_candidates.empty or "profile_distance" not in current_candidates.columns:
        return float("nan")
    return float(pd.to_numeric(current_candidates["profile_distance"], errors="coerce").mean())


def compute_candidate_extension_stats(current_candidates: pd.DataFrame) -> Tuple[float, float]:
    if current_candidates is None or current_candidates.empty or "close_vs_sma50_pct" not in current_candidates.columns:
        return float("nan"), float("nan")
    s = pd.to_numeric(current_candidates["close_vs_sma50_pct"], errors="coerce")
    return float(s.mean()), float(s.max())


def simulate_current_next_week_trades(current_candidates: pd.DataFrame, daily_map: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for _, row in current_candidates.iterrows():
        ticker = str(row["ticker"])
        daily = daily_map.get(ticker)
        if daily is None or daily.empty:
            continue
        regime_signal_date = pd.to_datetime(row.get("target_regime_signal_date"), errors="coerce")
        entry_signal_date = pd.to_datetime(row.get("signal_date"), errors="coerce")
        entry_date, entry_price, entry_status = get_entry_from_signal(row, daily)
        if entry_status != "ok" or pd.isna(entry_date) or not np.isfinite(entry_price) or entry_price <= 0:
            continue
        tr = simulate_trade_direct(daily, ticker, regime_signal_date, entry_signal_date, entry_date, entry_price)
        out = row.to_dict()
        out.update(tr.__dict__)
        out["is_win"] = int(str(tr.first_touch_result).lower() == "target")
        out["is_loss"] = int(str(tr.first_touch_result).lower() == "stop")
        out["is_none"] = int(str(tr.first_touch_result).lower() == "none")
        rows.append(out)
    return pd.DataFrame(rows)


def process_regime_week(
    idx: int,
    target_week: pd.Series,
    spy_unique_all: pd.DataFrame,
    weekly_by_signal: Dict[pd.Timestamp, pd.DataFrame],
    daily_map: Dict[str, pd.DataFrame],
    hist_start: pd.Timestamp,
    hist_end: pd.Timestamp,
    trade_cache: Optional[HistoricalTradeCache] = None,
    similar_weeks_cache: Optional[Dict[str, pd.DataFrame]] = None,
) -> Dict[str, Any]:
    target_regime_date = pd.Timestamp(target_week["signal_date"])
    current_entry_week_date = pd.Timestamp(target_week["next_signal_date"])
    print(f"Procesando régimen {target_regime_date.date().isoformat()} -> semana entrada {current_entry_week_date.date().isoformat()}")

    target_spy_channel_r2 = clean_float(target_week.get("spy_channel_r2", np.nan))
    spy_channel_r2_gate_pass = (not ENABLE_SPY_CHANNEL_R2_GATE) or (
        np.isfinite(target_spy_channel_r2) and target_spy_channel_r2 >= MIN_SPY_CHANNEL_R2
    )

    target_row = {
        "target_regime_signal_date": str(target_regime_date.date()),
        "current_entry_week_signal_date": str(current_entry_week_date.date()),
        **{v: clean_float(target_week[v]) for v in SPY_VARS},
        "spy_channel_r2_gate_enabled": int(ENABLE_SPY_CHANNEL_R2_GATE),
        "spy_channel_r2_gate_pass": int(spy_channel_r2_gate_pass),
        "min_spy_channel_r2_required": MIN_SPY_CHANNEL_R2 if ENABLE_SPY_CHANNEL_R2_GATE else np.nan,
    }

    similar_cache_key = str(target_regime_date.date())
    similar_base: Optional[pd.DataFrame] = None
    if isinstance(similar_weeks_cache, dict):
        similar_base = similar_weeks_cache.get(similar_cache_key)
    if similar_base is None:
        hist_spy_weeks = spy_unique_all[
            (spy_unique_all["signal_date"] >= hist_start)
            & (spy_unique_all["signal_date"] <= hist_end)
            & (spy_unique_all["next_signal_date"] <= hist_end)
            & (spy_unique_all["next_signal_date"] < target_regime_date)
        ].copy()
        similar_base = find_similar_spy_weeks(target_week, hist_spy_weeks)
        if isinstance(similar_weeks_cache, dict):
            similar_weeks_cache[similar_cache_key] = similar_base.copy()
    similar = similar_base.copy() if isinstance(similar_base, pd.DataFrame) else pd.DataFrame()
    similar["target_regime_signal_date"] = str(target_regime_date.date())
    similar["current_entry_week_signal_date"] = str(current_entry_week_date.date())
    similar["spy_channel_r2_gate_pass"] = int(spy_channel_r2_gate_pass)
    if not similar.empty:
        for c in ["signal_date", "next_signal_date"]:
            if c in similar.columns:
                similar[c] = pd.to_datetime(similar[c], errors="coerce").dt.date.astype(str)

    hist_trades = build_hist_trades_for_similar_spy(target_week, similar, weekly_by_signal, daily_map, trade_cache)
    if not hist_trades.empty:
        hist_trades["target_regime_signal_date"] = str(target_regime_date.date())
        hist_trades["current_entry_week_signal_date"] = str(current_entry_week_date.date())
        hist_trades["spy_channel_r2_gate_pass"] = int(spy_channel_r2_gate_pass)

    hist_ticker_stats = build_hist_ticker_stats(hist_trades)
    if not hist_ticker_stats.empty:
        hist_ticker_stats["target_regime_signal_date"] = str(target_regime_date.date())
        hist_ticker_stats["current_entry_week_signal_date"] = str(current_entry_week_date.date())
        hist_ticker_stats["spy_channel_r2_gate_pass"] = int(spy_channel_r2_gate_pass)

    winner_profile_overall = build_winner_profile_overall(hist_trades)
    if not winner_profile_overall.empty:
        winner_profile_overall["target_regime_signal_date"] = str(target_regime_date.date())
        winner_profile_overall["current_entry_week_signal_date"] = str(current_entry_week_date.date())
        winner_profile_overall["spy_channel_r2_gate_pass"] = int(spy_channel_r2_gate_pass)

    current_entry_rows = weekly_by_signal.get(current_entry_week_date.normalize(), pd.DataFrame())
    next_week_candidates = select_next_week_candidates(target_week, current_entry_rows, winner_profile_overall)
    avg_profile_distance = compute_avg_profile_distance(next_week_candidates) if STRATEGY_FAMILY == "profile_match" else float("nan")
    avg_close_vs_sma50_candidates, max_close_vs_sma50_candidates = compute_candidate_extension_stats(next_week_candidates)
    avg_profile_distance_gate_pass = (STRATEGY_FAMILY != "profile_match") or (not ENABLE_AVG_PROFILE_DISTANCE_GATE) or (
        np.isfinite(avg_profile_distance) and avg_profile_distance <= MAX_AVG_PROFILE_DISTANCE
    )

    should_trade_week = bool(spy_channel_r2_gate_pass and avg_profile_distance_gate_pass)
    skip_reasons = []
    if not spy_channel_r2_gate_pass:
        skip_reasons.append("spy_channel_r2_gate")
    if not avg_profile_distance_gate_pass:
        skip_reasons.append("avg_profile_distance_gate")
    skip_reason = "|".join(skip_reasons) if skip_reasons else ""

    if not next_week_candidates.empty:
        next_week_candidates = next_week_candidates.copy()
        next_week_candidates["avg_profile_distance"] = avg_profile_distance
        next_week_candidates["avg_close_vs_sma50_candidates"] = avg_close_vs_sma50_candidates
        next_week_candidates["max_close_vs_sma50_candidates"] = max_close_vs_sma50_candidates
        next_week_candidates["spy_channel_r2_gate_enabled"] = int(ENABLE_SPY_CHANNEL_R2_GATE)
        next_week_candidates["spy_channel_r2_gate_pass"] = int(spy_channel_r2_gate_pass)
        next_week_candidates["avg_profile_distance_gate_enabled"] = int(ENABLE_AVG_PROFILE_DISTANCE_GATE)
        next_week_candidates["avg_profile_distance_gate_pass"] = int(avg_profile_distance_gate_pass)
        next_week_candidates["should_trade_week"] = int(should_trade_week)
        next_week_candidates["skip_reason"] = skip_reason
        if "signal_date" in next_week_candidates.columns:
            next_week_candidates["signal_date"] = pd.to_datetime(next_week_candidates["signal_date"], errors="coerce").dt.date.astype(str)

    if should_trade_week:
        next_week_real_trades = simulate_current_next_week_trades(next_week_candidates, daily_map)
        if not next_week_real_trades.empty:
            next_week_real_trades["avg_profile_distance"] = avg_profile_distance
            next_week_real_trades["avg_close_vs_sma50_candidates"] = avg_close_vs_sma50_candidates
            next_week_real_trades["max_close_vs_sma50_candidates"] = max_close_vs_sma50_candidates
            next_week_real_trades["spy_channel_r2_gate_pass"] = int(spy_channel_r2_gate_pass)
            next_week_real_trades["avg_profile_distance_gate_pass"] = int(avg_profile_distance_gate_pass)
            next_week_real_trades["should_trade_week"] = int(should_trade_week)
            next_week_real_trades["skip_reason"] = skip_reason
    else:
        print(f"  Semana salteada por gates: {skip_reason or 'sin_candidatos_validos'}")
        next_week_real_trades = pd.DataFrame()

    summary_row = {
        "target_regime_signal_date": str(target_regime_date.date()),
        "current_entry_week_signal_date": str(current_entry_week_date.date()),
        "strategy_family": STRATEGY_FAMILY,
        "spy_channel_r2": target_spy_channel_r2,
        "spy_channel_r2_gate_enabled": int(ENABLE_SPY_CHANNEL_R2_GATE),
        "min_spy_channel_r2_required": MIN_SPY_CHANNEL_R2 if ENABLE_SPY_CHANNEL_R2_GATE else np.nan,
        "spy_channel_r2_gate_pass": int(spy_channel_r2_gate_pass),
        "avg_profile_distance": avg_profile_distance,
        "avg_profile_distance_gate_enabled": int(ENABLE_AVG_PROFILE_DISTANCE_GATE),
        "max_avg_profile_distance_allowed": MAX_AVG_PROFILE_DISTANCE if ENABLE_AVG_PROFILE_DISTANCE_GATE else np.nan,
        "avg_profile_distance_gate_pass": int(avg_profile_distance_gate_pass),
        "avg_close_vs_sma50_candidates": avg_close_vs_sma50_candidates,
        "max_close_vs_sma50_candidates": max_close_vs_sma50_candidates,
        "should_trade_week": int(should_trade_week),
        "skip_reason": skip_reason,
        "similar_spy_weeks": int(len(similar)),
        "hist_trades": int(len(hist_trades)),
        "hist_winners": int(hist_trades["is_win"].sum()) if not hist_trades.empty else 0,
        "current_candidates": int(len(next_week_candidates)),
        "real_trades": int(len(next_week_real_trades)),
        "wins": int(next_week_real_trades["is_win"].sum()) if not next_week_real_trades.empty else 0,
        "losses": int(next_week_real_trades["is_loss"].sum()) if not next_week_real_trades.empty else 0,
        "none": int(next_week_real_trades["is_none"].sum()) if not next_week_real_trades.empty else 0,
        "win_rate": float(next_week_real_trades["is_win"].mean()) if not next_week_real_trades.empty else np.nan,
        "avg_net_return_pct": float(pd.to_numeric(next_week_real_trades["net_return_pct"], errors="coerce").mean()) if not next_week_real_trades.empty else np.nan,
        "total_net_pnl_dollars": float(pd.to_numeric(next_week_real_trades["net_pnl_dollars"], errors="coerce").sum()) if not next_week_real_trades.empty else np.nan,
    }

    return {
        "idx": idx,
        "target_row": target_row,
        "similar": similar,
        "hist_trades": hist_trades,
        "hist_ticker_stats": hist_ticker_stats,
        "winner_profile_overall": winner_profile_overall,
        "next_week_candidates": next_week_candidates,
        "next_week_real_trades": next_week_real_trades,
        "summary_row": summary_row,
    }


def compute_dynamic_workers(target_count: int) -> int:
    requested = int(PARALLEL_REGIME_WORKERS)
    if target_count <= 1:
        return 1
    if AUTO_PARALLEL_WORKERS:
        cpu = os.cpu_count() or 2
        dynamic = max(1, min(max(1, cpu - 2), MAX_PARALLEL_WORKERS_CAP))
        if requested > 0:
            # requested actua como minimo sugerido para no quedar subutilizado.
            requested = max(requested, dynamic)
        else:
            requested = dynamic
    if requested <= 0:
        requested = 1
    return int(max(1, min(requested, target_count)))


def precompute_missing_hist_trades(
    target_weeks: pd.DataFrame,
    spy_unique_all: pd.DataFrame,
    weekly_by_signal: Dict[pd.Timestamp, pd.DataFrame],
    daily_map: Dict[str, pd.DataFrame],
    hist_start: pd.Timestamp,
    hist_end: pd.Timestamp,
    trade_cache: HistoricalTradeCache,
    similar_weeks_cache: Optional[Dict[str, pd.DataFrame]] = None,
) -> Dict[str, int]:
    missing_jobs: Dict[Tuple[str, str], Tuple[pd.DataFrame, str, pd.Timestamp, pd.Timestamp, float]] = {}
    scanned_candidates = 0
    hist_spy_base = spy_unique_all[
        (spy_unique_all["signal_date"] >= hist_start)
        & (spy_unique_all["signal_date"] <= hist_end)
        & (spy_unique_all["next_signal_date"] <= hist_end)
    ].copy()
    for _, target_week in target_weeks.iterrows():
        target_regime_date = pd.Timestamp(target_week["signal_date"]).normalize()
        cache_key = str(target_regime_date.date())
        similar_base: Optional[pd.DataFrame] = None
        if isinstance(similar_weeks_cache, dict):
            similar_base = similar_weeks_cache.get(cache_key)
        if similar_base is None:
            hist_spy_weeks = hist_spy_base[hist_spy_base["next_signal_date"] < target_regime_date].copy()
            similar_base = find_similar_spy_weeks(target_week, hist_spy_weeks)
            if isinstance(similar_weeks_cache, dict):
                similar_weeks_cache[cache_key] = similar_base.copy()
        similar = similar_base if isinstance(similar_base, pd.DataFrame) else pd.DataFrame()
        if similar is None or similar.empty:
            continue
        for _, sim in similar.iterrows():
            hist_regime_date = pd.Timestamp(sim["signal_date"]).normalize()
            hist_entry_week_date = pd.Timestamp(sim["next_signal_date"]).normalize()
            hist_entry_rows = weekly_by_signal.get(hist_entry_week_date)
            if hist_entry_rows is None or hist_entry_rows.empty:
                continue
            for row in hist_entry_rows.itertuples(index=False):
                row_dict = row._asdict()
                ticker = str(row_dict.get("ticker", ""))
                if not ticker:
                    continue
                scanned_candidates += 1
                daily = daily_map.get(ticker)
                if daily is None or daily.empty:
                    continue
                entry_date, entry_price, entry_status = get_entry_from_signal(row_dict, daily)
                if entry_status != "ok" or pd.isna(entry_date) or not np.isfinite(entry_price) or entry_price <= 0:
                    continue
                entry_signal_key = str(hist_entry_week_date.date())
                key = (ticker, entry_signal_key)
                if trade_cache.has(ticker, entry_signal_key):
                    continue
                if key not in missing_jobs:
                    missing_jobs[key] = (daily, ticker, hist_regime_date, hist_entry_week_date, float(entry_price))

    jobs = list(missing_jobs.values())
    if not jobs:
        return {"scanned_candidates": int(scanned_candidates), "missing_jobs": 0, "computed": 0}

    workers = max(1, min(int(PRECOMPUTE_WORKERS), len(jobs)))
    computed = 0

    def _compute(job: Tuple[pd.DataFrame, str, pd.Timestamp, pd.Timestamp, float]) -> Tuple[str, str, Dict[str, Any]]:
        daily, ticker, hist_regime_date, hist_entry_week_date, entry_price = job
        entry_signal_key = str(hist_entry_week_date.date())
        if trade_cache.has(ticker, entry_signal_key):
            return ticker, entry_signal_key, {}
        row_like = {"signal_date": hist_entry_week_date, "close": entry_price}
        entry_date, entry_price2, entry_status = get_entry_from_signal(row_like, daily)
        if entry_status != "ok" or pd.isna(entry_date) or not np.isfinite(entry_price2) or entry_price2 <= 0:
            return ticker, entry_signal_key, {}
        tr = simulate_trade_direct(daily, ticker, hist_regime_date, hist_entry_week_date, entry_date, entry_price2)
        return ticker, entry_signal_key, dict(tr.__dict__)

    if workers == 1:
        for job in jobs:
            ticker, entry_signal_key, payload = _compute(job)
            if payload:
                trade_cache.put(ticker, entry_signal_key, payload)
                computed += 1
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_compute, j) for j in jobs]
            for fut in as_completed(futs):
                ticker, entry_signal_key, payload = fut.result()
                if payload:
                    trade_cache.put(ticker, entry_signal_key, payload)
                    computed += 1

    return {"scanned_candidates": int(scanned_candidates), "missing_jobs": int(len(jobs)), "computed": int(computed)}

# =============================================================================
# EXPORT BUNDLE
# =============================================================================

def export_bundle(out_dir: Path, result_dfs: Dict[str, pd.DataFrame], ts: str):
    csv_outputs = []
    for stem, df in result_dfs.items():
        separate = stem == SEPARATE_STEM_IN_CSV
        export_csv_flag = separate or EXPORT_CSVS_INCLUDED_IN_XLSX
        if export_csv_flag:
            csv_outputs.append((stem, export_csv(df, out_dir, stem, ts)))

    xlsx_path = None
    txt_path = None
    desc_map = build_sheet_description_map()

    if EXPORT_SUMMARY_XLSX:
        xlsx_file = out_dir / f"{SUMMARY_XLSX_BASENAME}_{ts}.xlsx"
        used_sheets = set()
        with pd.ExcelWriter(xlsx_file, engine="openpyxl") as writer:
            wrote_any = False
            for stem, df in result_dfs.items():
                if stem == SEPARATE_STEM_IN_CSV:
                    continue
                format_df_for_excel_decimal_comma(df).to_excel(
                    writer, sheet_name=excel_safe_sheet_name(stem, used_sheets), index=False
                )
                wrote_any = True
            if not wrote_any:
                pd.DataFrame({"info": ["No hay resultados para incluir"]}).to_excel(writer, sheet_name="info", index=False)
        autosize_excel_columns(xlsx_file)
        xlsx_path = str(xlsx_file)

    if EXPORT_SHEETS_INFO_TXT:
        txt_file = out_dir / f"{SHEETS_INFO_TXT_BASENAME}_{ts}.txt"
        lines = [f"Corrida: {OUTPUT_PREFIX}", f"Timestamp: {ts}", f"Carpeta origen: {out_dir}", ""]
        if xlsx_path:
            lines += [f"Excel generado: {Path(xlsx_path).name}", ""]
        sep_name = f"{OUTPUT_PREFIX}_{SEPARATE_STEM_IN_CSV}_{ts}.csv"
        lines += [f"Archivo separado: {sep_name}", f"Para qué sirve: {desc_map.get(SEPARATE_STEM_IN_CSV, 'Sin descripción.')}", "", "SOLAPAS DEL EXCEL", "=" * 80]
        for stem in result_dfs.keys():
            if stem == SEPARATE_STEM_IN_CSV:
                continue
            lines += [f"Solapa: {stem}", f"Para qué sirve: {desc_map.get(stem, 'Sin descripción.')}", ""]
        lines += ["VARIABLES DEL PERFIL GLOBAL", "=" * 80]
        for var in PROFILE_VARS:
            lines.append(var)
        txt_file.write_text("\n".join(lines), encoding="utf-8-sig")
        txt_path = str(txt_file)

    return csv_outputs, xlsx_path, txt_path

# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    t_main_start = time.perf_counter()
    base_out_dir = ensure_dir(OUTPUT_DIR)
    run_folder = folder_ts_now()
    out_dir = ensure_dir(base_out_dir / run_folder) if OUTPUT_IN_TIMESTAMP_SUBDIR else base_out_dir
    profiler: Optional[cProfile.Profile] = cProfile.Profile() if ENABLE_RUNTIME_PROFILING else None
    if profiler is not None:
        profiler.enable()

    cache_dir = resolve_global_trade_cache_dir()
    trade_engine_hash = compute_trade_engine_hash()
    data_fingerprint = compute_dataset_fingerprint(WEEKLY_MASTER_FILE, DAILY_MASTER_GLOB)
    hist_trade_cache = HistoricalTradeCache(cache_dir=cache_dir, trade_engine_hash=trade_engine_hash, data_fingerprint=data_fingerprint)
    hist_trade_cache.load()

    t_boot_0 = time.perf_counter()
    print("[BOOT] Cargando weekly master...", flush=True)
    weekly_df = load_weekly_master(WEEKLY_MASTER_FILE)
    print(f"[BOOT] Weekly rows: {len(weekly_df)}", flush=True)
    print("[BOOT] Cargando daily masters...", flush=True)
    daily_df = load_daily_masters(DAILY_MASTER_GLOB)
    print(f"[BOOT] Daily rows: {len(daily_df)}", flush=True)
    print("[BOOT] Construyendo mapa diario...", flush=True)
    daily_map = build_daily_map(daily_df)
    print(f"[BOOT] Mapa diario listo: {len(daily_map)} tickers", flush=True)
    print(f"[CACHE] trade_engine_hash={trade_engine_hash}", flush=True)
    print(f"[CACHE] data_fingerprint={data_fingerprint}", flush=True)
    print(f"[CACHE] cache_file={hist_trade_cache.cache_file}", flush=True)
    print(f"[CACHE] cache_loaded_rows={hist_trade_cache.cache_loaded_rows}", flush=True)
    t_boot_1 = time.perf_counter()

    for col in SPY_VARS + PROFILE_VARS:
        if col not in weekly_df.columns:
            raise ValueError(f"Falta columna requerida en weekly master: {col}")

    test_start = pd.Timestamp(TEST_START)
    test_end = pd.Timestamp(TEST_END)
    hist_start = pd.Timestamp(HIST_START)
    hist_end = pd.Timestamp(HIST_END)

    spy_unique_all = get_unique_spy_weeks(weekly_df)
    weekly_by_signal = build_weekly_signal_index(weekly_df)
    target_weeks = spy_unique_all[(spy_unique_all["signal_date"] >= test_start) & (spy_unique_all["signal_date"] <= test_end)].copy()
    if REQUIRE_NEXT_WEEK_WITHIN_TEST_RANGE:
        target_weeks = target_weeks[target_weeks["next_signal_date"] <= test_end].copy()
    target_weeks = target_weeks.dropna(subset=["next_signal_date"]).sort_values("signal_date").reset_index(drop=True)
    if target_weeks.empty:
        raise ValueError("No encontré semanas objetivo válidas dentro del período de test")
    if REGIME_WEEKS_TO_RUN is not None:
        target_weeks = target_weeks.head(int(REGIME_WEEKS_TO_RUN)).copy()

    ts = ts_now()

    print("=" * 110)
    print("PRUEBA MULTI-WEEK - PERFIL GLOBAL REFORZADO")
    print(f"Semanas a correr: {len(target_weeks)}")
    print(f"Top candidatos por semana: {TOP_CANDIDATES_NEXT_WEEK}")
    print(f"Tickers excluidos: {sorted(EXCLUDED_CURRENT_TICKERS)}")
    print(f"Variables del perfil: {PROFILE_VARS}")
    print("Ladder: TP inicial +5%, SL inicial -5%, luego +5=>SL+1/TP+10, +10=>SL+5/TP+15, etc.")
    print("=" * 110)

    target_rows = []
    all_similar = []
    all_hist_trades = []
    all_hist_ticker_stats = []
    all_winner_profiles = []
    all_next_week_candidates = []
    all_next_week_real_trades = []
    summary_rows = []
    similar_weeks_cache: Dict[str, pd.DataFrame] = {}
    t_precompute_0 = time.perf_counter()
    if ENABLE_PRECOMPUTE_HIST_TRADES:
        print("[CACHE] precompute missing hist trades...", flush=True)
        pc = precompute_missing_hist_trades(
            target_weeks=target_weeks,
            spy_unique_all=spy_unique_all,
            weekly_by_signal=weekly_by_signal,
            daily_map=daily_map,
            hist_start=hist_start,
            hist_end=hist_end,
            trade_cache=hist_trade_cache,
            similar_weeks_cache=similar_weeks_cache,
        )
        print(
            f"[CACHE] precompute scanned={pc.get('scanned_candidates',0)} missing_jobs={pc.get('missing_jobs',0)} computed={pc.get('computed',0)}",
            flush=True,
        )
    t_precompute_1 = time.perf_counter()
    workers = compute_dynamic_workers(len(target_weeks))
    print(f"Regime workers en paralelo: {workers}")

    t_weeks_0 = time.perf_counter()
    week_results: List[Dict[str, Any]] = []
    target_items = list(target_weeks.iterrows())
    if workers == 1:
        for idx, target_week in target_items:
            week_results.append(
                process_regime_week(
                    idx=int(idx),
                    target_week=target_week,
                    spy_unique_all=spy_unique_all,
                    weekly_by_signal=weekly_by_signal,
                    daily_map=daily_map,
                    hist_start=hist_start,
                    hist_end=hist_end,
                    trade_cache=hist_trade_cache,
                    similar_weeks_cache=similar_weeks_cache,
                )
            )
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fut_map = {
                ex.submit(
                    process_regime_week,
                    int(idx),
                    target_week,
                    spy_unique_all,
                    weekly_by_signal,
                    daily_map,
                    hist_start,
                    hist_end,
                    hist_trade_cache,
                    similar_weeks_cache,
                ): int(idx)
                for idx, target_week in target_items
            }
            for fut in as_completed(fut_map):
                week_results.append(fut.result())
    t_weeks_1 = time.perf_counter()

    week_results = sorted(week_results, key=lambda x: int(x.get("idx", 0)))
    for wr in week_results:
        target_rows.append(wr["target_row"])
        if wr["similar"] is not None and not wr["similar"].empty:
            all_similar.append(wr["similar"])
        if wr["hist_trades"] is not None and not wr["hist_trades"].empty:
            all_hist_trades.append(wr["hist_trades"])
        if wr["hist_ticker_stats"] is not None and not wr["hist_ticker_stats"].empty:
            all_hist_ticker_stats.append(wr["hist_ticker_stats"])
        if wr["winner_profile_overall"] is not None and not wr["winner_profile_overall"].empty:
            all_winner_profiles.append(wr["winner_profile_overall"])
        if wr["next_week_candidates"] is not None and not wr["next_week_candidates"].empty:
            all_next_week_candidates.append(wr["next_week_candidates"])
        if wr["next_week_real_trades"] is not None and not wr["next_week_real_trades"].empty:
            all_next_week_real_trades.append(wr["next_week_real_trades"])
        summary_rows.append(wr["summary_row"])

    df_target_regime_weeks = pd.DataFrame(target_rows)
    df_similar = pd.concat(all_similar, ignore_index=True) if all_similar else pd.DataFrame()
    df_hist_trades = pd.concat(all_hist_trades, ignore_index=True) if all_hist_trades else pd.DataFrame()
    df_hist_ticker_stats = pd.concat(all_hist_ticker_stats, ignore_index=True) if all_hist_ticker_stats else pd.DataFrame()
    df_winner_profile_overall = pd.concat(all_winner_profiles, ignore_index=True) if all_winner_profiles else pd.DataFrame()
    df_next_week_candidates = pd.concat(all_next_week_candidates, ignore_index=True) if all_next_week_candidates else pd.DataFrame()
    df_next_week_real_trades = pd.concat(all_next_week_real_trades, ignore_index=True) if all_next_week_real_trades else pd.DataFrame()
    df_summary_by_regime_week = pd.DataFrame(summary_rows)

    summary_total = pd.DataFrame([{
        "regime_weeks_run": int(len(target_weeks)),
        "weeks_allowed_to_trade": int(pd.to_numeric(df_summary_by_regime_week.get("should_trade_week", pd.Series(dtype=float)), errors="coerce").sum()) if not df_summary_by_regime_week.empty else 0,
        "weeks_skipped_by_gates": int(len(df_summary_by_regime_week) - pd.to_numeric(df_summary_by_regime_week.get("should_trade_week", pd.Series(dtype=float)), errors="coerce").sum()) if not df_summary_by_regime_week.empty else 0,
        "similar_spy_weeks_total": int(pd.to_numeric(df_summary_by_regime_week.get("similar_spy_weeks", pd.Series(dtype=float)), errors="coerce").sum()) if not df_summary_by_regime_week.empty else 0,
        "hist_trades_total": int(len(df_hist_trades)),
        "hist_winners_total": int(df_hist_trades["is_win"].sum()) if not df_hist_trades.empty else 0,
        "current_candidates_total": int(len(df_next_week_candidates)),
        "real_trades_total": int(len(df_next_week_real_trades)),
        "wins_total": int(df_next_week_real_trades["is_win"].sum()) if not df_next_week_real_trades.empty else 0,
        "losses_total": int(df_next_week_real_trades["is_loss"].sum()) if not df_next_week_real_trades.empty else 0,
        "none_total": int(df_next_week_real_trades["is_none"].sum()) if not df_next_week_real_trades.empty else 0,
        "win_rate_total": float(df_next_week_real_trades["is_win"].mean()) if not df_next_week_real_trades.empty else np.nan,
        "avg_net_return_pct_total": float(pd.to_numeric(df_next_week_real_trades["net_return_pct"], errors="coerce").mean()) if not df_next_week_real_trades.empty else np.nan,
        "total_net_pnl_dollars": float(pd.to_numeric(df_next_week_real_trades["net_pnl_dollars"], errors="coerce").sum()) if not df_next_week_real_trades.empty else np.nan,
        "avg_profile_distance_mean": float(pd.to_numeric(df_summary_by_regime_week.get("avg_profile_distance", pd.Series(dtype=float)), errors="coerce").mean()) if not df_summary_by_regime_week.empty else np.nan,
        "avg_close_vs_sma50_candidates_mean": float(pd.to_numeric(df_summary_by_regime_week.get("avg_close_vs_sma50_candidates", pd.Series(dtype=float)), errors="coerce").mean()) if not df_summary_by_regime_week.empty else np.nan,
        "max_close_vs_sma50_candidates_mean": float(pd.to_numeric(df_summary_by_regime_week.get("max_close_vs_sma50_candidates", pd.Series(dtype=float)), errors="coerce").mean()) if not df_summary_by_regime_week.empty else np.nan,
        "top_similar_spy_weeks": TOP_SIMILAR_SPY_WEEKS,
        "top_candidates_next_week": TOP_CANDIDATES_NEXT_WEEK,
        "profile_vars_count": len(PROFILE_VARS),
        "spy_channel_r2_gate_enabled": int(ENABLE_SPY_CHANNEL_R2_GATE),
        "min_spy_channel_r2_required": MIN_SPY_CHANNEL_R2 if ENABLE_SPY_CHANNEL_R2_GATE else np.nan,
        "avg_profile_distance_gate_enabled": int(ENABLE_AVG_PROFILE_DISTANCE_GATE),
        "max_avg_profile_distance_allowed": MAX_AVG_PROFILE_DISTANCE if ENABLE_AVG_PROFILE_DISTANCE_GATE else np.nan,
        "initial_tp_pct": INITIAL_TP_PCT * 100.0,
        "initial_sl_pct": INITIAL_SL_PCT * 100.0,
        "first_locked_sl_pct": FIRST_LOCKED_SL_PCT * 100.0,
        "trail_step_pct": TRAIL_STEP_PCT * 100.0,
        "strategy_family": STRATEGY_FAMILY,
    }])

    result_dfs = {
        "01_target_regime_weeks": df_target_regime_weeks,
        "02_similar_spy_weeks": df_similar,
        "03_hist_trades": df_hist_trades,
        "04_hist_ticker_stats": df_hist_ticker_stats,
        "05_hist_winner_profile_overall": df_winner_profile_overall,
        "06_next_week_candidates": df_next_week_candidates,
        "07_next_week_real_trades": df_next_week_real_trades,
        "08_summary_by_regime_week": df_summary_by_regime_week,
        "09_summary_total": summary_total,
    }

    t_export_0 = time.perf_counter()
    csv_outputs, summary_xlsx_path, sheets_info_txt_path = export_bundle(out_dir, result_dfs, ts)
    cache_new_rows_written = hist_trade_cache.persist()
    t_export_1 = time.perf_counter()
    if profiler is not None:
        profiler.disable()
        profile_file = out_dir / f"runtime_profile_{ts}.txt"
        with profile_file.open("w", encoding="utf-8") as pf:
            stats = pstats.Stats(profiler, stream=pf).sort_stats("cumulative")
            stats.print_stats(max(1, int(PROFILE_TOP_N)))
        print(f"[PROFILE] runtime_profile={profile_file}", flush=True)

    print(f"Carpeta de salida: {out_dir}")
    for name, path in csv_outputs:
        print(f"{name:<30} {path}")
    if summary_xlsx_path:
        print(f"{'excel_resumen':<30} {summary_xlsx_path}")
    if sheets_info_txt_path:
        print(f"{'solapas_info_txt':<30} {sheets_info_txt_path}")
    print("[CACHE] STATS")
    print(f"trade_engine_hash: {trade_engine_hash}")
    print(f"cache_loaded_rows: {hist_trade_cache.cache_loaded_rows}")
    print(f"cache_hits_memory: {hist_trade_cache.cache_hits_memory}")
    print(f"cache_hits_disk: {hist_trade_cache.cache_hits_disk}")
    print(f"cache_misses: {hist_trade_cache.cache_misses}")
    print(f"cache_new_rows_written: {cache_new_rows_written}")
    print(f"similar_weeks_cache_rows: {len(similar_weeks_cache)}")
    print(f"perf_boot_load_sec: {round(max(0.0, t_boot_1 - t_boot_0), 3)}")
    print(f"perf_precompute_sec: {round(max(0.0, t_precompute_1 - t_precompute_0), 3)}")
    print(f"perf_regime_processing_sec: {round(max(0.0, t_weeks_1 - t_weeks_0), 3)}")
    print(f"perf_export_persist_sec: {round(max(0.0, t_export_1 - t_export_0), 3)}")
    print(f"perf_total_main_sec: {round(max(0.0, time.perf_counter() - t_main_start), 3)}")
    print("=" * 110)
    print(summary_total.to_string(index=False))


if __name__ == "__main__":
    main()
