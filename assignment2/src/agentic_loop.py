"""The agentic loop: model proposes tool calls, the harness executes them and feeds results back."""

import json
import os
import re
import subprocess
import time
import traceback

from . import prompts
from .api import ContextOverflowError, chat_with_retries
from .context import compact_messages, elide_write_file_arguments
from .conventions import new_file_issues
from .tools import TOOL_SCHEMAS, ToolExecutor, ToolResult, parse_arguments
from .trace_log import warn

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
TEXT_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


# --- git helpers -----------------------------------------------------------
def _git(workdir, *args):
    """Run git in workdir. Returns (returncode, stdout) or None when git cannot run."""
    try:
        proc = subprocess.run(["git", "-C", workdir] + list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=60)
    except Exception:
        return None
    return proc.returncode, proc.stdout.decode("utf-8", errors="replace")


def _git_out(workdir, *args):
    res = _git(workdir, *args)
    if res is None or res[0] != 0:
        return None
    return res[1].strip()


def done_gate(workdir, start_head, rejections, untracked_before=None):
    """Decide whether to accept a done call. Returns (accepted, message_for_model).

    ``rejections`` is a mutable dict counting one-time rejections already given.
    Git failures never block finishing.
    """
    stash = _git_out(workdir, "stash", "list")
    if stash:
        return False, ("Not finished: `git stash list` is not empty, so some of your changes are hidden in the "
                       "stash and would be lost. Run `git stash pop`, check `git diff`, then call done again.")
    head = _git_out(workdir, "rev-parse", "HEAD")
    if start_head and head and head != start_head:
        return False, ("Not finished: HEAD moved from %s to %s (a commit, reset or checkout happened). The harness "
                       "collects only unstaged changes against the original commit. Run `git reset --soft %s && "
                       "git reset -q` to turn your commits back into unstaged changes, then call done again."
                       % (start_head[:12], head[:12], start_head[:12]))
    staged = _git_out(workdir, "diff", "--cached", "--name-only")
    if staged:
        return False, ("Not finished: some changes are staged (%s). Staged changes are not collected. Run "
                       "`git reset -q` to unstage them (your edits stay in the files), then call done again."
                       % ", ".join(staged.splitlines()[:5]))
    if untracked_before is not None and rejections.get("conventions", 0) < 1:
        issues = new_file_issues(workdir, sorted(_untracked(workdir) - untracked_before))
        if issues:
            rejections["conventions"] = rejections.get("conventions", 0) + 1
            return False, ("Not finished: fix these convention problems in the files you created, re-run "
                           "your checks, then call done again.\n- " + "\n- ".join(issues))
    status = _git_out(workdir, "status", "--porcelain")
    if status == "" and rejections.get("empty", 0) < 1:
        rejections["empty"] = rejections.get("empty", 0) + 1
        return False, ("Not finished: the repository has no changes, so nothing would be submitted. Continue "
                       "working on the fix. If the task truly cannot be done, call done again and explain why.")
    return True, "Accepted. The run is finished."


# --- message helpers -------------------------------------------------------
def _clean_content(content):
    if not content:
        return ""
    return THINK_RE.sub("", content).strip()


def _extract_text_tool_calls(content):
    """Fallback: some servers leave Qwen tool calls as <tool_call>{...}</tool_call> text."""
    calls = []
    for m in TEXT_TOOL_CALL_RE.finditer(content or ""):
        try:
            obj = json.loads(m.group(1))
        except ValueError:
            continue
        if not isinstance(obj, dict) or not isinstance(obj.get("name"), str):
            continue
        args = obj.get("arguments", {})
        raw = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
        calls.append((obj["name"], raw))
    return calls


def build_assistant_message(msg, iteration):
    """Hand-build the assistant dict that is sent back. Drops reasoning_content and None fields."""
    content = _clean_content(getattr(msg, "content", None))
    tool_calls = []
    for idx, tc in enumerate(getattr(msg, "tool_calls", None) or []):
        fn = getattr(tc, "function", None)
        name = getattr(fn, "name", None) or ""
        raw = getattr(fn, "arguments", None)
        if raw is None:
            raw = "{}"
        elif not isinstance(raw, str):
            raw = json.dumps(raw, ensure_ascii=False)
        call_id = getattr(tc, "id", None) or "call_%d_%d" % (iteration, idx)
        tool_calls.append({"id": call_id, "type": "function", "function": {"name": name, "arguments": raw}})
    if not tool_calls and content:
        parsed = _extract_text_tool_calls(content)
        if parsed:
            for idx, (name, raw) in enumerate(parsed):
                tool_calls.append({"id": "call_%d_%d" % (iteration, idx), "type": "function",
                                   "function": {"name": name, "arguments": raw}})
            content = TEXT_TOOL_CALL_RE.sub("", content).strip()
    asst = {"role": "assistant", "content": content}
    if tool_calls:
        asst["tool_calls"] = tool_calls
    return asst


# --- the loop --------------------------------------------------------------
def run(problem, workdir, cfg, logger, client, clock=time.monotonic, sleep=time.sleep):
    """Run the agent. Returns the run_end reason. Never raises for ordinary failures."""
    start = clock()
    iteration = 0
    reason = "error"
    executor = ToolExecutor(workdir, cfg)
    start_head = _git_out(workdir, "rev-parse", "HEAD")
    untracked_before = _untracked(workdir)
    messages = [
        {"role": "system", "content": prompts.build_system_prompt(workdir)},
        {"role": "user", "content": prompts.build_user_message(problem, workdir)},
    ]
    nudges = 0
    rejections = {}
    warned = False
    logger.run_start(cfg.model_id, workdir)
    try:
        while True:
            elapsed = clock() - start
            if iteration >= cfg.max_iterations:
                reason = "max_iterations"
                break
            if elapsed >= cfg.max_wall_seconds:
                reason = "timeout"
                break
            steps_left = cfg.max_iterations - iteration
            seconds_left = int(cfg.max_wall_seconds - elapsed)
            if not warned and (steps_left <= cfg.warn_steps_left or seconds_left <= cfg.warn_seconds_left):
                warned = True
                messages.append({"role": "user", "content": prompts.steps_left_warning(steps_left, seconds_left)})

            iteration += 1
            try:
                resp = chat_with_retries(client, cfg, logger, iteration, messages, TOOL_SCHEMAS, sleep=sleep)
            except ContextOverflowError as exc:
                logger.progress("[iter %d] context overflow (%s); compacting hard and retrying" % (iteration, exc))
                compact_messages(messages, keep_last=4)
                elide_write_file_arguments(messages, keep_last_assistant=2)
                resp = chat_with_retries(client, cfg, logger, iteration, messages, TOOL_SCHEMAS, sleep=sleep)

            choice = resp.choices[0]
            asst = build_assistant_message(choice.message, iteration)
            messages.append(asst)
            tool_calls = asst.get("tool_calls") or []

            if not tool_calls:
                if nudges < cfg.max_nudges:
                    nudges += 1
                    text = prompts.NUDGE_LENGTH if choice.finish_reason == "length" else prompts.NUDGE_NO_TOOLS
                    messages.append({"role": "user", "content": text})
                    continue
                reason = "no_tool_calls"
                break

            finished = False
            results = {}
            ordered = [tc for tc in tool_calls if tc["function"]["name"] != "done"]
            ordered += [tc for tc in tool_calls if tc["function"]["name"] == "done"]
            for tc in ordered:
                name = tc["function"]["name"]
                if name == "done":
                    args, err = parse_arguments(tc["function"]["arguments"])
                    logger.tool_call(iteration, name, args)
                    if err is not None:
                        result = ToolResult(err, True)
                    elif finished:
                        result = ToolResult("Accepted. The run is finished.", False)
                    else:
                        accepted, text = done_gate(workdir, start_head, rejections, untracked_before)
                        result = ToolResult(text, not accepted)
                        finished = accepted
                else:
                    logger.tool_call(iteration, name, parse_arguments(tc["function"]["arguments"])[0])
                    result = executor.dispatch(name, tc["function"]["arguments"])[1]
                logger.tool_result(iteration, name, result.content, result.is_error)
                results[tc["id"]] = result
            for tc in tool_calls:
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": results[tc["id"]].content})

            if finished:
                reason = "done"
                break

            prompt_tokens = getattr(getattr(resp, "usage", None), "prompt_tokens", 0) or 0
            if prompt_tokens >= cfg.compact_prompt_tokens:
                saved = compact_messages(messages, keep_last=cfg.compact_keep_tool_msgs)
                if prompt_tokens >= cfg.compact_stage2_tokens:
                    saved += elide_write_file_arguments(messages)
                    saved += compact_messages(messages, keep_last=max(4, cfg.compact_keep_tool_msgs // 2))
                logger.progress("[iter %d] compacted history at %d prompt tokens (%d chars removed)"
                                % (iteration, prompt_tokens, saved))
    except Exception as exc:
        reason = "error"
        warn("madsLoop error: %s: %s" % (type(exc).__name__, exc))
        warn(traceback.format_exc())
    finally:
        _restore_safety(workdir, logger, untracked_before)
        logger.run_end(reason, iteration)
    return reason


CORE_DUMP_RE = re.compile(r"^core(\.\d+)?$")


def _untracked(workdir):
    out = _git_out(workdir, "ls-files", "--others", "--exclude-standard")
    return set(out.splitlines()) if out else set()


def _remove_core_dumps(workdir, before, logger):
    """Delete ELF core dumps that appeared during the run (they would break `git apply`)."""
    for rel in sorted(_untracked(workdir) - before):
        if not CORE_DUMP_RE.match(os.path.basename(rel)):
            continue
        path = os.path.join(workdir, rel)
        try:
            with open(path, "rb") as fh:
                if fh.read(4) != b"\x7fELF":
                    continue
            os.remove(path)
            logger.progress("cleanup: removed core dump %s" % rel)
        except OSError:
            pass


def _restore_safety(workdir, logger, untracked_before=None):
    """Non-destructive cleanup so the final unstaged diff contains the agent's work."""
    try:
        if untracked_before is not None:
            _remove_core_dumps(workdir, untracked_before, logger)
        if _git_out(workdir, "stash", "list"):
            logger.progress("cleanup: popping leftover git stash")
            _git(workdir, "stash", "pop")
        if _git_out(workdir, "diff", "--cached", "--name-only"):
            logger.progress("cleanup: unstaging staged changes")
            _git(workdir, "reset", "-q")
    except Exception:
        pass
