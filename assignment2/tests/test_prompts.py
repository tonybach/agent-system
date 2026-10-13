import tempfile
import unittest

from src.prompts import build_system_prompt, build_user_message


class PromptTest(unittest.TestCase):
    def test_system_prompt(self):
        p = build_system_prompt("/app")
        self.assertIn("/app", p)
        for key in ("Requirements", "Interface", "/tmp", "git commit", "done", "line"):
            self.assertIn(key, p)
        self.assertNotIn("{", p.replace("{workdir}", ""))

    def test_user_message(self):
        with tempfile.TemporaryDirectory() as d:
            open(d + "/setup.py", "w").close()
            msg = build_user_message("  Fix the bug.  ", d)
        self.assertIn("setup.py", msg)
        self.assertTrue(msg.endswith("Fix the bug."))


if __name__ == "__main__":
    unittest.main()
