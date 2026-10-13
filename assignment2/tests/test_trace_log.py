import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src.trace_log import REQUIRED_FIELDS, RunLogger


class TraceLogTest(unittest.TestCase):
    def test_disabled_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            log = RunLogger(False, log_dir=Path(d) / "madsLoop_logs", quiet=True)
            log.run_start("m", "/app")
            log.run_end("done", 1)
            self.assertFalse((Path(d) / "madsLoop_logs").exists())

    def test_disabled_still_validates_fields(self):
        log = RunLogger(False, quiet=True)
        with self.assertRaises(ValueError):
            log._emit("run_end", reason="done")

    def test_lines_have_exact_fields(self):
        with tempfile.TemporaryDirectory() as d:
            log_dir = Path(d) / "madsLoop_logs"
            log = RunLogger(True, log_dir=log_dir, quiet=True)
            self.assertFalse(log_dir.exists())  # lazy
            log.run_start("qwen", "/app")
            log.api_request(1, 10, 2, 12)
            log.api_retry(1, "RateLimitError: slow down", 1.5)
            log.tool_call(1, "bash", {"command": "ls"})
            log.tool_result(1, "bash", "a\nb", False)
            log.run_end("done", 1)
            log.close()
            files = list(log_dir.glob("run_*.jsonl"))
            self.assertEqual(len(files), 1)
            lines = [json.loads(l) for l in files[0].read_text().splitlines()]
            self.assertEqual([l["event"] for l in lines],
                             ["run_start", "api_request", "api_retry", "tool_call", "tool_result", "run_end"])
            for rec in lines:
                self.assertEqual(set(rec), REQUIRED_FIELDS[rec["event"]] | {"timestamp", "event"})
                ts = datetime.fromisoformat(rec["timestamp"])
                self.assertIsNotNone(ts.utcoffset())
                self.assertTrue(rec["timestamp"].endswith("+00:00"))

    def test_wrong_fields_raise(self):
        log = RunLogger(True, log_dir=tempfile.mkdtemp(), quiet=True)
        with self.assertRaises(ValueError):
            log._emit("tool_call", iteration=1, tool_name="x")
        with self.assertRaises(ValueError):
            log._emit("bogus")


if __name__ == "__main__":
    unittest.main()
