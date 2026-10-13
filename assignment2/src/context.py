"""Context growth control: output truncation and history compaction."""

import json

ELIDED_PREFIX = "[output elided to save context"
WRITE_ELIDED_PREFIX = "[content elided to save context"


def truncate(text, limit):
    """Keep the head (60%) and tail (40%) of text so the result is at most ``limit`` chars."""
    if text is None:
        return ""
    if limit <= 0 or len(text) <= limit:
        return text
    # Reserve room for the marker so the final string stays within the limit.
    marker_room = 48
    budget = max(limit - marker_room, 0)
    head_len = int(budget * 0.6)
    tail_len = budget - head_len
    dropped = len(text) - head_len - tail_len
    marker = "\n[... truncated %d chars ...]\n" % dropped
    tail = text[len(text) - tail_len:] if tail_len > 0 else ""
    return text[:head_len] + marker + tail


def _tool_names_by_id(messages):
    names = {}
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                names[tc.get("id")] = tc.get("function", {}).get("name", "tool")
    return names


def compact_messages(messages, keep_last):
    """Replace the content of old tool results with a short placeholder.

    The system prompt and the first user message are never touched, nor are the
    last ``keep_last`` tool messages. ``tool_call_id`` pairing is preserved.
    Idempotent. Returns the number of characters removed.
    """
    tool_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    if keep_last > 0:
        old = tool_idx[:-keep_last] if len(tool_idx) > keep_last else []
    else:
        old = tool_idx
    names = _tool_names_by_id(messages)
    saved = 0
    for i in old:
        msg = messages[i]
        content = msg.get("content") or ""
        if content.startswith(ELIDED_PREFIX):
            continue
        name = names.get(msg.get("tool_call_id"), "tool")
        placeholder = "%s: %d chars from %s; re-run if needed]" % (ELIDED_PREFIX, len(content), name)
        if len(placeholder) >= len(content):
            continue
        saved += len(content) - len(placeholder)
        msg["content"] = placeholder
    return saved


def elide_write_file_arguments(messages, keep_last_assistant=4):
    """Drop the ``content`` of write_file calls in older assistant turns."""
    asst_idx = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    old = asst_idx[:-keep_last_assistant] if len(asst_idx) > keep_last_assistant else []
    saved = 0
    for i in old:
        for tc in messages[i].get("tool_calls") or []:
            fn = tc.get("function", {})
            if fn.get("name") != "write_file":
                continue
            raw = fn.get("arguments") or ""
            try:
                args = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(args, dict):
                continue
            content = args.get("content")
            if not isinstance(content, str) or content.startswith(WRITE_ELIDED_PREFIX):
                continue
            args["content"] = "%s: %d chars]" % (WRITE_ELIDED_PREFIX, len(content))
            new_raw = json.dumps(args, ensure_ascii=False)
            if len(new_raw) < len(raw):
                saved += len(raw) - len(new_raw)
                fn["arguments"] = new_raw
    return saved
