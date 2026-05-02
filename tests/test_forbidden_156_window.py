import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestForbidden156Window(unittest.TestCase):
    def test_validator_rejects_156_in_plan(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "window_execution_plan.json").write_text(
                json.dumps(
                    {
                        "requested_windows": [4, 8, 24, 52, 156],
                        "allowed_windows": [4, 8, 24, 52],
                        "executed_windows": [4, 8, 24, 52],
                        "forbidden_windows": [156],
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "run_live_status.log").write_text("x", encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(Path("validators") / "validate_window_constraints.py"),
                    "--run-dir",
                    str(run_dir),
                    "--allowed-windows",
                    "4,8,24,52",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("156", proc.stderr)


if __name__ == "__main__":
    unittest.main()
