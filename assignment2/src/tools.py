"""Tool schemas and executors: bash, read_file, edit_file, write_file, done."""

import json
import os
import signal
import subprocess
from dataclasses import dataclass

from .config import API_KEY_ENV
from .context import truncate
from .conventions import export_style_issue


@dataclass
class ToolResult:
    content: str
    is_error: bool = False


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Run a bash command with the repository as the working directory. stdout and stderr are "
                "merged; the exit code is appended. Use it to search (grep -rn, find, ls), run scripts and "
                "tests. Long outputs are truncated, so filter them (grep, head, tail, -q flags). No network, "
                "no interactive programs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The bash command to run."},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 300, max 900). Compiling and running tests can be slow here."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a text file. Each line is prefixed with its line number and a tab; the prefix is NOT "
                "part of the file. At most 500 lines per call: use start_line/end_line for larger files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path, relative to the repository or absolute."},
                    "start_line": {"type": "integer", "description": "First line to show (1-based, inclusive)."},
                    "end_line": {"type": "integer", "description": "Last line to show (inclusive)."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace an exact string in an existing file. old_string must occur exactly once in the file "
                "(include surrounding lines to make it unique) and must match whitespace and indentation "
                "exactly, without read_file line-number prefixes. Returns the edited region."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path."},
                    "old_string": {"type": "string", "description": "Exact text to replace (must be unique)."},
                    "new_string": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create a file, or overwrite it completely, with the given content. Parent directories are "
                "created. Use it for new files and for scratch scripts under /tmp; prefer edit_file to change "
                "existing files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path."},
                    "content": {"type": "string", "description": "Full file content."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": (
                "Finish the task. Call it only after the fix is in place and verified. The summary lists the "
                "files changed and the test evidence, or explains why the task cannot be done."
            ),
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string", "description": "What changed and how it was verified."}},
                "required": ["summary"],
            },
        },
    },
]

TOOL_NAMES = {s["function"]["name"] for s in TOOL_SCHEMAS}
REQUIRED_ARGS = {s["function"]["name"]: s["function"]["parameters"]["required"] for s in TOOL_SCHEMAS}


def _numbered(lines, first_lineno):
    return "\n".join("%6d\t%s" % (first_lineno + i, line) for i, line in enumerate(lines))


def _clean_env():
    env = dict(os.environ)
    env.pop(API_KEY_ENV, None)
    pp = env.get("PYTHONPATH")
    if pp is not None:
        parts = [p for p in pp.split(os.pathsep) if p and p.rstrip("/") != "/tmp/agentdeps"]
        if parts:
            env["PYTHONPATH"] = os.pathsep.join(parts)
        else:
            env.pop("PYTHONPATH")
    return env


def _as_int(value, name):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("%s must be an integer" % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise ValueError("%s must be an integer, got %r" % (name, value))


class ToolExecutor:
    def __init__(self, workdir, cfg):
        self.workdir = os.path.realpath(workdir)
        self.cfg = cfg
        self._roots = [self.workdir, os.path.realpath("/tmp")]

    # --- path confinement --------------------------------------------------
    def resolve_path(self, path):
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        path = path.strip()
        full = path if os.path.isabs(path) else os.path.join(self.workdir, path)
        if not os.path.isabs(path) and not os.path.exists(full) and os.path.exists("/" + path):
            # The model sometimes drops the leading slash of an absolute path ("app/x.py").
            full = "/" + path
        real = os.path.realpath(full)
        for root in self._roots:
            if real == root or real.startswith(root.rstrip(os.sep) + os.sep):
                return real
        raise PermissionError("path %r is outside the allowed directories (%s and /tmp)" % (path, self.workdir))

    # --- tools -------------------------------------------------------------
    def bash(self, command, timeout=None):
        if not isinstance(command, str) or not command.strip():
            return ToolResult("Error: command must be a non-empty string", True)
        t = _as_int(timeout, "timeout")
        if t is None:
            t = self.cfg.bash_timeout_default
        t = max(1, min(t, self.cfg.bash_timeout_max))
        # No core dumps: a process killed by the timeout must not leave a binary `core` file in the repo,
        # where it would land in the patch and make `git apply` fail.
        proc = subprocess.Popen(
            ["bash", "-c", "ulimit -c 0 2>/dev/null\n" + command], cwd=self.workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True, env=_clean_env(),
        )
        try:
            out, _ = proc.communicate(timeout=t)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            try:
                out, _ = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                out = b""
            text = (out or b"").decode("utf-8", errors="replace")
            return ToolResult(
                text + "\n[timed out after %ds; the process group was killed. Use a narrower command, or "
                "raise the timeout (max %d).]" % (t, self.cfg.bash_timeout_max), True)
        text = (out or b"").decode("utf-8", errors="replace")
        return ToolResult(text + "\n[exit code %d]" % proc.returncode, False)

    def read_file(self, path, start_line=None, end_line=None):
        real = self.resolve_path(path)
        if os.path.isdir(real):
            return ToolResult("Error: %s is a directory; use bash `ls` to list it" % path, True)
        if not os.path.exists(real):
            return ToolResult("Error: file not found: %s" % path, True)
        with open(real, "rb") as fh:
            data = fh.read()
        if b"\x00" in data[:8192]:
            return ToolResult("Error: %s looks like a binary file" % path, True)
        lines = data.decode("utf-8", errors="replace").splitlines()
        total = len(lines)
        start = _as_int(start_line, "start_line") or 1
        start = max(1, start)
        end = _as_int(end_line, "end_line")
        end = total if end is None else min(end, total)
        if total == 0:
            return ToolResult("(empty file)", False)
        if start > total:
            return ToolResult("Error: start_line %d is past the end of the file (%d lines)" % (start, total), True)
        if end < start:
            return ToolResult("Error: end_line %d is before start_line %d" % (end, start), True)
        cap = self.cfg.read_file_max_lines
        shown_end = min(end, start + cap - 1)
        body = _numbered(lines[start - 1:shown_end], start)
        if shown_end < end:
            body += ("\n[showing lines %d-%d of %d; call read_file with start_line=%d to continue]"
                     % (start, shown_end, total, shown_end + 1))
        return ToolResult(body, False)

    def edit_file(self, path, old_string, new_string):
        real = self.resolve_path(path)
        if not isinstance(old_string, str) or not isinstance(new_string, str):
            return ToolResult("Error: old_string and new_string must be strings", True)
        if not os.path.exists(real):
            return ToolResult("Error: file not found: %s. Use write_file to create a new file." % path, True)
        if os.path.isdir(real):
            return ToolResult("Error: %s is a directory" % path, True)
        if old_string == "":
            return ToolResult("Error: old_string is empty; use write_file to create or overwrite a file", True)
        if old_string == new_string:
            return ToolResult("Error: old_string and new_string are identical; nothing to change", True)
        with open(real, "r", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            text = fh.read()
        count = text.count(old_string)
        if count == 0:
            return ToolResult(
                "Error: old_string not found in %s. Check whitespace and indentation, and do not include the "
                "line-number prefixes shown by read_file. Re-read the region and copy it exactly." % path, True)
        if count > 1:
            return ToolResult(
                "Error: old_string occurs %d times in %s. Add surrounding lines so it matches exactly once."
                % (count, path), True)
        pos = text.index(old_string)
        new_text = text[:pos] + new_string + text[pos + len(old_string):]
        with open(real, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.write(new_text)
        first = new_text.count("\n", 0, pos) + 1
        last = first + new_string.count("\n")
        lines = new_text.splitlines()
        lo = max(1, first - 4)
        hi = min(len(lines), last + 4)
        snippet = _numbered(lines[lo - 1:hi], lo)
        return ToolResult("Edited %s. Lines %d-%d now read:\n%s" % (path, lo, hi, snippet), False)

    def write_file(self, path, content):
        real = self.resolve_path(path)
        if not isinstance(content, str):
            return ToolResult("Error: content must be a string", True)
        if os.path.isdir(real):
            return ToolResult("Error: %s is a directory" % path, True)
        parent = os.path.dirname(real)
        if parent:
            self.resolve_path(parent)
            os.makedirs(parent, exist_ok=True)
        is_new = not os.path.exists(real)
        with open(real, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        text = "Wrote %d bytes to %s" % (len(content.encode("utf-8")), path)
        if is_new and real.startswith(self.workdir + os.sep):
            issue = export_style_issue(real, content, display=path)
            if issue:
                text += "\n" + issue
        return ToolResult(text, False)

    # --- dispatch ----------------------------------------------------------
    def dispatch(self, name, raw_arguments):
        """Parse arguments, run the tool and truncate its output. Never raises.

        Returns (arguments_for_log, ToolResult). The ToolResult content is final: it is both
        the tool message sent to the model and the logged result.
        """
        args, err = parse_arguments(raw_arguments)
        if err is not None:
            return args, ToolResult(err, True)
        if name not in TOOL_NAMES or name == "done":
            if name == "done":
                return args, ToolResult("Error: done is handled by the harness", True)
            return args, ToolResult("Error: unknown tool %r. Available tools: %s"
                                    % (name, ", ".join(sorted(TOOL_NAMES))), True)
        missing = [k for k in REQUIRED_ARGS[name] if k not in args]
        if missing:
            return args, ToolResult("Error: missing required argument(s) for %s: %s" % (name, ", ".join(missing)), True)
        allowed = set(TOOL_SCHEMAS_BY_NAME[name]["parameters"]["properties"])
        call_args = {k: v for k, v in args.items() if k in allowed}
        try:
            result = getattr(self, name)(**call_args)
        except Exception as exc:  # any tool failure becomes an error result
            result = ToolResult("Error: %s: %s" % (type(exc).__name__, exc), True)
        result.content = truncate(result.content, self.cfg.tool_output_limit)
        return args, result


TOOL_SCHEMAS_BY_NAME = {s["function"]["name"]: s["function"] for s in TOOL_SCHEMAS}


def parse_arguments(raw):
    """Return (dict, error_or_None). Bad JSON is kept under ``_raw_arguments`` for the log."""
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return {}, None
    if isinstance(raw, dict):
        return raw, None
    try:
        args = json.loads(raw)
    except (ValueError, TypeError) as exc:
        return {"_raw_arguments": raw}, ("Error: tool arguments are not valid JSON (%s). Send a JSON object "
                                         "matching the tool schema." % exc)
    if not isinstance(args, dict):
        return {"_raw_arguments": raw}, "Error: tool arguments must be a JSON object"
    return args, None
