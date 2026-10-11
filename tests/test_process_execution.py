from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.process import ProcessError, run_process


class ProcessExecutionTests(unittest.TestCase):
    def test_argv_execution_classifies_exit_code_and_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_process(
                (sys.executable, "-c", "import sys; print('secret-value'); sys.exit(7)"),
                cwd=Path(temporary), timeout_seconds=2, secrets=("secret-value",),
            )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.exit_status, 7)
        self.assertIn("[REDACTED]", result.stdout)
        self.assertNotIn("secret-value", result.stdout)

    def test_timeout_and_cancellation_are_distinct_from_exit_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            timed_out = run_process((sys.executable, "-c", "import time; time.sleep(2)"),
                                    cwd=Path(temporary), timeout_seconds=0.1)
            self.assertEqual(timed_out.status, "timed_out")
            self.assertIsNone(timed_out.exit_status)
            cancelled_event = threading.Event()
            cancelled_event.set()
            cancelled = run_process((sys.executable, "-c", "import time; time.sleep(2)"),
                                    cwd=Path(temporary), timeout_seconds=2,
                                    cancel_event=cancelled_event)
            self.assertEqual(cancelled.status, "cancelled")
            self.assertIsNone(cancelled.exit_status)

    def test_shell_strings_and_invalid_bounds_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ProcessError):
                run_process("echo unsafe", cwd=Path(temporary), timeout_seconds=1)
            with self.assertRaises(ProcessError):
                run_process((sys.executable,), cwd=Path(temporary), timeout_seconds=601)
            result = run_process((sys.executable, "-c", "print('x' * 100)"),
                                 cwd=Path(temporary), timeout_seconds=1, max_output_bytes=10)
            self.assertTrue(result.output_truncated)
            self.assertLessEqual(len(result.stdout.encode("utf-8")), 10)


if __name__ == "__main__":
    unittest.main()
