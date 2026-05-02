import json
import tempfile
import unittest
from pathlib import Path

from validators.validate_required_run_artifacts import classify, RC_INCOMPLETE_NO_PARENT


class TestNoParentIncompleteRuns(unittest.TestCase):
    def test_missing_final_outputs_without_partial_is_no_parent(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "run_live_status.log").write_text("x", encoding="utf-8")
            (run_dir / "window_execution_plan.json").write_text(json.dumps({"allowed_windows": [4, 8, 24, 52]}), encoding="utf-8")

            rc, msg = classify(run_dir)
            self.assertEqual(rc, RC_INCOMPLETE_NO_PARENT)
            self.assertIn("INCOMPLETE_NO_PARENT", msg)


if __name__ == "__main__":
    unittest.main()
