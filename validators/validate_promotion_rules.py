from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _require_phrases(path: Path, phrases: list[str]) -> list[str]:
    txt = path.read_text(encoding="utf-8", errors="ignore").lower()
    return [p for p in phrases if p.lower() not in txt]


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate baseline promotion and follow-up acceptance policy docs.")
    ap.add_argument(
        "--promotion",
        default=str(Path("governance") / "baseline_promotion_policy.md"),
        help="Baseline promotion policy path",
    )
    ap.add_argument(
        "--followup",
        default=str(Path("governance") / "followup_acceptance_policy.md"),
        help="Follow-up acceptance policy path",
    )
    args = ap.parse_args()

    promo = Path(args.promotion).resolve()
    follow = Path(args.followup).resolve()
    for p in [promo, follow]:
        if not p.exists():
            print(f"ERROR: missing policy file: {p}", file=sys.stderr)
            return 2

    miss_promo = _require_phrases(
        promo,
        [
            "promote",
            "robust",
            "vs spy",
            "promoted_to_baseline",
            "accepted_for_followup",
            "distinct",
        ],
    )
    miss_follow = _require_phrases(
        follow,
        [
            "accepted_for_followup",
            "promoted_to_baseline",
            "non-fatal",
            "insufficient_depth",
        ],
    )
    if miss_promo or miss_follow:
        for m in miss_promo:
            print(f"ERROR: baseline_promotion_policy missing phrase: {m}", file=sys.stderr)
        for m in miss_follow:
            print(f"ERROR: followup_acceptance_policy missing phrase: {m}", file=sys.stderr)
        return 3

    print("OK: promotion and follow-up policy docs look consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

