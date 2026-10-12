#!/usr/bin/env python3
"""Trajectory: a small web front end that drives Claude Code and streams its run.

Standard library only. Run:  python3 app/server.py [--port 8765]

API
  GET  /api/defaults                -> {cwd}
  POST /api/runs                    -> {run_id}   body: {prompt, cwd, session_id?, permission_mode?}
  GET  /api/runs/<id>/events        -> text/event-stream of Claude Code stream-json events
  POST /api/runs/<id>/cancel        -> {ok}
  POST /api/replay                  -> {run_id}   body: {file?, speed?}  (replays a fixture, no cost)
"""

import argparse
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
FIXTURES = ROOT / "fixtures"
PERMISSION_MODES = {"acceptEdits", "bypassPermissions", "default", "plan"}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
}


class Run:
    """One Claude Code invocation. Events are buffered so any client can (re)attach."""

    def __init__(self):
        self.id = uuid.uuid4().hex[:12]
        self.events = []  # list of JSON-encoded strings
        self.done = False
        self.saw_result = False
        self.cancelled = False
        self.proc = None
        self.stderr_tail = []
        self.cond = threading.Condition()

    def push(self, obj):
        line = obj if isinstance(obj, str) else json.dumps(obj)
        with self.cond:
            self.events.append(line)
            self.cond.notify_all()

    def finish(self):
        with self.cond:
            self.done = True
            self.cond.notify_all()


RUNS = {}
RUNS_LOCK = threading.Lock()


def active_run():
    with RUNS_LOCK:
        return next((r for r in RUNS.values() if not r.done), None)


def register(run):
    with RUNS_LOCK:
        RUNS[run.id] = run


def start_claude(run, prompt, cwd, session_id, permission_mode):
    claude = shutil.which("claude")
    if not claude:
        run.push({"type": "app_error", "message": "The `claude` executable was not found on PATH."})
        run.push({"type": "app_done"})
        run.finish()
        return

    cmd = [claude, "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--permission-mode", permission_mode]
    if session_id:
        cmd += ["--resume", session_id]

    # Drop markers that make a nested `claude` think it runs inside another session.
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")}
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
        )
    except OSError as exc:
        run.push({"type": "app_error", "message": f"Could not start claude: {exc}"})
        run.push({"type": "app_done"})
        run.finish()
        return
    run.proc = proc

    def read_stderr():
        for line in proc.stderr:
            run.stderr_tail.append(line.rstrip())
            del run.stderr_tail[:-30]

    def read_stdout():
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                run.stderr_tail.append(line)
                continue
            if obj.get("type") == "result":
                run.saw_result = True
            run.push(obj)
        code = proc.wait()
        err_thread.join(timeout=2)
        if run.cancelled:
            run.push({"type": "app_error", "message": "Run cancelled by user."})
        elif not run.saw_result:
            tail = "\n".join(run.stderr_tail[-12:]).strip()
            msg = f"Claude Code exited with code {code} before reporting a result."
            run.push({"type": "app_error", "message": msg, "detail": tail})
        run.push({"type": "app_done", "exit_code": code})
        run.finish()

    err_thread = threading.Thread(target=read_stderr, daemon=True)
    err_thread.start()
    threading.Thread(target=read_stdout, daemon=True).start()


def start_replay(run, path, speed):
    def play():
        try:
            lines = [l for l in path.read_text().splitlines() if l.strip()]
        except OSError as exc:
            run.push({"type": "app_error", "message": f"Cannot read fixture: {exc}"})
            lines = []
        for line in lines:
            if run.cancelled:
                run.push({"type": "app_error", "message": "Run cancelled by user."})
                break
            obj = json.loads(line)
            delay = obj.pop("_delay", 0.35)
            time.sleep(max(0.0, delay / speed))
            run.push(obj)
        run.push({"type": "app_done"})
        run.finish()

    threading.Thread(target=play, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter console
        if "/events" not in (args[0] if args else ""):
            super().log_message(fmt, *args)

    # ---- helpers -------------------------------------------------------
    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    # ---- routes --------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/defaults":
            return self.send_json({"cwd": os.getcwd(), "home": str(Path.home())})
        if path.startswith("/api/runs/") and path.endswith("/events"):
            return self.stream_events(path.split("/")[3])
        return self.serve_static(path)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/runs":
            return self.create_run()
        if path == "/api/replay":
            return self.create_replay()
        if path.startswith("/api/runs/") and path.endswith("/cancel"):
            run = RUNS.get(path.split("/")[3])
            if not run:
                return self.send_json({"error": "unknown run"}, 404)
            run.cancelled = True
            if run.proc and run.proc.poll() is None:
                run.proc.terminate()
            return self.send_json({"ok": True})
        self.send_json({"error": "not found"}, 404)

    def create_run(self):
        body = self.read_json()
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return self.send_json({"error": "Prompt is empty."}, 400)
        if active_run():
            return self.send_json({"error": "A run is already in progress."}, 409)
        mode = body.get("permission_mode") or "acceptEdits"
        if mode not in PERMISSION_MODES:
            mode = "acceptEdits"

        run = Run()
        register(run)
        raw_cwd = (body.get("cwd") or "").strip()
        cwd = Path(os.path.expanduser(raw_cwd or os.getcwd()))
        if not cwd.is_absolute():
            cwd = Path.home() / cwd
        if not cwd.exists():
            run.push({"type": "app_error", "message": f"Working directory does not exist: {cwd}"})
        elif not cwd.is_dir():
            run.push({"type": "app_error", "message": f"Working directory is not a directory: {cwd}"})
        else:
            start_claude(run, prompt, str(cwd), body.get("session_id"), mode)
            return self.send_json({"run_id": run.id, "cwd": str(cwd)})
        run.push({"type": "app_done"})
        run.finish()
        self.send_json({"run_id": run.id, "cwd": str(cwd)})

    def create_replay(self):
        body = self.read_json()
        if active_run():
            return self.send_json({"error": "A run is already in progress."}, 409)
        name = Path(body.get("file") or "demo-subagent.jsonl").name
        speed = float(body.get("speed") or 1.0)
        run = Run()
        register(run)
        start_replay(run, FIXTURES / name, max(speed, 0.1))
        self.send_json({"run_id": run.id})

    def stream_events(self, run_id):
        run = RUNS.get(run_id)
        if not run:
            return self.send_json({"error": "unknown run"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        idx = 0
        try:
            while True:
                with run.cond:
                    while idx >= len(run.events) and not run.done:
                        if not run.cond.wait(timeout=15):
                            break
                    batch = run.events[idx:]
                    finished = run.done and idx + len(batch) >= len(run.events)
                if batch:
                    chunk = "".join(f"data: {line}\n\n" for line in batch)
                    self.wfile.write(chunk.encode())
                    idx += len(batch)
                else:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                if finished:
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass

    def serve_static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        target = (STATIC / path.lstrip("/")).resolve()
        if STATIC not in target.parents or not target.is_file():
            return self.send_json({"error": "not found"}, 404)
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)))
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"Trajectory running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
