import json
import tempfile
import unittest
from pathlib import Path

from validators.validate_required_run_artifacts import classify, RC_COMPLETE


class TestBlockedPreflightComplete(unittest.TestCase):
    def test_blocked_preflight_is_complete(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "run_live_status.log").write_text("x", encoding="utf-8")
            (run_dir / "window_execution_plan.json").write_text(json.dumps({"allowed_windows": [4, 8, 24, 52]}), encoding="utf-8")
            (run_dir / "run_status.json").write_text(json.dumps({"status": "blocked_preflight"}), encoding="utf-8")
            (run_dir / "experiment_manifest.json").write_text(json.dumps({"status": "blocked_preflight"}), encoding="utf-8")

            rc, msg = classify(run_dir)
            self.assertEqual(rc, RC_COMPLETE)
            self.assertEqual(msg, "BLOCKED_PREFLIGHT_COMPLETE")


if __name__ == "__main__":
    unittest.main()
