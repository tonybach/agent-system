#!/usr/bin/env python3
"""Find API keys before they are committed, and redact them from developer logs.

    python3 scripts/check_secrets.py                 # scan files staged in git (pre-commit)
    python3 scripts/check_secrets.py PATH ...        # scan the given files
    python3 scripts/check_secrets.py --redact PATH   # rewrite PATH with keys replaced

A key is anything that looks like an OpenAI/OpenRouter key (sk-...), a course key (hyi-...),
or the exact value of an environment variable that holds a key (CS2680_API_KEY, OPENAI_API_KEY,
OPENROUTER_API_KEY). Matches are reported by file and line only; key values are never printed.
Exits 1 when a scan finds a key.
"""

import os
import re
import subprocess
import sys

PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9][A-Za-z0-9_\-]{19,}"),
    re.compile(r"hyi-[A-Za-z0-9][A-Za-z0-9_\-]{11,}"),
]
KEY_ENV_VARS = ("CS2680_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY")
REDACTED = "[REDACTED_KEY]"


def env_secrets():
    values = []
    for name in KEY_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if len(value) >= 12:
            values.append(value)
    return values


def find_secrets(text, extra=()):
    """Return the list of key-like strings in text."""
    found = []
    for value in extra:
        if value in text:
            found.append(value)
    for pat in PATTERNS:
        found.extend(pat.findall(text))
    return found


def redact(text, extra=()):
    for value in extra:
        text = text.replace(value, REDACTED)
    for pat in PATTERNS:
        text = pat.sub(REDACTED, text)
    return text


def staged_files():
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
                         stdout=subprocess.PIPE, check=True).stdout.decode()
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE,
                         check=True).stdout.decode().strip()
    return [os.path.join(top, p) for p in out.split("\0") if p]


def staged_text(path):
    """The staged blob, which is what would be committed (not the working copy)."""
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE,
                         check=True).stdout.decode().strip()
    rel = os.path.relpath(path, top)
    proc = subprocess.run(["git", "show", ":" + rel], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return proc.stdout.decode("utf-8", errors="replace") if proc.returncode == 0 else ""


def read_text(path):
    try:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def scan(paths, reader):
    extra = env_secrets()
    bad = 0
    for path in paths:
        text = reader(path)
        if not text:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            hits = find_secrets(line, extra)
            if hits:
                bad += 1
                sys.stderr.write("%s:%d: possible API key (%d match%s)\n"
                                 % (path, n, len(hits), "" if len(hits) == 1 else "es"))
    return bad


def main(argv):
    if argv and argv[0] == "--redact":
        extra = env_secrets()
        for path in argv[1:]:
            text = read_text(path)
            new = redact(text, extra)
            if new != text:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new)
                sys.stderr.write("redacted keys in %s\n" % path)
        return 0
    if argv:
        bad = scan(argv, read_text)
    else:
        bad = scan(staged_files(), staged_text)
    if bad:
        sys.stderr.write("check_secrets: %d line(s) contain possible API keys; commit blocked. "
                         "Use --redact on developer logs, or remove the key.\n" % bad)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
