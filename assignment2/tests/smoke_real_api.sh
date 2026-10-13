#!/bin/bash
# Manual smoke test against the real API on the host (not in a container).
#   export CS2680_API_KEY=...; bash tests/smoke_real_api.sh
# Needs a Python with openai: python3 -m venv .venv && .venv/bin/pip install "openai>=1.40"
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PY:-$HERE/.venv/bin/python}"
WORK="$(mktemp -d)"
REPO="$WORK/repo"
mkdir -p "$REPO"
cat > "$REPO/calc.py" <<'PYEOF'
def add(a, b):
    return a - b


def mul(a, b):
    return a * b
PYEOF
cat > "$REPO/test_calc.py" <<'PYEOF'
import unittest
from calc import mul


class T(unittest.TestCase):
    def test_mul(self):
        self.assertEqual(mul(2, 3), 6)
PYEOF
git -C "$REPO" init -q
git -C "$REPO" add .
git -C "$REPO" -c user.email=s@s -c user.name=s commit -qm init
cd "$WORK"
MADSLOOP_MAX_ITERATIONS="${MADSLOOP_MAX_ITERATIONS:-15}" "$PY" "$HERE/madsLoop.py" \
  -p "add(2, 3) returns -1 instead of 5. Fix calc.add so it returns the sum of its arguments." \
  --log "$REPO" > "$WORK/stdout.txt"
echo "== stdout bytes: $(wc -c < "$WORK/stdout.txt")"
echo "== diff:"; git -C "$REPO" diff
echo "== stash: $(git -C "$REPO" stash list | wc -l)"
"$PY" "$HERE/tests/validate_log.py" "$WORK"/madsLoop_logs/*.jsonl
tail -1 "$WORK"/madsLoop_logs/*.jsonl
echo "== work dir: $WORK"
