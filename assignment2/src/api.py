"""Model API client with visible, logged retries."""

import random
import re
import time

RETRYABLE_NAMES = {
    "RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError",
    "ConnectionError", "TimeoutError", "EmptyResponseError",
}
RETRYABLE_STATUS = {408, 409, 429}
CONTEXT_ERROR_RE = re.compile(r"context|token|length|too long", re.IGNORECASE)


class EmptyResponseError(Exception):
    """The API returned a response without choices."""


class ContextOverflowError(Exception):
    """The request was rejected because the prompt is too long."""


def make_client(cfg, api_key):
    from openai import OpenAI  # imported lazily so tests do not need the package

    return OpenAI(base_url=cfg.base_url, api_key=api_key, timeout=cfg.api_timeout, max_retries=0)


def _status(exc):
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def is_retryable(exc):
    if type(exc).__name__ in RETRYABLE_NAMES:
        return True
    status = _status(exc)
    return status is not None and (status in RETRYABLE_STATUS or status >= 500)


def is_context_error(exc):
    return _status(exc) == 400 and bool(CONTEXT_ERROR_RE.search(str(exc)))


def _describe(exc):
    return ("%s: %s" % (type(exc).__name__, exc))[:300]


def chat_with_retries(client, cfg, logger, iteration, messages, tools, sleep=time.sleep, jitter=random.uniform):
    """Call the chat API; retry transient failures with exponential backoff.

    Logs ``api_retry`` before each sleep and ``api_request`` on success.
    Raises ContextOverflowError for 400s that look like an over-long prompt,
    and re-raises everything else that is not retryable or after the last attempt.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = client.chat.completions.create(model=cfg.model_id, messages=messages, tools=tools)
            if not getattr(resp, "choices", None):
                raise EmptyResponseError("response has no choices")
        except Exception as exc:
            if is_context_error(exc):
                raise ContextOverflowError(_describe(exc)) from exc
            if not is_retryable(exc) or attempt >= cfg.api_max_attempts:
                raise
            backoff = round(min(cfg.api_backoff_cap, 2 ** (attempt - 1)) + jitter(0, 1), 2)
            logger.api_retry(iteration, _describe(exc), backoff)
            sleep(backoff)
            continue
        usage = getattr(resp, "usage", None)
        if usage is None:
            logger.progress("[iter %d] warning: response has no usage; logging zeros" % iteration)
            pt = ct = tt = 0
        else:
            pt = int(getattr(usage, "prompt_tokens", 0) or 0)
            ct = int(getattr(usage, "completion_tokens", 0) or 0)
            tt = int(getattr(usage, "total_tokens", 0) or (pt + ct))
        logger.api_request(iteration, pt, ct, tt)
        return resp
