# madsLoop

A minimal coding-agent harness for CS2680 Assignment 2. The model (`qwen3.6-35b-a3b` behind the course's
OpenAI-compatible proxy) runs in a tool-calling loop. The loop works on a SWE-bench Pro task inside its
Docker container.

```bash
python madsLoop.py -p "<problem statement>" [--log] <workdir>
```

## Layout

| Path | Role |
|---|---|
| `madsLoop.py` | CLI entry point. Writes nothing to stdout and always exits 0. |
| `src/config.py` | Constants and `MADSLOOP_*` environment overrides |
| `src/prompts.py` | System prompt, first user message, nudge texts |
| `src/tools.py` | Tool schemas and executors: `bash`, `read_file`, `edit_file`, `write_file`, `done` |
| `src/agentic_loop.py` | The loop, assistant-message rebuilding, the `done` gate, limits, compaction trigger |
| `src/api.py` | OpenAI client, retries with logged backoff |
| `src/context.py` | Output truncation and history compaction |
| `src/trace_log.py` | `madsLoop_logs/` JSONL trace with the exact handout schema |
| `docker_env.sh` | Installs `openai` in the task container |
| `evaluation_scripts/build_problem.py` | Builds the `-p` text for a task (used by `run_task.sh`) |
| `tests/` | Unit tests (`python3 -m unittest discover -s tests -t .`), log validator, real-API smoke test |

## Design notes and departures from the handout

- **Task text.** `run_task.sh` passes the problem statement *plus* the `requirements` and `interface`
  fields. Hidden tests import the names given there. Some entries store these fields as double-encoded
  JSON strings, so `build_problem.py` decodes them.
- **Tools.** `bash`, `read_file` (line-numbered, 500-line window), `edit_file` (exactly one match),
  `write_file`, `done`. There is no `repro_check` tool. The system prompt asks for reproduction scripts
  under `/tmp`, and a harness-side `done` gate checks the repository state instead.
- **`done` gate.** The harness rejects `done` when changes are stashed, staged or committed, because those
  changes would not be in the unstaged `git diff`. It also rejects `done` once when there are no changes
  at all. After the loop, the harness pops a leftover stash and unstages staged changes.
- **Path confinement.** File tools work only inside the workdir and `/tmp`. Symlinks are resolved first.
- **Bash tool.** Runs in its own process group; on timeout the whole group is killed. The API key and the
  harness's private `PYTHONPATH` entry are removed from the environment.
- **Loop robustness.** Assistant messages are rebuilt by hand (`reasoning_content` is never re-sent).
  Malformed tool arguments and unknown tools become error results, still paired with their call id.
  One nudge is given when the model answers without a tool call. Tool calls written as
  `<tool_call>` text are parsed as a fallback.
- **Limits.** 100 iterations and 45 minutes by default; a warning is injected near the end.
- **Context.** Tool outputs are truncated to 12 000 characters (head and tail kept). Above 90 000 prompt
  tokens, old tool results are elided; above 110 000, old `write_file` contents are elided too. A
  context-length 400 error triggers hard compaction and one retry.
- **API retries.** The client's own retries are off, so every retry is visible as an `api_retry` event.
- **`run_task.sh`.** Defaults to `--platform linux/amd64` on Apple Silicon, guards the harness call so the
  diff and logs are still collected after a crash, and passes `MADSLOOP_*` knobs into the container.

## Environment knobs

`MADSLOOP_MAX_ITERATIONS`, `MADSLOOP_MAX_SECONDS`, `MADSLOOP_COMPACT_TOKENS`,
`MADSLOOP_TOOL_OUTPUT_LIMIT`, `MADSLOOP_QUIET=1` (silence stderr progress).

`MADSLOOP_BASE_URL` and `MADSLOOP_MODEL` point the harness at another OpenAI-compatible endpoint.
The key is still read from `CS2680_API_KEY`. Example with OpenRouter, which serves the same model:

```bash
export CS2680_API_KEY="<openrouter key>"
export MADSLOOP_BASE_URL=https://openrouter.ai/api/v1
export MADSLOOP_MODEL=qwen/qwen3.6-35b-a3b
bash evaluation_scripts/run_task.sh 0
```
