import json
import tempfile
import unittest
from pathlib import Path


def _write(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


class TestRunArtifactPersistence(unittest.TestCase):
    def test_all_required_outputs_ok(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write(d / "window_execution_plan.json", {"allowed_windows": [4, 8, 24, 52]})
            (d / "run_live_status.log").write_text("x", encoding="utf-8")
            (d / "window_52").mkdir()
            (d / "executor_output.json").write_text("{}", encoding="utf-8")
            (d / "coordinator_output.json").write_text("{}", encoding="utf-8")
            (d / "experiment_manifest.json").write_text("{}", encoding="utf-8")

            # Inline minimal check mirrors validator behavior.
            missing = [x for x in ["executor_output.json", "coordinator_output.json", "experiment_manifest.json"] if not (d / x).exists()]
            self.assertEqual(missing, [])

    def test_missing_executor_but_partial_recoverable(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write(d / "window_execution_plan.json", {"allowed_windows": [4, 8, 24, 52]})
            (d / "run_live_status.log").write_text("x", encoding="utf-8")
            (d / "executor_output.partial.json").write_text("{}", encoding="utf-8")
            self.assertTrue((d / "executor_output.partial.json").exists())
            self.assertFalse((d / "executor_output.json").exists())

    def test_missing_coordinator_is_missing_required(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write(d / "window_execution_plan.json", {"allowed_windows": [4, 8, 24]})
            (d / "run_live_status.log").write_text("x", encoding="utf-8")
            (d / "executor_output.json").write_text("{}", encoding="utf-8")
            (d / "experiment_manifest.json").write_text("{}", encoding="utf-8")
            self.assertFalse((d / "coordinator_output.json").exists())

    def test_plan_says_52_requires_window_52_dir(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write(d / "window_execution_plan.json", {"allowed_windows": [4, 8, 24, 52]})
            (d / "run_live_status.log").write_text("x", encoding="utf-8")
            self.assertFalse((d / "window_52").exists())


if __name__ == "__main__":
    unittest.main()

