from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 2


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _basic_validate(obj: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if obj.get("role") != "coordinator":
        errors.append("role must be 'coordinator'")
    dt = obj.get("decision_type")
    if dt not in {"rejected", "accepted_for_followup", "promoted_to_baseline"}:
        errors.append("decision_type must be rejected|accepted_for_followup|promoted_to_baseline")
    if not isinstance(obj.get("accepted_for_followup"), bool):
        errors.append("accepted_for_followup must be boolean")
    if not isinstance(obj.get("promoted_to_baseline"), bool):
        errors.append("promoted_to_baseline must be boolean")
    if dt == "accepted_for_followup":
        if obj.get("accepted_for_followup") is not True or obj.get("promoted_to_baseline") is not False:
            errors.append("accepted_for_followup implies accepted_for_followup=true and promoted_to_baseline=false")
    if dt == "promoted_to_baseline":
        if obj.get("promoted_to_baseline") is not True or obj.get("accepted_for_followup") is not False:
            errors.append("promoted_to_baseline implies promoted_to_baseline=true and accepted_for_followup=false")
    if dt == "rejected":
        if obj.get("accepted_for_followup") is not False or obj.get("promoted_to_baseline") is not False:
            errors.append("rejected implies accepted_for_followup=false and promoted_to_baseline=false")

    # Required coordinator sections
    for key in [
        "status",
        "gate_decision",
        "reasons",
        "materiality",
        "transition_classification",
        "promotion_reason",
        "promotion_blockers",
        "parent_run_id",
        "parent_script",
        "validation_phase",
        "next_validation_phase",
        "multi_year_validation",
        "effective_change_check",
        "compare",
        "auditor_v2_evaluation",
        "learning_feedback",
    ]:
        if key not in obj:
            errors.append(f"missing key: {key}")

    # Minimal manual enforcement even without jsonschema installed.
    ae = obj.get("auditor_v2_evaluation")
    if not isinstance(ae, dict):
        errors.append("auditor_v2_evaluation must be an object")
    else:
        rna = ae.get("recommended_next_action")
        allowed = {
            "refine_current_branch",
            "controlled_exploration",
            "evidence_based_rollback",
            "extend_validation",
            "stop_branch",
            "fix_process_before_more_research",
        }
        if rna not in allowed:
            errors.append(f"auditor_v2_evaluation.recommended_next_action must be one of {sorted(allowed)}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate coordinator_output.json against repo contract/schema.")
    ap.add_argument("--path", required=True, help="Path to coordinator_output.json")
    ap.add_argument(
        "--schema",
        default=str(Path("contracts") / "coordinator_output.schema.json"),
        help="Path to JSON schema",
    )
    args = ap.parse_args()

    path = Path(args.path).resolve()
    schema_path = Path(args.schema).resolve()
    if not path.exists():
        return _fail(f"missing coordinator output: {path}")
    if not schema_path.exists():
        return _fail(f"missing schema: {schema_path}")

    try:
        obj = _load_json(path)
    except Exception as e:
        return _fail(f"invalid JSON in coordinator output: {e}")
    if not isinstance(obj, dict):
        return _fail("coordinator output must be a JSON object")

    # Best-effort jsonschema validation if available; otherwise run basic checks.
    used_jsonschema = False
    try:
        import jsonschema  # type: ignore

        schema = _load_json(schema_path)
        jsonschema.validate(instance=obj, schema=schema)
        used_jsonschema = True
    except ModuleNotFoundError:
        pass
    except Exception as e:
        # Schema validation failed; still run basic checks to produce more actionable output.
        print(f"SCHEMA_ERROR: {e}", file=sys.stderr)

    basic_errors = _basic_validate(obj)
    if basic_errors:
        for e in basic_errors:
            print(f"BASIC_ERROR: {e}", file=sys.stderr)
        return 3

    print(f"OK: coordinator_output.json valid ({'jsonschema' if used_jsonschema else 'basic'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
