from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate persistent dataset cache manifest and files.")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    cfg_path = repo / "config" / "dataset_cache_config.json"
    if not cfg_path.exists():
        print("FAIL_CACHE_INVALID: missing config/dataset_cache_config.json", file=sys.stderr)
        return 2
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    cache_dir = (repo / cfg.get("cache_dir", "_dataset_cache/prepared")).resolve()
    manifest_path = cache_dir / "cache_manifest.json"
    if not manifest_path.exists():
        print("OK: cache config exists; manifest not built yet")
        return 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    entries = manifest.get("entries", {}) if isinstance(manifest, dict) else {}
    bad = []
    for key, entry in entries.items():
        cache_file = Path(str(entry.get("cache_file", "")))
        source_path = Path(str(entry.get("source_path", "")))
        if not cache_file.exists():
            bad.append(f"missing cache_file for {key}: {cache_file}")
            continue
        if not source_path.exists():
            bad.append(f"missing source_path for {key}: {source_path}")
            continue
        st = source_path.stat()
        if int(entry.get("source_size", -1)) != int(st.st_size):
            bad.append(f"source_size mismatch for {key}")
        if int(entry.get("source_mtime_ns", -1)) != int(st.st_mtime_ns):
            bad.append(f"source_mtime_ns mismatch for {key}")
    if bad:
        print("FAIL_CACHE_INVALID:")
        for b in bad:
            print(f"- {b}")
        return 2
    print(f"OK: dataset cache manifest valid entries={len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
