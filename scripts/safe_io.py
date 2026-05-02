#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _sleep_for_attempt(attempt: int, base_delay: float) -> None:
    # Small incremental backoff. Keeps Windows antivirus/indexer/VSCode locks from killing the loop.
    time.sleep(max(0.0, base_delay) * (attempt + 1))


def safe_json_write(
    path: Path,
    obj: Any,
    *,
    retries: int = 12,
    delay_seconds: float = 0.25,
    indent: int = 2,
    ensure_ascii: bool = False,
    backup_on_failure: bool = True,
) -> None:
    """
    Robust JSON write for Windows:
    - writes in the same directory,
    - uses a temp file unique by pid + timestamp,
    - retries PermissionError/OSError,
    - uses os.replace for atomic replacement,
    - optionally writes a .failed_write fallback for diagnosis.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent)
    last_exc: Optional[BaseException] = None

    for attempt in range(max(1, int(retries))):
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(str(tmp), str(path))
            return
        except (PermissionError, OSError) as exc:
            last_exc = exc
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            if attempt + 1 >= max(1, int(retries)):
                break
            _sleep_for_attempt(attempt, delay_seconds)

    if backup_on_failure:
        try:
            failed = path.with_name(f"{path.name}.failed_write.{os.getpid()}.{time.time_ns()}.json")
            failed.write_text(payload, encoding="utf-8")
        except Exception:
            pass
    if last_exc:
        raise last_exc


def safe_text_write(
    path: Path,
    text: str,
    *,
    retries: int = 12,
    delay_seconds: float = 0.25,
    backup_on_failure: bool = True,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = str(text)
    last_exc: Optional[BaseException] = None

    for attempt in range(max(1, int(retries))):
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(str(tmp), str(path))
            return
        except (PermissionError, OSError) as exc:
            last_exc = exc
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            if attempt + 1 >= max(1, int(retries)):
                break
            _sleep_for_attempt(attempt, delay_seconds)

    if backup_on_failure:
        try:
            failed = path.with_name(f"{path.name}.failed_write.{os.getpid()}.{time.time_ns()}.txt")
            failed.write_text(payload, encoding="utf-8")
        except Exception:
            pass
    if last_exc:
        raise last_exc


def safe_append_jsonl(
    path: Path,
    payload: Dict[str, Any],
    *,
    retries: int = 12,
    delay_seconds: float = 0.20,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    last_exc: Optional[BaseException] = None
    for attempt in range(max(1, int(retries))):
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
            return
        except (PermissionError, OSError) as exc:
            last_exc = exc
            if attempt + 1 >= max(1, int(retries)):
                break
            _sleep_for_attempt(attempt, delay_seconds)
    if last_exc:
        raise last_exc


def safe_append_csv_row(
    path: Path,
    header: List[str],
    row: Dict[str, Any],
    *,
    delimiter: str = ";",
    retries: int = 12,
    delay_seconds: float = 0.20,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    last_exc: Optional[BaseException] = None
    for attempt in range(max(1, int(retries))):
        try:
            file_exists = path.exists()
            with path.open("a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter=delimiter)
                if not file_exists:
                    writer.writerow(header)
                writer.writerow([_to_text(row.get(k, "")) for k in header])
            return
        except (PermissionError, OSError) as exc:
            last_exc = exc
            if attempt + 1 >= max(1, int(retries)):
                break
            _sleep_for_attempt(attempt, delay_seconds)
    if last_exc:
        raise last_exc


def _read_pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        # Windows and Unix compatible enough: signal 0 only checks process existence.
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False
    except Exception:
        return False


@contextmanager
def single_instance_lock(
    lock_path: Path,
    *,
    enabled: bool = True,
    stale_after_seconds: int = 8 * 60 * 60,
    retries: int = 1,
    delay_seconds: float = 1.0,
) -> Iterator[None]:
    """
    Single-writer guard. Creates lock file with O_EXCL.
    If an old lock belongs to a dead pid or is stale, it is removed.
    """
    if not enabled:
        yield
        return

    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    acquired = False
    last_reason = ""

    for attempt in range(max(1, int(retries))):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps({"pid": os.getpid(), "created_at": _now_iso()}, ensure_ascii=False, indent=2))
            acquired = True
            break
        except FileExistsError:
            last_reason = "lock_exists"
            try:
                raw = json.loads(lock_path.read_text(encoding="utf-8-sig"))
                pid = int(raw.get("pid") or 0)
            except Exception:
                raw = {}
                pid = 0

            try:
                age = time.time() - lock_path.stat().st_mtime
            except Exception:
                age = 0

            stale = bool(age > int(stale_after_seconds))
            dead = bool(pid and not _read_pid_is_alive(pid))
            invalid = bool(not pid)

            if stale or dead or invalid:
                try:
                    lock_path.unlink()
                    continue
                except Exception as exc:
                    last_reason = f"cannot_remove_stale_lock:{exc}"

            if attempt + 1 < max(1, int(retries)):
                time.sleep(max(0.0, delay_seconds))
        except OSError as exc:
            last_reason = str(exc)
            if attempt + 1 < max(1, int(retries)):
                time.sleep(max(0.0, delay_seconds))

    if not acquired:
        raise RuntimeError(f"another autonomous loop seems to be running; lock={lock_path}; reason={last_reason}")

    try:
        yield
    finally:
        try:
            current = json.loads(lock_path.read_text(encoding="utf-8-sig"))
            if int(current.get("pid") or 0) == os.getpid():
                lock_path.unlink()
        except Exception:
            pass
