#!/bin/bash
# docker_env.sh — container setup, runs inside the task container before madsLoop.py.
# Non-fatal: run_task.sh separately makes sure the harness interpreter can import openai.
set -u
export PIP_BREAK_SYSTEM_PACKAGES=1 PIP_DISABLE_PIP_VERSION_CHECK=1
python3 -m pip install -q "openai>=1.40" 2>/dev/null || pip install -q "openai>=1.40" 2>/dev/null || true
exit 0
