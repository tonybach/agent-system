# Results on the 10 provided tasks

Model: `qwen3.6-35b-a3b` through OpenRouter (`MADSLOOP_BASE_URL=https://openrouter.ai/api/v1`,
`MADSLOOP_MODEL=qwen/qwen3.6-35b-a3b`). Host: Apple M4 Pro, Colima with Rosetta, `DOCKER_PLATFORM=linux/amd64`.
Scored with the unmodified `evaluation_scripts/evaluate.sh` (official SWE-bench Pro evaluation).

| Folder | What it holds |
|---|---|
| `run1/` | First pass over all 10 tasks with the PR #8 harness: patches, agent logs, `eval_results.json` (5/10) |
| `final/` | Patches and the agent log per task with the final harness, `eval_results.json` (**7/10**) |
| `task9_before/` | Agent logs of the three task 9 runs that failed (named-only export) before the convention check |
| `task9_repeats/` | Three more task 9 runs with the final harness: patch, agent log and `eval_results.json` each (3/3 resolved) |

## Per-task outcome

| # | Task | Lang | run1 | final | Steps (final) | Cause when unresolved |
|---|---|---|---|---|---|---|
| 0 | ansible `f327e65` collection-name keywords | Python | ✅ | ✅ | 60 | Patch from the first run, which hit the old 60-step limit before calling `done` |
| 1 | qutebrowser `c580ebf` | Python | ✅ | ✅ | 49 | |
| 2 | ansible `a26c325` `use_netrc` | Python | ❌ | ✅ | 52 | run1: `Request.open(use_netrc=True)` broke the `None`-fallback pattern of its sibling parameters |
| 3 | flipt `2eac0df` telemetry | Go | ✅ | ✅ | 44 | |
| 4 | qutebrowser `de4a1c1` | Python | ✅ | ✅ | 52 | |
| 5 | openlibrary `4a5d2a7` wikidata | Python | ✅ | ✅ | 11 | |
| 6 | teleport `89f0432` `ReadAtMost` | Go | ❌ | ❌ | 18 | Test contradicts the requirements (see below) |
| 7 | qutebrowser `21b426b` `Values._vmap` | Python | ❌ | ❌ | 49 | Test pins an unspecified `__repr__` format |
| 8 | ansible `83909bf` galaxy login removal | Python | ❌ | ❌ | 53 | Test pins an unspecified error message |
| 9 | protonmail `944adbf` `observeApiError` | TS | ❌ | ✅ | 20 | run1–3: named-only export; the test imports a default export. Fixed by the convention check |

## Evidence for the unresolved tasks (6, 7, 8)

**6 — teleport, `ReadAtMost`.** The requirements say: "When the limit allows reading all available content,
`ReadAtMost` must return all bytes without error." The hidden test `TestReadAtMost` reads `"hello"` with limit 5
and expects `ErrLimitReached`. The agent implemented the requirement as written (peeks one byte past the limit
and returns `nil` when the content fits exactly), so the test fails on `utils_test.go:565`. A patch that passes
must violate the stated requirement.

**8 — ansible, galaxy login.** `test_api_no_auth_but_required` matches the exact text
`"No access token or username set. A token can be set with --api-key or at "`. The task never gives this
string, and its requirement points elsewhere: "update the error message in the Galaxy API to indicate the new
authentication options via token file or --token parameter". The agent wrote "...with --token, with a token
file, or set in ansible.cfg.", which follows the requirement and fails the regex.

**7 — qutebrowser, `Values._vmap`.** The requirements fix the attribute (`_vmap`, an `OrderedDict`) and say
`__repr__` "should be updated to use the new internal `_vmap` structure". The test compares the full repr string
and expects `vmap=odict_values([...])`; the agent produced `values=[...]` (it kept the existing keyword name and
passed `list(self._vmap.values())`). The keyword name and the `odict_values` wrapper are not specified anywhere.
Borderline: renaming the keyword along with the attribute is a plausible guess, but nothing in the task pins it.

## Task 9: from 0/3 to 4/4

All six files in `packages/metrics/lib/` use `export default`, and so does the golden patch. The hidden test does
`import observeApiError from '../lib/observeApiError'`, so a named-only export fails to compile
(`TS2613: Module has no default export`). In runs 1–3 the agent read two of those sibling files and still wrote a
named-only export, run 3 even after the system prompt told it to export both ways. A rule in the system prompt
is read once; the 35B model does not reliably apply it at the moment it writes the file.

The fix moves the check into the harness (`src/conventions.py`). When the agent creates a new JS/TS module (not a
test, `index`, or `.d.ts` file) without a default export, and a majority of at least two sibling modules have one,
the harness says so in the `write_file` result, naming the siblings and the fix ("add a default export and keep the
named export"). The `done` gate runs the same check on every new file in the diff (also catching files created
with `bash`) and rejects `done` once with the same message. On run 3's failing patch the check reports
"6 of 6 sibling modules in lib use `export default`".

| Task 9 run | Harness | Check fired | Default export | Official eval |
|---|---|---|---|---|
| run 1, 2, 3 | before | — | no | ❌ |
| run 4 (`final/`) | final | no (the model wrote it unprompted) | yes | ✅ |
| repeat 1 | final | yes, `write_file` result at step 5 | yes | ✅ |
| repeat 2 | final | no | yes | ✅ |
| repeat 3 | final | yes, `write_file` result at step 4 | yes | ✅ |

## Harness changes driven by these runs

- **Convention check in the harness** (`src/conventions.py`, wired into `write_file` and the `done` gate): see
  above. Only new JS/TS modules are checked, so Python and Go tasks are unaffected, and the requested fix only
  adds an export.

- **Conventions rule in the system prompt** (`src/prompts.py`, step 3 of the workflow): copy the pattern of
  sibling parameters (defaults, fallback handling), read sibling files before creating one and match their export
  style (export both default and named when unsure), and update every method that uses a changed data structure.
  This fixed task 2 (`Request.open` now uses `use_netrc=None` like its siblings). On its own it did not fix task 9.
- Earlier, in PR #8: no core dumps from the bash tool and removal of new ELF `core` files (task 3's first run
  left a binary `core` file in the patch); 300 s / 900 s bash timeouts for slow Go builds; 100-step limit
  (task 0 ran out of 60 steps while cleaning up).
