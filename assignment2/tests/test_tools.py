import json
import os
import tempfile
import time
import unittest

from src.config import Config
from src.tools import ToolExecutor


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.cfg = Config()
        self.ex = ToolExecutor(self.root, self.cfg)
        with open(os.path.join(self.root, "a.py"), "w") as fh:
            fh.write("def f():\n    return 1\n\ndef g():\n    return 1\n")

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, name, **args):
        return self.ex.dispatch(name, json.dumps(args))[1]

    # confinement
    def test_confinement(self):
        self.assertTrue(self.call("read_file", path="../../etc/passwd").is_error)
        self.assertTrue(self.call("read_file", path="/etc/passwd").is_error)
        r = self.call("write_file", path="/tmp/madsloop_test_x.txt", content="hi")
        self.assertFalse(r.is_error, r.content)
        os.remove("/tmp/madsloop_test_x.txt")

    def test_missing_leading_slash(self):
        r = self.call("read_file", path=self.root.lstrip("/") + "/a.py")
        self.assertFalse(r.is_error, r.content)
        self.assertTrue(self.call("read_file", path="etc/passwd").is_error)

    def test_symlink_escape(self):
        os.symlink("/etc", os.path.join(self.root, "esc"))
        r = self.call("read_file", path="esc/hosts")
        self.assertTrue(r.is_error)
        self.assertIn("outside", r.content)

    # bash
    def test_bash_merges_and_exit_code(self):
        r = self.call("bash", command="echo out; echo err >&2; exit 3")
        self.assertFalse(r.is_error)
        self.assertIn("out", r.content)
        self.assertIn("err", r.content)
        self.assertTrue(r.content.endswith("[exit code 3]"))

    def test_bash_cwd(self):
        r = self.call("bash", command="pwd")
        self.assertIn(self.root, r.content)

    def test_bash_timeout_kills(self):
        t0 = time.time()
        r = self.call("bash", command="sleep 30 & sleep 30", timeout=1)
        self.assertTrue(r.is_error)
        self.assertIn("timed out", r.content)
        self.assertLess(time.time() - t0, 15)

    def test_bash_no_core_dumps(self):
        r = self.call("bash", command="ulimit -c")
        self.assertTrue(r.content.startswith("0"), r.content)

    def test_bash_env_scrubbed(self):
        os.environ["CS2680_API_KEY"] = "secret-test"
        os.environ["PYTHONPATH"] = "/tmp/agentdeps:/keep"
        try:
            r = self.call("bash", command='echo "k=${CS2680_API_KEY:-none} p=$PYTHONPATH"')
        finally:
            del os.environ["CS2680_API_KEY"]
            del os.environ["PYTHONPATH"]
        self.assertIn("k=none", r.content)
        self.assertIn("p=/keep", r.content)

    def test_bash_truncates(self):
        self.cfg.tool_output_limit = 1000
        r = self.call("bash", command="python3 -c 'print(\"x\"*50000)'")
        self.assertLessEqual(len(r.content), 1000)
        self.assertIn("truncated", r.content)

    # read_file
    def test_read_file_numbering_and_range(self):
        r = self.call("read_file", path="a.py", start_line=2, end_line=3)
        self.assertEqual(r.content, "     2\t    return 1\n     3\t")

    def test_read_file_cap(self):
        with open(os.path.join(self.root, "big.txt"), "w") as fh:
            fh.write("\n".join(str(i) for i in range(1200)))
        r = self.call("read_file", path="big.txt")
        self.assertIn("start_line=501", r.content)
        self.assertEqual(len(r.content.splitlines()), 501)

    def test_read_file_errors(self):
        self.assertTrue(self.call("read_file", path="missing.py").is_error)
        self.assertTrue(self.call("read_file", path=".").is_error)
        with open(os.path.join(self.root, "b.bin"), "wb") as fh:
            fh.write(b"\x00\x01\x02")
        self.assertTrue(self.call("read_file", path="b.bin").is_error)

    # edit_file
    def test_edit_file_matches(self):
        r = self.call("edit_file", path="a.py", old_string="return 1", new_string="return 2")
        self.assertTrue(r.is_error)
        self.assertIn("2 times", r.content)
        r = self.call("edit_file", path="a.py", old_string="return 9", new_string="return 2")
        self.assertTrue(r.is_error)
        self.assertIn("not found", r.content)
        r = self.call("edit_file", path="a.py", old_string="def g():\n    return 1", new_string="def g():\n    return 2")
        self.assertFalse(r.is_error, r.content)
        self.assertIn("return 2", r.content)
        with open(os.path.join(self.root, "a.py")) as fh:
            self.assertEqual(fh.read(), "def f():\n    return 1\n\ndef g():\n    return 2\n")

    def test_edit_file_missing_and_same(self):
        self.assertIn("write_file", self.call("edit_file", path="n.py", old_string="a", new_string="b").content)
        self.assertTrue(self.call("edit_file", path="a.py", old_string="def f", new_string="def f").is_error)

    # write_file
    def test_write_file_parents(self):
        r = self.call("write_file", path="pkg/sub/new.py", content="x = 1\n")
        self.assertFalse(r.is_error)
        self.assertTrue(os.path.exists(os.path.join(self.root, "pkg/sub/new.py")))
        self.assertTrue(self.call("write_file", path="../evil.py", content="x").is_error)

    def test_write_file_convention_note(self):
        os.makedirs(os.path.join(self.root, "lib"))
        for n in ("A", "B"):
            with open(os.path.join(self.root, "lib", n + ".ts"), "w") as fh:
                fh.write("export default class %s {}" % n)
        r = self.call("write_file", path="lib/obs.ts", content="export function obs() {}")
        self.assertFalse(r.is_error)
        self.assertIn("Convention check", r.content)
        r = self.call("write_file", path="lib/ok.ts", content="export default function ok() {}")
        self.assertNotIn("Convention check", r.content)
        r = self.call("write_file", path="/tmp/madsloop_scratch.ts", content="export const x = 1")
        self.assertNotIn("Convention check", r.content)
        os.remove("/tmp/madsloop_scratch.ts")

    # dispatch
    def test_dispatch_never_raises(self):
        args, r = self.ex.dispatch("bash", "{not json")
        self.assertTrue(r.is_error)
        self.assertEqual(args, {"_raw_arguments": "{not json"})
        self.assertTrue(self.ex.dispatch("nope", "{}")[1].is_error)
        self.assertIn("missing", self.ex.dispatch("edit_file", '{"path": "a.py"}')[1].content)
        self.assertTrue(self.ex.dispatch("read_file", '{"path": 5}')[1].is_error)
        self.assertTrue(self.ex.dispatch("read_file", '{"path": "a.py", "start_line": "x"}')[1].is_error)
        self.assertTrue(self.ex.dispatch("bash", "[1,2]")[1].is_error)

    def test_dispatch_ignores_extra_args(self):
        r = self.ex.dispatch("bash", json.dumps({"command": "echo hi", "extra": 1}))[1]
        self.assertFalse(r.is_error)


if __name__ == "__main__":
    unittest.main()
