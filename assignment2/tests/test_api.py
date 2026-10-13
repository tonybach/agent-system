import unittest

from src.api import ContextOverflowError, chat_with_retries, is_retryable
from src.config import Config
from tests.fakes import BadRequestError, FakeClient, NullLogger, RateLimitError, response


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.log = NullLogger()
        self.sleeps = []

    def call(self, client):
        return chat_with_retries(client, self.cfg, self.log, 1, [{"role": "user", "content": "hi"}], [],
                                 sleep=self.sleeps.append, jitter=lambda a, b: 0)

    def test_retry_then_success(self):
        client = FakeClient([RateLimitError("slow"), RateLimitError("slow"), response(prompt_tokens=7)])
        resp = self.call(client)
        self.assertEqual(resp.usage.prompt_tokens, 7)
        retries = [e for e in self.log.events if e[0] == "api_retry"]
        self.assertEqual([r[1][2] for r in retries], [1, 2])
        self.assertIn("RateLimitError: slow", retries[0][1][1])
        self.assertEqual(self.sleeps, [1, 2])
        self.assertEqual([e[0] for e in self.log.events if e[0] == "api_request"], ["api_request"])

    def test_non_retryable_raises(self):
        with self.assertRaises(ValueError):
            self.call(FakeClient([ValueError("bad")]))
        self.assertEqual(self.sleeps, [])

    def test_exhaustion(self):
        self.cfg.api_max_attempts = 3
        with self.assertRaises(RateLimitError):
            self.call(FakeClient([RateLimitError("x")] * 3))
        self.assertEqual(len(self.sleeps), 2)

    def test_status_codes(self):
        self.assertTrue(is_retryable(BadRequestError("x", 503)))
        self.assertTrue(is_retryable(BadRequestError("x", 429)))
        self.assertFalse(is_retryable(BadRequestError("x", 401)))

    def test_context_error(self):
        with self.assertRaises(ContextOverflowError):
            self.call(FakeClient([BadRequestError("maximum context length exceeded")]))

    def test_empty_choices_retried(self):
        from types import SimpleNamespace
        client = FakeClient([SimpleNamespace(choices=[], usage=None), response()])
        self.call(client)
        self.assertEqual(len(self.sleeps), 1)

    def test_missing_usage_logs_zeros(self):
        self.call(FakeClient([response(usage=False)]))
        req = [e for e in self.log.events if e[0] == "api_request"][0]
        self.assertEqual(req[1][1:], (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
