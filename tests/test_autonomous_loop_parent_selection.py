import json
import tempfile
import unittest
from pathlib import Path

from scripts.loop import run_infinite_research_loop as loop


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_valid_run(repo: Path, run_id: str) -> Path:
    run_dir = repo / "runs" / "multi_agent_runs" / f"{run_id}_260425000000"
    run_dir.mkdir(parents=True, exist_ok=True)
    fake_script = repo / "scripts" / "fake_parent.py"
    fake_script.parent.mkdir(parents=True, exist_ok=True)
    fake_script.write_text("print('ok')\n", encoding="utf-8")
    _write_json(
        run_dir / "executor_output.json",
        {"status": "run_ok", "script_executed": str(fake_script), "windows": {}, "core_metrics": {}},
    )
    _write_json(
        run_dir / "coordinator_output.json",
        {
            "role": "coordinator",
            "decision_type": "accepted_for_followup",
            "accepted_for_followup": True,
            "promoted_to_baseline": False,
            "auditor_v2_evaluation": {"recommended_next_action": "refine_current_branch"},
        },
    )
    _write_json(run_dir / "experiment_manifest.json", {"status": "run_ok"})
    return run_dir


class TestAutonomousLoopParentSelection(unittest.TestCase):
    def test_invalid_parent_is_skipped_in_favor_of_champion(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _write_json(
                repo / "config" / "paths_config.json",
                {
                    "runs": {
                        "multi_agent_runs": "runs/multi_agent_runs",
                        "champion_runs_json": "runs/champion_runs/champion_runs.json",
                    },
                    "state": {
                        "research_state": "state/research_state.json",
                        "current_baseline": "state/current_baseline.json",
                    },
                },
            )
            _write_json(repo / "state" / "research_state.json", {
                "parent_state": {
                    "current_parent_run_id": "EXP_142",
                    "last_useful_run_id": "EXP_142",
                },
                "state_tracking": {
                    "last_useful_run_id": "EXP_142",
                    "last_followup_run_id": "EXP_142",
                },
            })
            _write_json(repo / "runs" / "champion_runs" / "champion_runs.json", {
                "version": 1,
                "updated_at": "2026-04-25T00:00:00",
                "champions": {"best_recent_followup_run_id": "EXP_144"},
                "metadata": {"best_recent_followup_run_id": {}},
            })
            _write_json(repo / "runs" / "multi_agent_runs" / "EXP_142_260425000000" / "recovery_status.json", {
                "do_not_use_as_parent": True,
                "safe_for_strategy_analysis": False,
                "safe_for_process_analysis": True,
            })
            _write_json(repo / "runs" / "multi_agent_runs" / "EXP_144_260425000000" / "recovery_status.json", {
                "do_not_use_as_parent": False,
                "safe_for_strategy_analysis": True,
                "safe_for_process_analysis": True,
            })
            _make_valid_run(repo, "EXP_144")

            rs = json.loads((repo / "state" / "research_state.json").read_text(encoding="utf-8"))
            champions = json.loads((repo / "runs" / "champion_runs" / "champion_runs.json").read_text(encoding="utf-8"))
            ctx, src = loop.select_parent_context(repo, rs, champions)

            self.assertIsNotNone(ctx)
            self.assertEqual(ctx["run_id"], "EXP_144")
            self.assertIn("champion", src)


if __name__ == "__main__":
    unittest.main()
