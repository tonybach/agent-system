"""JSONL run trace (madsLoop_logs/) with the exact schema from the handout, plus stderr progress."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_FIELDS = {
    "run_start": {"model_id", "workdir"},
    "api_request": {"iteration", "prompt_tokens", "completion_tokens", "total_tokens"},
    "api_retry": {"iteration", "error", "backoff_s"},
    "tool_call": {"iteration", "tool_name", "arguments"},
    "tool_result": {"iteration", "tool_name", "result", "is_error"},
    "run_end": {"reason", "num_iterations"},
}


def _now():
    return datetime.now(timezone.utc)


class RunLogger:
    """Writes one JSON object per line. The file is created lazily on the first event."""

    def __init__(self, enabled, log_dir=None, quiet=False):
        self.enabled = enabled
        self.log_dir = Path(log_dir) if log_dir is not None else Path.cwd() / "madsLoop_logs"
        self.quiet = quiet
        self.path = None
        self._fh = None

    def _open(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = _now().strftime("%Y%m%dT%H%M%SZ")
        path = self.log_dir / ("run_%s.jsonl" % stamp)
        n = 1
        while path.exists():
            n += 1
            path = self.log_dir / ("run_%s_%d.jsonl" % (stamp, n))
        self.path = path
        self._fh = open(path, "a", encoding="utf-8")

    def _emit(self, event, **fields):
        required = REQUIRED_FIELDS.get(event)
        if required is None:
            raise ValueError("unknown event %r" % event)
        if set(fields) != required:
            raise ValueError("event %r needs fields %s, got %s" % (event, sorted(required), sorted(fields)))
        if not self.enabled:
            return
        if self._fh is None:
            self._open()
        record = {"timestamp": _now().isoformat(timespec="seconds"), "event": event}
        record.update(fields)
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()

    # --- events -----------------------------------------------------------
    def run_start(self, model_id, workdir):
        self._emit("run_start", model_id=model_id, workdir=workdir)
        self.progress("run start: model=%s workdir=%s" % (model_id, workdir))

    def api_request(self, iteration, prompt_tokens, completion_tokens, total_tokens):
        self._emit("api_request", iteration=iteration, prompt_tokens=prompt_tokens,
                   completion_tokens=completion_tokens, total_tokens=total_tokens)
        self.progress("[iter %d] tokens prompt=%s completion=%s" % (iteration, prompt_tokens, completion_tokens))

    def api_retry(self, iteration, error, backoff_s):
        self._emit("api_retry", iteration=iteration, error=error, backoff_s=backoff_s)
        self.progress("[iter %d] api retry in %.1fs: %s" % (iteration, backoff_s, error))

    def tool_call(self, iteration, tool_name, arguments):
        self._emit("tool_call", iteration=iteration, tool_name=tool_name, arguments=arguments)
        preview = json.dumps(arguments, ensure_ascii=False)
        if len(preview) > 160:
            preview = preview[:157] + "..."
        self.progress("[iter %d] %s: %s" % (iteration, tool_name, preview))

    def tool_result(self, iteration, tool_name, result, is_error):
        self._emit("tool_result", iteration=iteration, tool_name=tool_name, result=result, is_error=is_error)
        if is_error:
            first = result.splitlines()[0] if result else ""
            self.progress("[iter %d] %s error: %s" % (iteration, tool_name, first[:200]))

    def run_end(self, reason, num_iterations):
        self._emit("run_end", reason=reason, num_iterations=num_iterations)
        self.progress("run end: reason=%s iterations=%d" % (reason, num_iterations))

    # --- misc -------------------------------------------------------------
    def progress(self, text):
        if self.quiet:
            return
        try:
            sys.stderr.write(text + "\n")
            sys.stderr.flush()
        except Exception:
            pass

    def close(self):
        if self._fh is not None:
            try:
                self._fh.close()
            finally:
                self._fh = None


def warn(text):
    """Unconditional stderr message (never stdout: stdout carries the patch)."""
    try:
        sys.stderr.write(text + ("" if text.endswith("\n") else "\n"))
        sys.stderr.flush()
    except Exception:
        pass


__all__ = ["REQUIRED_FIELDS", "RunLogger", "warn"]
