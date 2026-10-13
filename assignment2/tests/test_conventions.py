import os
import tempfile
import unittest
from pathlib import Path

from src.conventions import export_style_issue, has_default_export, new_file_issues


class ConventionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name, "lib")
        self.lib.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        Path(self.lib, name).write_text(text)

    def test_has_default_export(self):
        self.assertTrue(has_default_export("export default class A {}"))
        self.assertTrue(has_default_export("const a = 1;\nexport default a;"))
        self.assertTrue(has_default_export("export { a as default, b };"))
        self.assertFalse(has_default_export("export function a() {}\nexport const defaultValue = 1;"))

    def test_flags_missing_default_when_siblings_use_it(self):
        self.write("A.ts", "export default class A {}")
        self.write("B.ts", "class B {}\nexport default B;")
        self.write("C.ts", "export const c = 1;")
        msg = export_style_issue(str(self.lib / "obs.ts"), "export function obs() {}", display="lib/obs.ts")
        self.assertIn("2 of 3 sibling modules", msg)
        self.assertIn("lib/obs.ts", msg)
        self.assertIn("export default", msg)

    def test_no_issue_cases(self):
        self.write("A.ts", "export default class A {}")
        self.write("B.ts", "export default class B {}")
        p = str(self.lib / "obs.ts")
        self.assertIsNone(export_style_issue(p, "export default function obs() {}"))
        self.assertIsNone(export_style_issue(str(self.lib / "obs.py"), "def obs(): pass"))
        self.assertIsNone(export_style_issue(str(self.lib / "obs.test.ts"), "test('x', () => {})"))
        self.assertIsNone(export_style_issue(str(self.lib / "index.ts"), "export * from './A'"))

    def test_minority_or_too_few_siblings(self):
        self.write("A.ts", "export default class A {}")
        p = str(self.lib / "obs.ts")
        self.assertIsNone(export_style_issue(p, "export const x = 1"))  # only one sibling
        self.write("B.ts", "export const b = 1;")
        self.assertIsNone(export_style_issue(p, "export const x = 1"))  # 1 of 2 is not a majority
        self.write("C.test.ts", "export default 1")  # tests and .d.ts are not siblings
        self.write("D.d.ts", "export default 1")
        self.assertIsNone(export_style_issue(p, "export const x = 1"))

    def test_new_file_issues(self):
        self.write("A.ts", "export default class A {}")
        self.write("B.ts", "export default class B {}")
        self.write("obs.ts", "export function obs() {}")
        issues = new_file_issues(self.tmp.name, ["lib/obs.ts", "lib/missing.ts"])
        self.assertEqual(len(issues), 1)
        self.assertIn("lib/obs.ts", issues[0])


if __name__ == "__main__":
    unittest.main()
