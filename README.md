# Trajectory

A web page that drives Claude Code and shows its trajectory live: every assistant message,
tool call and tool result, nested by subagent, with per-call and per-run status and the
run's cost, duration and turn count.

## Run it

```bash
python3 app/server.py
```

Open <http://127.0.0.1:8765>. The server uses only the Python standard library and calls the
`claude` executable on your `PATH` (`claude -p … --output-format stream-json --verbose`).

Pick a working directory, type a prompt and press Enter. A follow-up prompt in the same
directory resumes the same session (`--resume <session_id>`). **New session** starts over.
Click **Replay a recorded demo run** to see a full run with two parallel subagents at no cost
(`app/fixtures/demo-subagent.jsonl`).

## What the page shows

| Feature | Where |
|---|---|
| Prompt, working directory, permission mode | Composer at the bottom |
| Live trajectory, markdown rendered | Main column, one section per turn |
| Tool results | Under each call. Up to 14 lines show whole; longer output shows the first 8 lines (errors show the last 12) with *Show all* / *Show last* controls |
| Status per call | Spinner while pending, check with duration on success, red card and *Error* on `is_error` |
| Status per run | Pill in each turn header: Running (live timer), Finished, Failed. Bad directory, a crash, a cancelled run or a stream that ends without a `result` event all fail visibly |
| Run numbers | Cost, duration, turns and tool-call count from the final `result` event |
| Subagents | Events with a `parent_tool_use_id` nest under their `Task`/`Agent` call, collapsible |
| Outline | Right column (drawer below 1100 px). Parallel subagents show as side-by-side lanes; click to jump |
| Timeline | Swimlane strip per turn: one lane per agent, one bar per tool call, width = time to result |

## Files

- `app/server.py` — HTTP server, spawns `claude`, streams its events over Server-Sent Events.
- `app/static/` — `index.html`, `app.css`, `app.js` (no build step).
- `app/fixtures/demo-subagent.jsonl` — recorded-style stream for the demo replay.
- `events.jsonl` — a real stream-json log used as a reference for event shapes.
