#!/usr/bin/env python3
"""Print the text madsLoop receives as -p for one task.

    python3 build_problem.py <tasks.json> <index>

The text is the problem statement followed by the requirements and interface
sections (hidden tests use the names given there). Some task entries store
these fields as double-encoded JSON strings; those are decoded. Empty sections
are skipped, so mytest/ entries with "" requirements/interface work unchanged.
"""

import json
import sys


def field(task, name):
    value = task.get(name) or ""
    if isinstance(value, str) and value.startswith('"'):
        try:
            decoded = json.loads(value)
        except ValueError:
            decoded = None
        if isinstance(decoded, str):
            value = decoded
    if not isinstance(value, str):
        value = json.dumps(value, indent=2)
    return value.strip()


def build(task):
    parts = []
    for title, key in (("Problem statement", "problem_statement"), ("Requirements", "requirements"),
                       ("Interface", "interface")):
        text = field(task, key)
        if text:
            parts.append("# %s\n\n%s" % (title, text))
    return "\n\n".join(parts) + "\n"


if __name__ == "__main__":
    tasks = json.load(open(sys.argv[1]))
    task = list(tasks.values())[int(sys.argv[2])]
    sys.stdout.write(build(task))
