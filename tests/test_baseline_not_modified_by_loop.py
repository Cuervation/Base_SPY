import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.loop import run_infinite_research_loop as loop


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class TestBaselineNotModifiedByLoop(unittest.TestCase):
    def test_dry_run_does_not_modify_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            baseline = repo / "state" / "current_baseline.json"
            _write_json(baseline, {"version": 1, "active_config": {"TOP_CANDIDATES_NEXT_WEEK": 5}})
            _write_json(
                repo / "config" / "autonomous_loop_config.json",
                {
                    "windows": [4, 8, 24, 52],
                    "forbidden_windows": [156],
                    "strict_windows": True,
                    "max_iterations": 0,
                    "baseline_path": "state/current_baseline.json",
                    "research_state_path": "state/research_state.json",
                    "experiment_log_path": "trackers/experiment_log.csv",
                    "dependencies_path": "config/parameter_dependencies.json",
                    "runs_root": "runs/multi_agent_runs",
                },
            )
            before = _sha256(baseline)
            cfg = loop.load_config(repo)
            rc = loop.run_loop(repo, cfg, max_iterations=0, dry_run=True)
            after = _sha256(baseline)
            self.assertEqual(rc, 0)
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
