#!/usr/bin/env python3
"""madsLoop: a minimal coding-agent harness.

    python madsLoop.py -p "<problem statement>" [--log] <workdir>

Nothing is ever printed to stdout (run_task.sh captures stdout as the patch),
and the process always exits 0 so the patch and logs are still collected.
"""

import argparse
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import API_KEY_ENV, Config  # noqa: E402
from src.trace_log import RunLogger, warn  # noqa: E402


class _ArgParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def parse_args(argv):
    parser = _ArgParser(prog="madsLoop.py", description="Minimal coding-agent harness.")
    parser.add_argument("-p", "--problem", required=True, help="the issue text")
    parser.add_argument("--log", action="store_true", help="write a JSONL trace to ./madsLoop_logs/")
    parser.add_argument("workdir", help="path to the repository checkout")
    return parser.parse_args(argv)


def _default_client_factory(cfg, api_key):
    from src.api import make_client
    return make_client(cfg, api_key)


def main(argv=None, client_factory=None):
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except ValueError as exc:
        warn("madsLoop: %s\nusage: madsLoop.py -p \"<problem>\" [--log] <workdir>" % exc)
        return 0
    cfg = Config.from_env()
    logger = RunLogger(args.log, quiet=cfg.quiet)
    workdir = os.path.realpath(args.workdir)
    try:
        if not os.path.isdir(workdir):
            raise RuntimeError("workdir %s is not a directory" % workdir)
        api_key = os.environ.get(API_KEY_ENV, "").strip()
        if not api_key:
            raise RuntimeError("%s is not set" % API_KEY_ENV)
        client = (client_factory or _default_client_factory)(cfg, api_key)
    except Exception as exc:
        warn("madsLoop: %s" % exc)
        logger.run_start(cfg.model_id, workdir)
        logger.run_end("error", 0)
        logger.close()
        return 0
    try:
        from src.agentic_loop import run
        run(args.problem, workdir, cfg, logger, client)
    except Exception:
        warn(traceback.format_exc())
    finally:
        logger.close()
    return 0


if __name__ == "__main__":
    # Keep stdout clean even if a library prints: route it to stderr.
    sys.stdout = sys.stderr
    sys.exit(main())
