import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import madsLoop
from tests.fakes import FakeClient, response, tool_call

ROOT = Path(__file__).resolve().parent.parent


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.saved_key = os.environ.get("CS2680_API_KEY")
        os.environ["MADSLOOP_QUIET"] = "1"

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()
        os.environ.pop("MADSLOOP_QUIET", None)
        if self.saved_key is None:
            os.environ.pop("CS2680_API_KEY", None)
        else:
            os.environ["CS2680_API_KEY"] = self.saved_key

    def logs(self):
        files = list(Path(self.tmp.name, "madsLoop_logs").glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        return [json.loads(l) for l in files[0].read_text().splitlines()]

    def test_parse_args(self):
        a = madsLoop.parse_args(["-p", "fix it", "--log", "/app"])
        self.assertEqual((a.problem, a.log, a.workdir), ("fix it", True, "/app"))
        self.assertFalse(madsLoop.parse_args(["/app", "-p", "x"]).log)

    def test_main_runs_and_logs(self):
        os.environ["CS2680_API_KEY"] = "test"
        client = FakeClient([response(tool_calls=[tool_call("write_file", {"path": "new.txt", "content": "x"}, "1")]),
                             response(tool_calls=[tool_call("done", {"summary": "ok"}, "2")])])
        rc = madsLoop.main(["-p", "x", "--log", self.repo], client_factory=lambda cfg, key: client)
        self.assertEqual(rc, 0)
        ev = self.logs()
        self.assertEqual(ev[-1]["reason"], "done")

    def test_no_log_flag_no_dir(self):
        os.environ["CS2680_API_KEY"] = "test"
        client = FakeClient([response("hi"), response("bye")])
        madsLoop.main(["-p", "x", self.repo], client_factory=lambda cfg, key: client)
        self.assertFalse(Path(self.tmp.name, "madsLoop_logs").exists())

    def test_missing_key(self):
        os.environ.pop("CS2680_API_KEY", None)
        rc = madsLoop.main(["-p", "x", "--log", self.repo])
        self.assertEqual(rc, 0)
        ev = self.logs()
        self.assertEqual([e["event"] for e in ev], ["run_start", "run_end"])
        self.assertEqual(ev[-1]["reason"], "error")

    def test_subprocess_stdout_empty(self):
        env = dict(os.environ)
        env.pop("CS2680_API_KEY", None)
        proc = subprocess.run([sys.executable, str(ROOT / "madsLoop.py"), "-p", "x", "--log", self.repo],
                              cwd=self.tmp.name, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")
        self.assertIn(b"CS2680_API_KEY", proc.stderr)
        proc = subprocess.run([sys.executable, str(ROOT / "madsLoop.py")], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
        self.assertEqual((proc.returncode, proc.stdout), (0, b""))


if __name__ == "__main__":
    unittest.main()
