import json
import unittest

from src.context import compact_messages, elide_write_file_arguments, truncate


def _conv(n_tools, size=500):
    msgs = [{"role": "system", "content": "s" * 1000}, {"role": "user", "content": "u" * 1000}]
    for i in range(n_tools):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": "c%d" % i, "type": "function", "function": {"name": "bash", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": "c%d" % i, "content": "x" * size})
    return msgs


class TruncateTest(unittest.TestCase):
    def test_short_text_unchanged(self):
        self.assertEqual(truncate("abc", 100), "abc")

    def test_long_text_bounded_with_marker(self):
        text = "".join(chr(97 + i % 26) for i in range(50000))
        out = truncate(text, 1000)
        self.assertLessEqual(len(out), 1000)
        self.assertIn("truncated", out)
        self.assertTrue(out.startswith(text[:500]))
        self.assertTrue(out.endswith(text[-300:]))

    def test_none(self):
        self.assertEqual(truncate(None, 10), "")


class CompactTest(unittest.TestCase):
    def test_keeps_last_k_and_pairing(self):
        msgs = _conv(10)
        compact_messages(msgs, keep_last=3)
        tools = [m for m in msgs if m["role"] == "tool"]
        self.assertTrue(all(m["content"].startswith("[output elided") for m in tools[:7]))
        self.assertTrue(all(m["content"] == "x" * 500 for m in tools[7:]))
        self.assertEqual([m["tool_call_id"] for m in tools], ["c%d" % i for i in range(10)])
        self.assertEqual(msgs[0]["content"], "s" * 1000)
        self.assertEqual(msgs[1]["content"], "u" * 1000)
        self.assertIn("from bash", tools[0]["content"])

    def test_idempotent(self):
        msgs = _conv(6)
        compact_messages(msgs, keep_last=2)
        snapshot = json.dumps(msgs)
        self.assertEqual(compact_messages(msgs, keep_last=2), 0)
        self.assertEqual(json.dumps(msgs), snapshot)

    def test_keep_zero(self):
        msgs = _conv(3)
        compact_messages(msgs, keep_last=0)
        self.assertTrue(all(m["content"].startswith("[output elided") for m in msgs if m["role"] == "tool"))

    def test_elide_write_file(self):
        msgs = [{"role": "system", "content": ""}, {"role": "user", "content": ""}]
        for i in range(6):
            args = json.dumps({"path": "/tmp/f%d" % i, "content": "y" * 2000})
            msgs.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": "w%d" % i, "type": "function", "function": {"name": "write_file", "arguments": args}}]})
            msgs.append({"role": "tool", "tool_call_id": "w%d" % i, "content": "ok"})
        saved = elide_write_file_arguments(msgs, keep_last_assistant=4)
        self.assertGreater(saved, 0)
        first = json.loads(msgs[2]["tool_calls"][0]["function"]["arguments"])
        last = json.loads(msgs[-2]["tool_calls"][0]["function"]["arguments"])
        self.assertTrue(first["content"].startswith("[content elided"))
        self.assertEqual(first["path"], "/tmp/f0")
        self.assertEqual(last["content"], "y" * 2000)


if __name__ == "__main__":
    unittest.main()
