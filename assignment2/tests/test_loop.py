import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.agentic_loop import run
from src.config import Config
from src.trace_log import RunLogger
from tests.fakes import FakeClient, response, tool_call


def git(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def assert_paired(test, messages):
    """Every assistant tool call is followed by exactly one tool message with its id."""
    for i, m in enumerate(messages):
        if m["role"] != "assistant":
            continue
        test.assertNotIn("reasoning_content", m)
        ids = [tc["id"] for tc in m.get("tool_calls", [])]
        following = []
        for n in messages[i + 1:]:
            if n["role"] != "tool":
                break
            following.append(n["tool_call_id"])
        test.assertEqual(sorted(ids), sorted(following))


class LoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self.tmp.name)
        git(self.repo, "init", "-q")
        Path(self.repo, "calc.py").write_text("def add(a, b):\n    return a - b\n")
        git(self.repo, "add", ".")
        git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
        self.cfg = Config()
        self.cfg.quiet = True
        self.log_dir = Path(self.repo).parent / ("logs_" + os.path.basename(self.repo))
        self.logger = RunLogger(True, log_dir=self.log_dir, quiet=True)

    def tearDown(self):
        self.logger.close()
        self.tmp.cleanup()
        for f in self.log_dir.glob("*"):
            f.unlink()
        if self.log_dir.exists():
            self.log_dir.rmdir()

    def events(self):
        self.logger.close()
        files = list(self.log_dir.glob("*.jsonl"))
        return [json.loads(l) for l in files[0].read_text().splitlines()]

    def run_loop(self, script):
        client = FakeClient(script)
        reason = run("fix add", self.repo, self.cfg, self.logger, client, sleep=lambda s: None)
        return reason, client

    def test_happy_path(self):
        script = [
            response(tool_calls=[tool_call("bash", {"command": "cat calc.py"}, "a1")], reasoning_content="hmm"),
            response(tool_calls=[tool_call("edit_file", {"path": "calc.py", "old_string": "a - b",
                                                         "new_string": "a + b"}, "a2")]),
            response(tool_calls=[tool_call("done", {"summary": "fixed"}, "a3")]),
        ]
        reason, client = self.run_loop(script)
        self.assertEqual(reason, "done")
        self.assertIn("a + b", Path(self.repo, "calc.py").read_text())
        last = client.requests[-1]
        assert_paired(self, last)
        ev = self.events()
        self.assertEqual(ev[0]["event"], "run_start")
        self.assertEqual(ev[-1], dict(ev[-1], event="run_end", reason="done", num_iterations=3))
        # logged result equals what the model saw
        results = [e["result"] for e in ev if e["event"] == "tool_result"]
        tool_msgs = [m["content"] for m in last if m["role"] == "tool"]
        self.assertEqual(results[:2], tool_msgs)

    def test_malformed_args_paired(self):
        script = [
            response(tool_calls=[tool_call("bash", "{oops", "b1"), tool_call("nope", {}, "b2"),
                                 tool_call("read_file", {"path": "calc.py"}, None)]),
            response(tool_calls=[tool_call("edit_file", {"path": "calc.py", "old_string": "a - b",
                                                         "new_string": "a + b"}, "b3")]),
            response(tool_calls=[tool_call("done", {"summary": "x"}, "b4")]),
        ]
        reason, client = self.run_loop(script)
        self.assertEqual(reason, "done")
        assert_paired(self, client.requests[-1])
        ids = [tc["id"] for tc in client.requests[1][2]["tool_calls"]]
        self.assertEqual(ids, ["b1", "b2", "call_1_2"])
        logged = [e for e in self.events() if e["event"] == "tool_call"]
        self.assertEqual(logged[0]["arguments"], {"_raw_arguments": "{oops"})

    def test_nudge_then_no_tool_calls(self):
        reason, client = self.run_loop([response("I think it's fixed"), response("really")])
        self.assertEqual(reason, "no_tool_calls")
        self.assertEqual(client.requests[1][-1]["role"], "user")
        self.assertEqual(self.events()[-1]["num_iterations"], 2)

    def test_max_iterations(self):
        self.cfg.max_iterations = 3
        script = [response(tool_calls=[tool_call("bash", {"command": "true"}, "m%d" % i)]) for i in range(3)]
        reason, client = self.run_loop(script)
        self.assertEqual(reason, "max_iterations")
        self.assertEqual(len(client.requests), 3)
        self.assertTrue(any("steps" in m["content"] for m in client.requests[0] if m["role"] == "user"))

    def test_done_clean_tree_rejected_once(self):
        script = [response(tool_calls=[tool_call("done", {"summary": "x"}, "d1")]),
                  response(tool_calls=[tool_call("done", {"summary": "impossible"}, "d2")])]
        reason, client = self.run_loop(script)
        self.assertEqual(reason, "done")
        self.assertIn("no changes", client.requests[1][-1]["content"])

    def test_done_with_stash_rejected(self):
        script = [
            response(tool_calls=[tool_call("bash", {"command": "sed -i.bak s/-/+/ calc.py && rm calc.py.bak && git stash -q"}, "s1")]),
            response(tool_calls=[tool_call("done", {"summary": "x"}, "s2")]),
            response(tool_calls=[tool_call("bash", {"command": "git stash pop -q"}, "s3")]),
            response(tool_calls=[tool_call("done", {"summary": "x"}, "s4")]),
        ]
        reason, client = self.run_loop(script)
        self.assertEqual(reason, "done")
        self.assertIn("stash", client.requests[2][-1]["content"])
        self.assertIn("a + b", Path(self.repo, "calc.py").read_text())

    def test_done_with_staged_rejected_and_cleanup(self):
        self.cfg.max_iterations = 2
        script = [
            response(tool_calls=[tool_call("bash", {"command": "sed -i.bak s/-/+/ calc.py && rm calc.py.bak && git add calc.py"}, "g1")]),
            response(tool_calls=[tool_call("done", {"summary": "x"}, "g2")]),
        ]
        reason, client = self.run_loop(script)
        self.assertEqual(reason, "max_iterations")
        out = subprocess.run(["git", "-C", self.repo, "diff", "--cached", "--name-only"],
                             stdout=subprocess.PIPE).stdout
        self.assertEqual(out, b"")  # cleanup unstaged it
        self.assertIn("a + b", Path(self.repo, "calc.py").read_text())

    def test_compaction(self):
        big = "x" * 5000
        script = []
        for i in range(16):
            script.append(response(tool_calls=[tool_call("bash", {"command": "printf '%s'" % big}, "c%d" % i)],
                                   prompt_tokens=95000 if i == 14 else 1000))
        script.append(response(tool_calls=[tool_call("edit_file", {"path": "calc.py", "old_string": "a - b",
                                                                   "new_string": "a + b"}, "e")]))
        script.append(response(tool_calls=[tool_call("done", {"summary": "x"}, "f")]))
        reason, client = self.run_loop(script)
        self.assertEqual(reason, "done")
        before = client.requests[14]
        after = client.requests[15]
        self.assertFalse(any(m["content"].startswith("[output elided") for m in before if m["role"] == "tool"))
        elided = [m for m in after if m["role"] == "tool" and m["content"].startswith("[output elided")]
        self.assertEqual(len(elided), 15 - self.cfg.compact_keep_tool_msgs)
        assert_paired(self, after)

    def test_core_dump_removed(self):
        Path(self.repo, "core.txt").write_text("keep me")  # pre-existing names are untouched
        cmd = ("printf '\\177ELFxx' > core && printf '\\177ELFyy' > core.123 && printf 'text' > core.9 "
               "&& sed -i.bak s/-/+/ calc.py && rm calc.py.bak")
        script = [response(tool_calls=[tool_call("bash", {"command": cmd}, "k1")]),
                  response(tool_calls=[tool_call("done", {"summary": "x"}, "k2")])]
        reason, _ = self.run_loop(script)
        self.assertEqual(reason, "done")
        self.assertFalse(Path(self.repo, "core").exists())
        self.assertFalse(Path(self.repo, "core.123").exists())
        self.assertTrue(Path(self.repo, "core.9").exists())  # not an ELF file
        self.assertTrue(Path(self.repo, "core.txt").exists())

    def test_done_rejected_once_for_export_convention(self):
        lib = Path(self.repo, "lib")
        lib.mkdir()
        (lib / "A.ts").write_text("export default class A {}")
        (lib / "B.ts").write_text("export default class B {}")
        git(self.repo, "add", ".")
        git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "lib")
        script = [
            response(tool_calls=[tool_call("bash", {"command": "printf 'export function obs() {}' > lib/obs.ts"}, "v1")]),
            response(tool_calls=[tool_call("done", {"summary": "x"}, "v2")]),
            response(tool_calls=[tool_call("bash", {"command": "printf '\\nexport default obs;' >> lib/obs.ts"}, "v3")]),
            response(tool_calls=[tool_call("done", {"summary": "x"}, "v4")]),
        ]
        reason, client = self.run_loop(script)
        self.assertEqual(reason, "done")
        rejection = client.requests[2][-1]["content"]
        self.assertIn("convention", rejection)
        self.assertIn("lib/obs.ts", rejection)

    def test_api_error_ends_with_error(self):
        reason, _ = self.run_loop([ValueError("boom")])
        self.assertEqual(reason, "error")
        self.assertEqual(self.events()[-1]["reason"], "error")

    def test_text_tool_call_fallback(self):
        text = '<tool_call>\n{"name": "edit_file", "arguments": {"path": "calc.py", "old_string": "a - b", "new_string": "a + b"}}\n</tool_call>'
        script = [response(text), response(tool_calls=[tool_call("done", {"summary": "x"}, "t2")])]
        reason, client = self.run_loop(script)
        self.assertEqual(reason, "done")
        assert_paired(self, client.requests[-1])


if __name__ == "__main__":
    unittest.main()
