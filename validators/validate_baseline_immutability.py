from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate baseline immutability via SHA256 hashes.")
    ap.add_argument("--before-hash", default="", help="Expected hash before run (SHA256 hex)")
    ap.add_argument("--after-hash", default="", help="Hash after run (SHA256 hex)")
    ap.add_argument("--baseline", default="state/current_baseline.json", help="Baseline file path")
    ap.add_argument("--expected-hash", default="", help="Expected baseline SHA256 hash")
    args = ap.parse_args()

    before = (args.before_hash or "").strip().upper()
    after = (args.after_hash or "").strip().upper()
    expected = (args.expected_hash or "").strip().upper()

    if before and after:
        if before != after:
            print(f"ERROR: baseline hash changed before={before} after={after}", file=sys.stderr)
            return 3
        print("OK: baseline hash unchanged (before==after)")
        return 0

    baseline = Path(args.baseline).resolve()
    if not baseline.exists():
        print(f"ERROR: baseline not found: {baseline}", file=sys.stderr)
        return 2

    actual = sha256_file(baseline)
    if expected and actual != expected:
        print(f"ERROR: baseline hash mismatch expected={expected} actual={actual}", file=sys.stderr)
        return 3
    if expected:
        print("OK: baseline hash matches expected")
        return 0

    print(f"INFO: baseline SHA256={actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

