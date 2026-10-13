"""Harness configuration: constants with MADSLOOP_* environment overrides."""

import os
from dataclasses import dataclass, field

MODEL_ID = "qwen3.6-35b-a3b"
BASE_URL = "https://api.cs2680.com/v1"
API_KEY_ENV = "CS2680_API_KEY"


def _env_int(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Config:
    model_id: str = MODEL_ID
    base_url: str = BASE_URL

    # Context management
    tool_output_limit: int = 12000
    read_file_max_lines: int = 500
    compact_prompt_tokens: int = 90000
    compact_stage2_tokens: int = 110000
    compact_keep_tool_msgs: int = 12

    # Run limits
    max_iterations: int = 100
    max_wall_seconds: int = 2700

    # Tool limits
    bash_timeout_default: int = 300
    bash_timeout_max: int = 900

    # API
    api_timeout: float = 300.0
    api_max_attempts: int = 6
    api_backoff_cap: float = 60.0

    # Loop behaviour
    max_nudges: int = 1
    max_done_rejections: int = 1
    warn_steps_left: int = 3
    warn_seconds_left: int = 300

    quiet: bool = field(default=False)

    @classmethod
    def from_env(cls):
        cfg = cls()
        # Point the harness at another OpenAI-compatible endpoint (e.g. OpenRouter or a local
        # server). The defaults are the course proxy and model.
        cfg.base_url = os.environ.get("MADSLOOP_BASE_URL", "").strip() or cfg.base_url
        cfg.model_id = os.environ.get("MADSLOOP_MODEL", "").strip() or cfg.model_id
        cfg.tool_output_limit = _env_int("MADSLOOP_TOOL_OUTPUT_LIMIT", cfg.tool_output_limit)
        cfg.compact_prompt_tokens = _env_int("MADSLOOP_COMPACT_TOKENS", cfg.compact_prompt_tokens)
        cfg.compact_stage2_tokens = max(cfg.compact_stage2_tokens, cfg.compact_prompt_tokens + 20000)
        cfg.max_iterations = _env_int("MADSLOOP_MAX_ITERATIONS", cfg.max_iterations)
        cfg.max_wall_seconds = _env_int("MADSLOOP_MAX_SECONDS", cfg.max_wall_seconds)
        cfg.quiet = os.environ.get("MADSLOOP_QUIET", "") not in ("", "0")
        return cfg
