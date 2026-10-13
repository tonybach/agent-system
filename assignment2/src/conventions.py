"""Harness-side convention checks for files the agent creates.

The model does not reliably follow "match the sibling files" from the system prompt, so the harness
measures the convention itself and reports a concrete fix in the tool result and at the done gate.

Currently one check: a new JavaScript/TypeScript module should have a default export when most of
its sibling modules do (hidden tests may `import thing from './thing'`).
"""

import os
import re

JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
DEFAULT_EXPORT_RE = re.compile(r"^\s*export\s+default\b|\bas\s+default\b", re.MULTILINE)
MAX_SIBLINGS = 30


def _is_module_file(name):
    lower = name.lower()
    if not lower.endswith(JS_EXTS) or lower.endswith(".d.ts"):
        return False
    stem = lower.split(".", 1)[0]
    if stem == "index":
        return False
    return not re.search(r"\.(test|spec|stories)\.", lower)


def has_default_export(text):
    return bool(DEFAULT_EXPORT_RE.search(text or ""))


def sibling_default_exports(path):
    """Return (sibling names with a default export, number of sibling modules checked)."""
    directory = os.path.dirname(path)
    own = os.path.basename(path)
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return [], 0
    with_default = []
    total = 0
    for name in names:
        if name == own or not _is_module_file(name):
            continue
        full = os.path.join(directory, name)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                text = fh.read(200000)
        except OSError:
            continue
        total += 1
        if has_default_export(text):
            with_default.append(name)
        if total >= MAX_SIBLINGS:
            break
    return with_default, total


def export_style_issue(path, text, display=None):
    """Return a message when a new JS/TS module lacks the default export its siblings use, else None.

    ``path`` is the real file path; ``display`` is how the message names it (defaults to ``path``).
    """
    if not _is_module_file(os.path.basename(path)) or has_default_export(text):
        return None
    with_default, total = sibling_default_exports(path)
    if total < 2 or len(with_default) * 2 <= total:
        return None
    shown = display or path
    examples = ", ".join(with_default[:3])
    return ("Convention check: %s has no default export, but %d of %d sibling modules in %s use "
            "`export default` (e.g. %s). Tests may import it as `import X from '.../%s'`. Add a default "
            "export of the main function or class and keep the named export, e.g. `export default "
            "<name>;` at the end of the file."
            % (shown, len(with_default), total, os.path.dirname(shown) or ".", examples,
               os.path.splitext(os.path.basename(path))[0]))


def new_file_issues(workdir, rel_paths):
    """Check the new files (paths relative to workdir) and return a list of messages."""
    issues = []
    for rel in rel_paths:
        full = os.path.join(workdir, rel)
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                text = fh.read(500000)
        except OSError:
            continue
        msg = export_style_issue(full, text, display=rel)
        if msg:
            issues.append(msg)
    return issues
