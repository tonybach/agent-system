#!/usr/bin/env python3
"""Validate madsLoop JSONL trace logs against the handout schema.

    python3 tests/validate_log.py [madsLoop_logs/**/*.jsonl ...]

Exits 1 and prints problems to stderr if any file is invalid.
"""

import glob
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.trace_log import REQUIRED_FIELDS  # noqa: E402


def validate(path):
    problems = []
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    if not lines:
        return ["empty file"]
    events = []
    for n, line in enumerate(lines, 1):
        try:
            rec = json.loads(line)
        except ValueError as exc:
            problems.append("line %d: not JSON (%s)" % (n, exc))
            continue
        ev = rec.get("event")
        if ev not in REQUIRED_FIELDS:
            problems.append("line %d: unknown event %r" % (n, ev))
            continue
        expected = REQUIRED_FIELDS[ev] | {"timestamp", "event"}
        if set(rec) != expected:
            problems.append("line %d (%s): fields %s != %s" % (n, ev, sorted(rec), sorted(expected)))
        try:
            if datetime.fromisoformat(rec["timestamp"]).utcoffset() is None:
                problems.append("line %d: timestamp has no UTC offset" % n)
        except (KeyError, ValueError, TypeError):
            problems.append("line %d: bad timestamp" % n)
        if ev == "tool_result" and not isinstance(rec.get("is_error"), bool):
            problems.append("line %d: is_error is not a bool" % n)
        if ev == "tool_call" and not isinstance(rec.get("arguments"), dict):
            problems.append("line %d: arguments is not an object" % n)
        events.append(ev)
    if events and events[0] != "run_start":
        problems.append("first event is %s, not run_start" % events[0])
    if events and events[-1] != "run_end":
        problems.append("last event is %s, not run_end" % events[-1])
    if events.count("tool_call") != events.count("tool_result"):
        problems.append("tool_call/tool_result counts differ")
    return problems


def main(paths):
    if not paths:
        paths = glob.glob("madsLoop_logs/**/*.jsonl", recursive=True)
    if not paths:
        sys.stderr.write("no log files found\n")
        return 1
    bad = 0
    for p in paths:
        problems = validate(p)
        if problems:
            bad += 1
            sys.stderr.write("%s: INVALID\n  %s\n" % (p, "\n  ".join(problems[:20])))
        else:
            print("%s: ok" % p)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
