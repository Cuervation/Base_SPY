from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate insufficient depth policy content.")
    ap.add_argument(
        "--policy",
        default=str(Path("governance") / "insufficient_depth_policy.md"),
        help="Path to policy markdown",
    )
    args = ap.parse_args()

    path = Path(args.policy).resolve()
    if not path.exists():
        print(f"ERROR: missing policy: {path}", file=sys.stderr)
        return 2

    txt = path.read_text(encoding="utf-8", errors="ignore").lower()
    required = [
        "insufficient_depth",
        "non-fatal",
        "preserve",
        "24/52",
        "accepted_for_followup",
        "promoted_to_baseline",
    ]
    missing = [r for r in required if r not in txt]
    if missing:
        for m in missing:
            print(f"ERROR: missing required phrase: {m}", file=sys.stderr)
        return 3

    print("OK: insufficient depth policy contains required rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

