import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "check_secrets", Path(__file__).resolve().parent.parent / "scripts" / "check_secrets.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)

FAKE_OR = "sk-or-v1-" + "0123456789abcdef" * 4
FAKE_PROJ = "sk-proj-" + "AbCdEfGhIjKlMnOpQrStUv_-12"
FAKE_HYI = "hyi-" + "abcdef0123456789"


class CheckSecretsTest(unittest.TestCase):
    def test_finds_keys(self):
        for key in (FAKE_OR, FAKE_PROJ, FAKE_HYI):
            self.assertEqual(cs.find_secrets('export CS2680_API_KEY="%s"' % key), [key])

    def test_ignores_mentions(self):
        for text in ("keys start with sk- or hyi-", 'grep -E "sk-proj-|hyi-"', "risk-free task-list",
                     r"re.compile(r'sk-[A-Za-z0-9]{20,}')", "export CS2680_API_KEY=\"hyi-...\""):
            self.assertEqual(cs.find_secrets(text), [], text)

    def test_env_value(self):
        self.assertEqual(cs.find_secrets("token=weird-format-secret-123", ["weird-format-secret-123"]),
                         ["weird-format-secret-123"])

    def test_redact(self):
        text = "a %s b %s c" % (FAKE_OR, FAKE_HYI)
        self.assertEqual(cs.redact(text), "a [REDACTED_KEY] b [REDACTED_KEY] c")

    def test_scan_and_redact_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.jsonl")
            Path(p).write_text('{"k": "%s"}\n{"ok": 1}\n' % FAKE_OR)
            self.assertEqual(cs.main([p]), 1)
            cs.main(["--redact", p])
            self.assertEqual(cs.main([p]), 0)
            self.assertIn("[REDACTED_KEY]", Path(p).read_text())


if __name__ == "__main__":
    unittest.main()
